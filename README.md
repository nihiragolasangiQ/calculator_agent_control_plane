# IGA Incident Analysis Agent — Control Plane

An enterprise-grade, manifest-driven AI agent platform built on [Google ADK](https://google.github.io/adk-docs/) and Gemini 2.5 Flash.

The system acts as an **L2 Incident Copilot** for IGA (Identity Governance & Administration) operations teams. It reads pre-computed pipeline results from BigQuery and surfaces them as triage dashboards and investigation reports — with enforced PII redaction, LLM policy guardrails, and a full orchestration layer.

**Core philosophy:** Drop a YAML file, get a working agent. Change the YAML, the agent changes. No Python edits required.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [How It Works — Startup Pipeline](#how-it-works--startup-pipeline)
- [How It Works — Request Lifecycle](#how-it-works--request-lifecycle)
- [The Three Config Layers](#the-three-config-layers)
- [Running Modes](#running-modes)
  - [Mode 1 — Single Agent (default)](#mode-1--single-agent-default)
  - [Mode 2 — Orchestrator Mode](#mode-2--orchestrator-mode)
- [Security & Guardrails](#security--guardrails)
- [BigQuery Data Layer](#bigquery-data-layer)
- [Adding a New Agent](#adding-a-new-agent)
- [Manifest Reference](#manifest-reference)
- [Environment Variable Reference](#environment-variable-reference)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                           │
│               (ADK Web UI  /  Terminal REPL)                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
            ┌───────────────▼───────────────┐
            │        ORCHESTRATOR           │  ← ORCHESTRATOR_MODE=true
            │   (routes, never answers)     │
            └───────────────┬───────────────┘
                            │  AgentTool call
            ┌───────────────▼───────────────┐
            │     IGA INCIDENT AGENT        │  ← ORCHESTRATOR_MODE=false (direct)
            │   Gemini 2.5 Flash / ADK      │
            └───────────────┬───────────────┘
                            │  tool call
            ┌───────────────▼───────────────┐
            │        TOOL LAYER             │
            │  LLM Policy Guardrail check   │
            │  → BigQuery (ADC auth)        │
            └───────────────┬───────────────┘
                            │  result
            ┌───────────────▼───────────────┐
            │      CALLBACK LAYER           │
            │  after_tool: capture PII      │
            │  after_model: redact PII      │
            └───────────────┬───────────────┘
                            │
                     Final Response
```

---

## Project Structure

```
control_plane/
│
├── .env                                          # Secrets — never committed
├── .env.example                                  # Template — copy to .env and fill in
├── requirements.txt
├── commands.txt                                  # Quick command reference
├── README.md
│
└── orchestrator/
    ├── __init__.py                               # Lazy root_agent export for `adk web`
    ├── agent.py                                  # ADK web entry point — builds root_agent
    ├── agent_from_manifest.py                    # Core pipeline: load → validate → merge → build
    ├── config.py                                 # Env-var layer — Settings dataclass singleton
    ├── orchestrator.py                           # Orchestrator mode entry (ORCHESTRATOR_MODE=true)
    │
    ├── manifest/
    │   ├── incident_agent_manifest.yaml          # IGA incident agent definition
    │   └── orchestrator_manifest.yaml            # Orchestrator definition (sub-agent routing)
    │
    └── incident_agent/
        ├── tools.py                              # 5 ADK tool wrappers with guardrail checks
        ├── bigquery_tool.py                      # BigQuery data layer (ADC auth, lazy client)
        ├── pii_redactor.py                       # after_model + after_tool PII callbacks
        └── llm_policy_guardrail.py               # LLM-based tool call validation
```

---

## How It Works — Startup Pipeline

Every time the agent starts, it runs this pipeline before accepting any request:

```
.env  +  manifest.yaml
         │
         ▼
      config.py
      Reads all env vars at boot → frozen Settings dataclass singleton.
      Nothing re-reads .env after this point.
         │
         ▼
  agent_from_manifest.py
         │
         ├─ load_manifest()
         │    Reads the YAML file from MANIFEST_PATH.
         │    Fails fast if file not found.
         │
         ├─ validate_manifest()
         │    Checks required keys (identity, instruction, model, capabilities, policy).
         │    Verifies tool_ids exist in TOOL_REGISTRY.
         │    Checks sub-agent manifest_paths are readable.
         │    Warns on non-blocking issues (missing version, unused tools).
         │    Raises on fatal issues — agent will not start broken.
         │
         ├─ merge_config()
         │    Resolves three-layer hierarchy:
         │    ENV VAR  wins  →  YAML value  wins  →  hardcoded default
         │    Builds MergedConfig with all resolved values.
         │    Dynamically imports and instantiates callback factories.
         │    Constructs MCPToolset / AgentTool / function references.
         │
         └─ build_agent()
              Constructs ADK Agent with:
                - resolved model name + inference params
                - resolved tool list
                - resolved system instruction
                - resolved callbacks (after_model, after_tool)
              Returns root_agent — ready to serve.
```

---

## How It Works — Request Lifecycle

What happens from the moment a user sends a message to when they get a response:

```
User sends message
        │
        ▼
┌───────────────────────────────────────────────┐
│  ORCHESTRATOR_MODE=true?                      │
│  Yes → Orchestrator LLM receives message      │
│         Orchestrator MUST call incident_agent  │
│         (never answers directly)              │
│  No  → Incident Agent receives directly       │
└───────────────────────────┬───────────────────┘
                            │
                            ▼
              Incident Agent LLM selects tool
              (fetch_incidents_by_date,
               build_triage_dashboard,
               fetch_ai_analysis, etc.)
                            │
                            ▼
              tools.py: _guard_or_block()
              Calls LLM Policy Guardrail before execution
                            │
                    ┌───────┴────────┐
                 BLOCKED          ALLOWED
                    │                │
               Return error          ▼
                         bigquery_tool.*()
                         → BigQuery JOIN:
                           raw_incidents + analysis_result
                         → Returns structured dict
                            │
                            ▼
              after_tool_callback (pii_redactor.py)
              Captures caller / assigned_to / resolved_by
              into session state for later redaction
                            │
                            ▼
              Incident Agent LLM formats response
              (Markdown dashboard table / investigation report)
                            │
                            ▼
              after_model_callback (pii_redactor.py)
              Calls Gemini to scan output text
              Replaces all person names → [NAME REDACTED]
                            │
                            ▼
                   Final response → User
```

---

## The Three Config Layers

Resolution order: **Env Var > YAML manifest > hardcoded default**

### Layer 1 — Environment Variables → `config.py`

All env vars are read once at startup and locked into a frozen `Settings` dataclass. The singleton is available everywhere as `settings`.

```
GOOGLE_API_KEY            →  Gemini authentication
ORCHESTRATOR_MODE         →  which agent is the root
MANIFEST_PATH             →  which YAML to load
AGENT_MODEL_NAME          →  settings.agent.model_name
CONFIDENCE_THRESHOLD      →  settings.policy.confidence_threshold
BQ_PROJECT                →  BigQuery GCP project
GUARDRAIL_FAIL_CLOSED     →  guardrail block-on-error behavior
```

### Layer 2 — `manifest.yaml`

The YAML manifest is the single source of truth for what an agent *is*:
- **Identity** — name, version, owner, description
- **Instruction** — full system prompt
- **Model** — base model, temperature, max tokens
- **Capabilities** — tools list (functions / sub-agents / MCP servers) + callbacks
- **Policy** — allowed/denied problem types, rate limits, escalation config
- **Observability** — logging, metrics, alerts
- **Deployment** — target environments, lifecycle limits, canary config

### Layer 3 — `merge_config()` in `agent_from_manifest.py`

Merges both layers into a single typed `MergedConfig` object. Env vars win at every field. YAML fills the gaps. Hardcoded defaults are last resort. The resolved config is what the ADK `Agent` is built from.

---

## Running Modes

### Mode 1 — Single Agent (default)

`ORCHESTRATOR_MODE=false` (or unset). The incident agent is loaded directly as the root agent.

```
User  →  IGA Incident Agent  →  BigQuery  →  Response
```

**1. Prerequisites**

```bash
# Clone and install
pip install -r requirements.txt

# Configure secrets
cp .env.example .env
# Edit .env — set GOOGLE_API_KEY and BigQuery credentials
```

**2. Authenticate with GCP** (for BigQuery access)

```bash
gcloud auth application-default login
```

**3. Start the agent**

```bash
# ADK Web UI (browser) — default port 8000
adk web .

# ADK Web UI — explicit manifest path
MANIFEST_PATH=orchestrator/manifest/incident_agent_manifest.yaml adk web .

# Terminal REPL
python -m orchestrator.agent
```

Open `http://localhost:8000` and select `incident_agent` from the dropdown.

---

### Mode 2 — Orchestrator Mode

`ORCHESTRATOR_MODE=true`. The orchestrator wraps the incident agent as a sub-agent tool via `AgentTool`. Routing is completely invisible to the user.

```
User  →  Orchestrator  →  incident_agent (AgentTool)  →  BigQuery  →  Response
```

The orchestrator's system prompt enforces: *"You MUST call incident_agent for every request. NEVER answer yourself."*

```bash
# ADK Web UI
ORCHESTRATOR_MODE=true adk web .

# .env alternative (set once, no inline override needed)
# ORCHESTRATOR_MODE=true
# adk web .
```

**When to use orchestrator mode:**
- When you plan to add more specialist sub-agents in future
- When you want a single routing layer that scales to multiple domains
- When you need centralized policy at the routing level

---

## Security & Guardrails

Every response passes through four independent defense layers in sequence.

```
Request
   │
   ▼
Layer 1 — Policy Enforcement (agent_from_manifest.py)
   Checks denied_problem_types from manifest/env.
   Blocks before Gemini ever sees the message.
   │
   ▼
Layer 2 — LLM Policy Guardrail (llm_policy_guardrail.py)
   Fires before every tool call.
   Gemini evaluates: "Is this a legitimate incident lookup or prompt injection?"
   Returns (allow: bool, reason: str).
   GUARDRAIL_FAIL_CLOSED=1 → block on any evaluation error (default, safe).
   GUARDRAIL_FAIL_CLOSED=0 → allow on error (open, use only in dev).
   │
   ▼
Layer 3 — PII Capture (pii_redactor.py — after_tool_callback)
   Intercepts every tool response before the LLM sees it.
   Extracts caller, assigned_to, resolved_by fields.
   Stores them in session state under _pii_* keys for use in Layer 4.
   │
   ▼
Layer 4 — PII Redaction (pii_redactor.py — after_model_callback)
   Intercepts the LLM's final output before it reaches the user.
   Uses known_names from session state + fresh LLM scan.
   Replaces every person name, email, and username with [NAME REDACTED].
   Returns redacted LlmResponse. Original text never reaches the user.
```

| Layer | File | Trigger | Action on violation |
|---|---|---|---|
| Policy enforcement | `agent_from_manifest.py` | Every request | Reject with reason |
| LLM policy guardrail | `llm_policy_guardrail.py` | Before every tool call | Block tool execution |
| PII capture | `pii_redactor.py` | After every tool call | Store in session state |
| PII redaction | `pii_redactor.py` | After every model response | Rewrite output |

---

## BigQuery Data Layer

Authentication uses **GCP Application Default Credentials (ADC)** — no service account key files in code. The BigQuery client is a lazy singleton created on first tool call.

### Configuration

| Env Var | Default | Description |
|---|---|---|
| `BQ_PROJECT` | `gsk-corp-ai-tech-ops-dev` | GCP project ID |
| `BQ_DATASET` | `snow` | Dataset name |
| `BQ_RAW_TABLE` | `raw_incidents` | Source incidents from ServiceNow |
| `BQ_RESULT_TABLE` | `analysis_result` | AI pipeline classification results |

### Tables

**`raw_incidents`** — Source incidents ingested from ServiceNow/monitoring:

| Column | Description |
|---|---|
| `number` | Incident ID (e.g. INC0012345) |
| `caller` | Person who raised the incident |
| `short_description` | One-line summary |
| `description` | Full incident description |
| `category` | Incident category |
| `priority` | P1 / P2 / P3 / P4 |
| `state` | Current state |
| `assignment_group` | Team assigned |
| `assigned_to` | Individual assignee |
| `opened_at` | Timestamp opened |
| `closed_at` | Timestamp closed |
| `ingested_at` | Pipeline ingestion timestamp |

**`analysis_result`** — AI pipeline classifications (joined to raw_incidents on `number`):

| Column | Description |
|---|---|
| `incident_type` | `NOISE` / `KB FOUND` / `RCA REQUIRED` |
| `confidence_score` | Model confidence 0–1 |
| `ai_analysis` | Full AI analysis text |
| `summary` | Short summary |
| `recommended_actions` | Suggested next steps |
| `kb_article_title` | KB article name (KB FOUND only) |
| `kb_article_url` | KB article URL (KB FOUND only) |
| `rca_reason` | Why RCA is needed (RCA REQUIRED only) |
| `noise_reason` | Why classified as noise (NOISE only) |
| `lookalike_incidents` | Similar past incident IDs |

### Incident Classification

| Type | Meaning | Recommended Action |
|---|---|---|
| `NOISE` | Automated / non-actionable alert | Close without investigation |
| `KB FOUND` | Known issue — matching KB article exists | Follow KB article steps |
| `RCA REQUIRED` | Unknown issue — no KB match found | Perform root cause analysis |

### Available Tools

| Tool | Description |
|---|---|
| `fetch_ai_analysis` | Fetch AI classification and analysis for a single incident ID |
| `fetch_incident_details` | Fetch full raw incident record by incident ID |
| `fetch_incidents_by_date` | Date-range query with optional incident type filter, joins both tables |
| `build_triage_dashboard` | Aggregated triage summary with classification counts and effort saved |
| `list_columns` | Return available column names from raw_incidents |

---

## Adding a New Agent

**Drop one YAML file. That's it.**

The orchestrator auto-discovers every `*_manifest.yaml` in `orchestrator/manifest/` at startup (except `orchestrator_manifest.yaml` itself). No other file needs to change — not the orchestrator manifest, not any Python code.

### Step 1 — Write your agent manifest

Drop it in `orchestrator/manifest/my_agent_manifest.yaml`:

```yaml
identity:
  agent_id: "my_agent_001"
  name: "my_agent"
  display_name: "My Agent"
  description: "Handles X, Y, and Z domain queries."   # ← drives routing
  version: "1.0.0"
  status: "active"

instruction: |
  You are a helpful agent that ...
  [your full system prompt here]

model:
  base_model_id: "gemini-2.5-flash"
  inference:
    temperature: 0.1
    max_output_tokens: 4096

capabilities:
  tools:
    - tool_id: "my_mcp_tool"
      type: "mcp_server"
      url: "http://localhost:9000/mcp"
      on_unavailable: "warn"

policy:
  confidence_threshold: 0.7
  denied_problem_types: []
  rate_limits:
    requests_per_minute: 30
    max_concurrent_sessions: 5

deployment:
  lifecycle:
    max_turns: 20
    session_timeout_seconds: 300
```

### Step 2 — Restart the orchestrator

```bash
ORCHESTRATOR_MODE=true adk web .
```

On startup you will see:
```
  Orchestrator mode — auto-discovering specialist agents...
  Found 2 specialist agent(s) in orchestrator/manifest/

  Discovered agent: incident_agent (incident_agent_manifest.yaml)
  Discovered agent: my_agent (my_agent_manifest.yaml)
```

### Step 3 — Done

The orchestrator reads `identity.description` from your manifest and automatically builds its routing instruction to include your new agent. The LLM now knows when to call it.

> **The `identity.description` field drives routing.** Write it as a clear statement of what domain or queries the agent handles — this is what the orchestrator LLM reads to decide which agent to call for a given user request.

### For local Python function tools

If your agent uses `type: "function"` tools instead of MCP, add the Python callable to `TOOL_REGISTRY` in `agent_from_manifest.py` — one dict entry. MCP-based agents require zero Python changes.

---

## Manifest Reference

### `identity`

| Field | Required | Description |
|---|---|---|
| `agent_id` | Yes | Unique identifier string |
| `name` | Yes | Module-style name used by ADK |
| `display_name` | Yes | Human-readable name shown in UI |
| `description` | Yes | Purpose description |
| `version` | No | Semver string |
| `status` | No | `active` / `deprecated` / `experimental` |

### `instruction`

Full system prompt as a YAML block scalar. Supports `|` (literal, preserves newlines) or `>` (folded). This is what Gemini receives as its system instruction.

### `model`

| Field | Description |
|---|---|
| `base_model_id` | Gemini model string (e.g. `gemini-2.5-flash`) |
| `inference.temperature` | Sampling temperature |
| `inference.max_output_tokens` | Max tokens in response |
| `inference.top_p` | Nucleus sampling parameter |

### `capabilities.tools`

| Field | Description |
|---|---|
| `tool_id` | Identifier — must match TOOL_REGISTRY key for `function` type |
| `type` | `function` / `sub_agent` / `mcp_server` / `human_in_loop` |
| `allowed` | `true` / `false` — whether tool is active |
| `manifest_path` | Path to sub-agent manifest (sub_agent type only) |
| `url` | HTTP endpoint (mcp_server type only) |
| `allowed_tool_ids` | Whitelist of tool names exposed by MCP server |
| `on_unavailable` | `fail` = crash at startup / `warn` = skip with fallback |
| `fallback_tool_id` | Local function to use if MCP server is unreachable |
| `auth.type` | `none` / `api_key` / `bearer` |
| `auth.secret_ref` | Name of env var holding the credential value |

### `capabilities.callbacks`

| Field | Description |
|---|---|
| `after_model_callback` | `module.path:factory_function` — called after every LLM response |
| `after_tool_callback` | `module.path:factory_function` — called after every tool execution |

Callbacks are resolved dynamically at build time via `importlib`. The factory is called once; the returned function is registered as the callback.

### `policy`

| Field | Description |
|---|---|
| `confidence_threshold` | Float 0–1 — minimum confidence to act without escalation |
| `allowed_problem_types` | List of problem type strings that are permitted |
| `denied_problem_types` | List of problem type strings that are blocked pre-LLM |
| `rate_limits.requests_per_minute` | RPM cap |
| `rate_limits.max_concurrent_sessions` | Concurrent session cap |
| `escalation.enabled` | Whether human escalation is enabled |

### `deployment.lifecycle`

| Field | Description |
|---|---|
| `max_turns` | Maximum turns per session |
| `session_timeout_seconds` | Idle session timeout |
| `graceful_shutdown_seconds` | Shutdown grace period |

---

## Environment Variable Reference

All YAML values can be overridden at runtime via env vars. Inline overrides (`KEY=value adk web .`) take effect immediately without editing any file.

### Core

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | — | Gemini API key (required if not using Vertex AI) |
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE` | Set `TRUE` to use Vertex AI instead of AI Studio |
| `ORCHESTRATOR_MODE` | `false` | `true` = load orchestrator as root agent |
| `MANIFEST_PATH` | `orchestrator/manifest/incident_agent_manifest.yaml` | Path to agent manifest |
| `RUN_MODE` | `ui` | `ui` = ADK web / `terminal` = REPL |

### Agent & Model

| Variable | Overrides | Description |
|---|---|---|
| `AGENT_MODEL_NAME` | `model.base_model_id` | Gemini model to use |
| `MAX_TURNS` | `deployment.lifecycle.max_turns` | Max turns per session |
| `SESSION_TIMEOUT` | `deployment.lifecycle.session_timeout_seconds` | Idle timeout in seconds |

### Policy

| Variable | Overrides | Description |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | `policy.confidence_threshold` | Min confidence threshold |
| `ALLOWED_PROBLEM_TYPES` | `policy.allowed_problem_types` | Comma-separated list |
| `DENIED_PROBLEM_TYPES` | `policy.denied_problem_types` | Comma-separated list |
| `RATE_LIMIT_RPM` | `policy.rate_limits.requests_per_minute` | Requests per minute cap |
| `MAX_CONCURRENT_SESSIONS` | `policy.rate_limits.max_concurrent_sessions` | Session concurrency cap |

### BigQuery

| Variable | Default | Description |
|---|---|---|
| `BQ_PROJECT` | `gsk-corp-ai-tech-ops-dev` | GCP project ID |
| `BQ_DATASET` | `snow` | BigQuery dataset name |
| `BQ_RAW_TABLE` | `raw_incidents` | Source incidents table |
| `BQ_RESULT_TABLE` | `analysis_result` | AI results table |

### Guardrail

| Variable | Default | Description |
|---|---|---|
| `ENABLE_LLM_POLICY_GUARDRAIL` | `1` | `0` to disable guardrail entirely |
| `GUARDRAIL_MODEL` | `gemini-2.5-flash` | Model used for guardrail evaluation |
| `GUARDRAIL_FAIL_CLOSED` | `1` | `1` = block on error (safe) / `0` = allow on error |
