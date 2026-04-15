"""Central configuration for the Calculator Agent control plane.

Resolution order: Env Var > YAML manifest > hardcoded default.
This module owns the env-var layer. The manifest layer is merged on top
in agent_from_manifest.py via merge_config().
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------
AGENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = AGENT_DIR.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _resolve_env_path(
    env_name: str,
    *,
    default: Path,
    fallback: Path | None = None,
) -> Path:
    env_value = os.getenv(env_name)
    if env_value and env_value.strip():
        configured = Path(env_value.strip())
        if not configured.is_absolute():
            configured = PROJECT_ROOT / configured
        return configured.resolve()

    candidates = [default]
    if fallback is not None:
        candidates.append(fallback)
    return _resolve_preferred_path(*candidates)


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ManifestConfig:
    """Where to find the agent manifest YAML."""
    manifest_path: Path = field(
        default_factory=lambda: _resolve_env_path(
            "MANIFEST_PATH",
            default=AGENT_DIR / "manifest" / "calculator_agent_manifest.yaml",
        )
    )


@dataclass(frozen=True)
class PolicyConfig:
    """Policy defaults — YAML values override these when merged."""
    confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
    )
    allowed_problem_types: tuple[str, ...] = field(
        default_factory=lambda: _env_csv(
            "ALLOWED_PROBLEM_TYPES",
            ["arithmetic", "algebra", "word_problems"],
        )
    )
    denied_problem_types: tuple[str, ...] = field(
        default_factory=lambda: _env_csv(
            "DENIED_PROBLEM_TYPES",
            ["calculus", "differential_equations", "abstract_algebra"],
        )
    )


@dataclass(frozen=True)
class RateLimitConfig:
    """Rate-limit defaults — YAML values override these when merged."""
    requests_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_RPM", "30"))
    )
    max_concurrent_sessions: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_SESSIONS", "5"))
    )


@dataclass(frozen=True)
class AgentConfig:
    """Agent runtime defaults — YAML values override these when merged."""
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
    """Top-level settings object — single source of truth for env-var layer."""
    manifest: ManifestConfig = field(default_factory=ManifestConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    rate_limits: RateLimitConfig = field(default_factory=RateLimitConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    @property
    def google_api_key(self) -> str | None:
        return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


settings = Settings()

# Expose HF_HUB_OFFLINE to any dependency that reads the process environment.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
