# Calculator Agent — Control Plane

A manifest-driven AI agent built with [Google ADK](https://google.github.io/adk-docs/) and Gemini. Feed it a YAML file, get a working agent. Change the YAML, the agent changes. No code edits needed.

---

## Project Structure

```
calculator_agent_control_plane/
├── .env                          # Your API keys (never committed)
├── .env.example                  # Template — copy this to .env
├── agent.yaml                    # Reference manifest schema
├── calculator_agent/
│   ├── __init__.py               # Exposes root_agent for ADK web
│   ├── agent.py                  # Builds root_agent from YAML (web UI entry point)
│   ├── agent_from_manifest.py    # Full control plane pipeline (terminal mode)
│   ├── config.py                 # Env-var layer — frozen dataclasses
│   ├── tools.py                  # Calculator tool functions
│   └── manifest/
│       └── calculator_agent_manifest.yaml   # Agent definition
```

---

## How to Run

### Prerequisites

Copy `.env.example` to `.env` and fill in your API key:

```
GOOGLE_API_KEY=your_gemini_api_key_here
GOOGLE_GENAI_USE_VERTEXAI=FALSE
RUN_MODE=ui
```

### UI Mode (browser)

```bash
pip install -r requirements.txt
adk web . --port 8000
```

Open `http://localhost:8000` in your browser.

### Terminal Mode (REPL)

```bash
python -m calculator_agent.agent_from_manifest
```

---

## How the Code Runs

### 1. Entry point — `__init__.py`

When ADK web starts, it imports the `calculator_agent` package, which triggers `__init__.py`:

```python
from .agent import root_agent
```

This kicks off `agent.py`.

### 2. `agent.py` — builds the agent for the web UI

Three things happen in order:

1. **`config.py` is imported** — reads your `.env` file and locks all values into frozen dataclasses. `settings` is now a singleton available everywhere.
2. **YAML manifest is loaded** — opened using the path from `settings.manifest.manifest_path`. The `instruction` block is extracted.
3. **ADK `Agent` is constructed** using:
   - `model` → from `AGENT_MODEL_NAME` env var, or `model.base_model_id` from YAML
   - `instruction` → the system prompt written in the YAML under `instruction:`
   - `tools` → the 5 Python functions from `tools.py`

This `root_agent` is what the web UI talks to.

### 3. Terminal mode — `agent_from_manifest.py`

In terminal mode the pipeline is explicit and sequential:

```
load_manifest()               reads YAML from disk
        ↓
merge_config()                combines .env + YAML → typed MergedConfig
        ↓
enforce_policy()              checks input against denied_problem_types
        ↓                     if blocked → prints reason and stops
build_agent_from_manifest()   constructs the ADK Agent
        ↓
Runner → ADK                  sends message to Gemini, streams response back
```

---

## Architecture — Three Layers

```
Layer 1 — .env file       →  config.py reads into frozen dataclasses
Layer 2 — YAML manifest   →  agent_from_manifest.py reads and parses
Layer 3 — merge_config()  →  combines both into one resolved config
```

**Resolution order: Env Var > YAML > Hardcoded default**

---

## Where Variables Live

| Variable | Defined in | Used in |
|---|---|---|
| `settings` | `config.py` (singleton) | `agent.py`, `agent_from_manifest.py` |
| `_manifest` | `agent.py` (local) | same file only |
| `merged` | `merge_config()` | passed to `enforce_policy()` and `build_agent_from_manifest()` |
| `root_agent` | `agent.py` | picked up by ADK web automatically |
| `TOOL_REGISTRY` | `agent_from_manifest.py` | maps YAML tool names to Python functions |

---

## What the YAML Controls

| YAML section | What it drives |
|---|---|
| `instruction` | Agent persona, rules, and behaviour |
| `model.base_model_id` | Which Gemini model to use |
| `capabilities.tools` | Which tools the agent can call |
| `policy.denied_problem_types` | Requests blocked before reaching the agent |
| `policy.confidence_threshold` | When to escalate to human review |
| `policy.rate_limits` | RPM and max concurrent sessions |
| `deployment.lifecycle` | Max turns per session, session timeout |

---

## Env Var Overrides

All YAML values can be overridden at runtime via env vars without touching any files:

| Env Var | Overrides |
|---|---|
| `AGENT_MODEL_NAME` | `model.base_model_id` |
| `MANIFEST_PATH` | Path to the YAML manifest |
| `CONFIDENCE_THRESHOLD` | `policy.confidence_threshold` |
| `ALLOWED_PROBLEM_TYPES` | `policy.allowed_problem_types` (comma-separated) |
| `DENIED_PROBLEM_TYPES` | `policy.denied_problem_types` (comma-separated) |
| `RATE_LIMIT_RPM` | `policy.rate_limits.requests_per_minute` |
| `MAX_CONCURRENT_SESSIONS` | `policy.rate_limits.max_concurrent_sessions` |
| `MAX_TURNS` | `deployment.lifecycle.max_turns` |
| `SESSION_TIMEOUT` | `deployment.lifecycle.session_timeout_seconds` |
