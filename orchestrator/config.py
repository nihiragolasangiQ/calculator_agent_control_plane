from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

AGENT_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT = AGENT_DIR.parent


def _env_csv(name: str, default: list[str]) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return tuple(default)
    values = [v.strip() for v in raw.split(",") if v.strip()]
    return tuple(values or default)


def _resolve_preferred_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _resolve_env_path(env_name: str, *, default: Path, fallback: Path | None = None) -> Path:
    env_value = os.getenv(env_name)
    if env_value and env_value.strip():
        configured = Path(env_value.strip())
        if not configured.is_absolute():
            configured = PROJECT_ROOT / configured
        return configured.resolve()
    candidates = [default] + ([fallback] if fallback else [])
    return _resolve_preferred_path(*candidates)


@dataclass(frozen=True)
class ManifestConfig:
    manifest_path: Path = field(
        default_factory=lambda: _resolve_env_path(
            "MANIFEST_PATH",
            default=AGENT_DIR / "manifest" / "incident_agent_manifest.yaml",
        )
    )


@dataclass(frozen=True)
class PolicyConfig:
    confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
    )
    allowed_problem_types: tuple[str, ...] = field(
        default_factory=lambda: _env_csv(
            "ALLOWED_PROBLEM_TYPES",
            ["incident_lookup", "triage_dashboard", "date_range_query", "column_listing"],
        )
    )
    denied_problem_types: tuple[str, ...] = field(
        default_factory=lambda: _env_csv(
            "DENIED_PROBLEM_TYPES",
            ["code_execution", "image_analysis", "creative_writing"],
        )
    )


@dataclass(frozen=True)
class RateLimitConfig:
    requests_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_RPM", "30"))
    )
    max_concurrent_sessions: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_SESSIONS", "5"))
    )


@dataclass(frozen=True)
class AgentConfig:
    model_name: str = field(
        default_factory=lambda: os.getenv("AGENT_MODEL_NAME", "gemini-2.5-flash")
    )
    run_mode: str = field(
        default_factory=lambda: os.getenv("RUN_MODE", "ui")
    )
    max_turns: int = field(
        default_factory=lambda: int(os.getenv("MAX_TURNS", "20"))
    )
    session_timeout: int = field(
        default_factory=lambda: int(os.getenv("SESSION_TIMEOUT", "300"))
    )


@dataclass(frozen=True)
class Settings:
    manifest:    ManifestConfig   = field(default_factory=ManifestConfig)
    policy:      PolicyConfig     = field(default_factory=PolicyConfig)
    rate_limits: RateLimitConfig  = field(default_factory=RateLimitConfig)
    agent:       AgentConfig      = field(default_factory=AgentConfig)

    @property
    def google_api_key(self) -> str | None:
        return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


settings = Settings()

os.environ.setdefault("HF_HUB_OFFLINE", "1")
