from __future__ import annotations

import json
import logging
import os
from typing import Optional

from google import genai

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        _client = genai.Client(api_key=api_key) if api_key else genai.Client()
    return _client


def _guardrail_model() -> str:
    return os.getenv("GUARDRAIL_MODEL", os.getenv("AGENT_MODEL_NAME", "gemini-2.5-flash"))


def _llm_redact_text(text: str, known_names: list[str] | None = None) -> str:
    if not text:
        return text

    prompt = f"""You are a strict PII-redaction engine.

Redact the following from the INPUT TEXT:
- Person names → [NAME REDACTED]
- Email addresses → [EMAIL REDACTED]
- Usernames / account IDs that identify people → [USER REDACTED]

Do NOT alter: incident IDs, KB titles, URLs, markdown structure, or non-PII technical content.
If known names are provided, always redact them wherever they appear.
Known names: {json.dumps(known_names or [], ensure_ascii=False)}

Return ONLY the redacted text with no other commentary.

INPUT TEXT:
{text}""".strip()

    try:
        resp = _get_client().models.generate_content(model=_guardrail_model(), contents=prompt)
        out  = (getattr(resp, "text", "") or "").strip()
        return out if out else text
    except Exception as exc:
        logger.warning("PII redaction failed, returning original text: %s", exc)
        return text


def redact_text(text: str, known_names: list[str] | None = None) -> str:
    return _llm_redact_text(text, known_names=known_names)


def make_pii_redaction_callback():
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types as genai_types

    def _callback(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
        known_names: list[str] = []
        try:
            state = callback_context.state if hasattr(callback_context, "state") else {}
            for key in ("_pii_caller", "_pii_assigned_to", "_pii_resolved_by"):
                val = state.get(key, "")
                if val and isinstance(val, str):
                    known_names.append(val)
        except Exception:
            pass

        if not llm_response or not llm_response.content or not llm_response.content.parts:
            return None

        changed, new_parts = False, []
        for part in llm_response.content.parts:
            if hasattr(part, "text") and part.text:
                redacted = redact_text(part.text, known_names=known_names or None)
                if redacted != part.text:
                    changed = True
                    new_parts.append(genai_types.Part(text=redacted))
                else:
                    new_parts.append(part)
            else:
                new_parts.append(part)

        if not changed:
            return None

        logger.info("PII guardrail: redaction applied")
        new_content = genai_types.Content(role=llm_response.content.role, parts=new_parts)
        return llm_response.model_copy(update={"content": new_content})

    return _callback


def make_pii_tool_callback():
    import json as _json
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext

    def _tool_callback(tool: BaseTool, args: dict, tool_context: ToolContext, tool_response: dict):
        try:
            payload = tool_response
            if isinstance(payload, str):
                try:
                    payload = _json.loads(payload)
                except Exception:
                    return None
            if isinstance(payload, dict) and "result" in payload:
                payload = payload["result"]
            if not isinstance(payload, dict):
                return None

            state = tool_context.state
            for src_key, state_key in (
                ("caller",      "_pii_caller"),
                ("assigned_to", "_pii_assigned_to"),
                ("resolved_by", "_pii_resolved_by"),
            ):
                val = str(payload.get(src_key, "") or "").strip()
                if val and len(val) > 2:
                    state[state_key] = val
        except Exception as exc:
            logger.debug("PII tool callback error (non-fatal): %s", exc)
        return None

    return _tool_callback
