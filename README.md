# Agent Control Plane

A manifest-driven AI agent platform built with [Google ADK](https://google.github.io/adk-docs/) and Gemini. Drop a YAML file, get a working agent. Change the YAML, the agent changes. No code edits required.

Calculator and Palindrome agents are the learning vehicles — the real goal is an enterprise-grade platform where new agents are deployed by writing a manifest, not by touching Python.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [The Three Layers](#the-three-layers)
- [Running Modes](#running-modes)
  - [Local Mode — function tools, no servers needed](#local-mode)
  - [MCP Mode — enterprise, tools as HTTP servers](#mcp-mode)
- [Adding a New Agent](#adding-a-new-agent)
- [Manifest Reference](#manifest-reference)
- [Env Var Overrides](#env-var-overrides)
- [MCP Fallback Behaviour](#mcp-fallback-behaviour)
- [Available Agents](#available-agents)

---

## How It Works

```
.env  +  manifest.yaml
         ↓
      config.py          reads env vars → frozen dataclasses (settings singleton)
         ↓
  agent_from_manifest.py
    load_manifest()      reads YAML from disk
    validate_manifest()  structural check at startup — catches errors before first request
    merge_config()       env vars win over YAML, YAML wins over hardcoded defaults
    enforce_policy()     blocks denied problem types before Gemini ever sees the request
    build_agent()        constructs ADK Agent with resolved model + tools + instruction
         ↓
      Runner → Gemini → tool calls → response
```

Every value the agent uses — system prompt, model, tools, rate limits, policy — comes from the manifest. The Python code is the engine. The YAML is the config.

---

## Project Structure

```
calculator_agent_control_plane/
│
├── .env                                    # Your secrets — never committed
├── .env.example                            # Template — copy to .env
│
├── calculator_agent/
│   ├── __init__.py                         # Lazy root_agent export for ADK web
│   ├── agent.py                            # ADK web entry point — builds root_agent
│   ├── agent_from_manifest.py              # Full control plane pipeline (terminal + shared logic)
│   ├── config.py                           # Env-var layer — frozen dataclasses singleton
│   ├── tools.py                            # Calculator tool functions (add, subtract, multiply, divide, escalate)
│   ├── palindrome_tools.py                 # Palindrome tool functions
│   └── manifest/
│       ├── calculator_agent_manifest.yaml  # Calculator agent — local function tools
│       ├── palindrome_agent_manifest.yaml  # Palindrome agent — local function tools
│       ├── calculator_mcp_manifest.yaml    # Calculator agent — MCP server tools
│       └── palindrome_mcp_manifest.yaml    # Palindrome agent — MCP server tools
│
├── mcp_servers/
│   ├── __init__.py
│   ├── calculator_server.py                # FastMCP server wrapping tools.py (port 8001)
│   └── palindrome_server.py                # FastMCP server wrapping palindrome_tools.py (port 8002)
│
├── requirements.txt
└── README.md
```

---

## The Three Layers

Resolution order: **Env Var > YAML manifest > hardcoded default**

### Layer 1 — `.env` → `config.py`

Reads environment variables at startup and locks them into frozen dataclasses. Nothing re-reads `.env` after boot. The `settings` object is a singleton available everywhere.

```
AGENT_MODEL_NAME=gemini-2.5-flash  →  settings.agent.model_name
MANIFEST_PATH=...                  →  settings.manifest.manifest_path
CONFIDENCE_THRESHOLD=0.8           →  settings.policy.confidence_threshold
```

### Layer 2 — `manifest.yaml`

The manifest is the single source of truth for what an agent is and how it behaves. It defines the system prompt, model, tools, policy, rate limits, and lifecycle — all in one file.

### Layer 3 — `merge_config()`

Merges both layers into a single typed `MergedConfig` object. Env vars win. YAML fills the rest. This resolved config is what the agent is built from.

---

## Running Modes

### Local Mode

Tools run as Python functions inside the same process. No servers needed. Good for development.

**Prerequisites**

Copy `.env.example` to `.env` and add your API key:

```
GOOGLE_API_KEY=your_gemini_api_key_here
GOOGLE_GENAI_USE_VERTEXAI=FALSE
```

**ADK Web UI**

```bash
pip install -r requirements.txt
adk web . --port 8000 # or just adk web
```

Open `http://localhost:8000`, select `calculator_agent` from the dropdown.

To run the palindrome agent in the web UI:

```bash
MANIFEST_PATH=calculator_agent/manifest/palindrome_agent_manifest.yaml adk web . --port 8000
```

**Terminal REPL**

```bash
# Calculator agent
python -m calculator_agent.agent_from_manifest

# Palindrome agent
MANIFEST_PATH=calculator_agent/manifest/palindrome_agent_manifest.yaml \
  python -m calculator_agent.agent_from_manifest
```

---

### MCP Mode

Tools run as standalone HTTP servers using the [Model Context Protocol](https://modelcontextprotocol.io). The agent connects to them over HTTP at runtime. This is the enterprise path — tools are decoupled from the agent process.

**Step 1 — Start the MCP servers**

```bash
# Terminal 1
python -m mcp_servers.calculator_server
# → Starting Calculator MCP Server on port 8001 at /mcp ...

# Terminal 2
python -m mcp_servers.palindrome_server
# → Starting Palindrome MCP Server on port 8002 at /mcp ...
```

**Step 2 — Run the agent pointing at an MCP manifest**

```bash
# Terminal 3 — ADK web
MANIFEST_PATH=calculator_agent/manifest/calculator_mcp_manifest.yaml adk web . --port 8000

# or terminal REPL
MANIFEST_PATH=calculator_agent/manifest/calculator_mcp_manifest.yaml \
  python -m calculator_agent.agent_from_manifest
```

**How MCP tool loading works**

The manifest declares a URL instead of a function name:

```yaml
- tool_id: "calculator_mcp"
  type: "mcp_server"
  url: "http://localhost:8001/mcp"
  allowed_tool_ids: ["add", "subtract", "multiply", "divide"]
  on_unavailable: "warn"
  fallback_tool_id: "add"
```

## Adding a New Agent

No Python code needed. Three steps:

**1. Write a manifest**

```yaml
identity:
  agent_id: "my_agent_001"
  name: "my_agent"
  display_name: "My Agent"
  description: "Does something useful."

instruction: |
  You are a helpful agent that ...

model:
  base_model_id: "gemini-2.5-flash"

capabilities:
  tools:
    - tool_id: "some_mcp_server"
      type: "mcp_server"
      url: "http://localhost:9000/mcp"
      on_unavailable: "warn"
      allowed: true

policy:
  denied_problem_types:
    - "off_topic_requests"
  rate_limits:
    requests_per_minute: 30
    max_concurrent_sessions: 5
```

**2. Point `MANIFEST_PATH` at it**

```bash
MANIFEST_PATH=calculator_agent/manifest/my_agent_manifest.yaml \
  python -m calculator_agent.agent_from_manifest
```

**3. That's it**

The control plane reads the manifest, validates it, enforces policy, and builds the agent automatically.

> If your agent uses local Python tools (not MCP), add the function to `tools.py` and register it in `TOOL_REGISTRY` in `agent_from_manifest.py`. For MCP tools, no code changes are needed at all.

---

## Manifest Reference

| Section | Field | What it controls |
|---|---|---|
| `identity` | `name`, `display_name` | Agent identity shown in ADK web |
| `instruction` | _(string)_ | System prompt — agent persona and rules |
| `model` | `base_model_id` | Gemini model to use |
| `capabilities.tools` | `tool_id`, `type`, `url` | Which tools the agent can call |
| `capabilities.tools` | `allowed_tool_ids` | Whitelist of tools exposed by an MCP server |
| `capabilities.tools` | `on_unavailable` | `fail` = crash at startup / `warn` = skip with fallback |
| `capabilities.tools` | `fallback_tool_id` | Local function to use if MCP server is unreachable |
| `capabilities.tools` | `auth.type` + `auth.secret_ref` | MCP auth — credential read from env var |
| `policy` | `denied_problem_types` | Requests blocked before Gemini sees them |
| `policy` | `confidence_threshold` | When to trigger escalation |
| `policy.rate_limits` | `requests_per_minute` | RPM cap (stub — wire to counter service in prod) |
| `deployment.lifecycle` | `max_turns`, `session_timeout_seconds` | Session limits |

### Tool types

| `type` | Behaviour |
|---|---|
| `function` | Local Python function — looked up in `TOOL_REGISTRY` |
| `human_in_loop` | Local Python function — same as `function`, signals human review intent |
| `mcp_server` | Remote HTTP server — connected via `MCPToolset` at first tool call |

### MCP auth types

| `auth.type` | Header sent |
|---|---|
| `none` | No auth header |
| `api_key` | `X-API-Key: <value of secret_ref env var>` |
| `bearer` | `Authorization: Bearer <value of secret_ref env var>` |

Credentials are never stored in the manifest. `secret_ref` is just the name of the env var to read.

---

## Env Var Overrides

Any YAML value can be overridden at runtime without touching any files.

| Env Var | Overrides |
|---|---|
| `MANIFEST_PATH` | Path to the YAML manifest |
| `AGENT_MODEL_NAME` | `model.base_model_id` |
| `CONFIDENCE_THRESHOLD` | `policy.confidence_threshold` |
| `ALLOWED_PROBLEM_TYPES` | `policy.allowed_problem_types` (comma-separated) |
| `DENIED_PROBLEM_TYPES` | `policy.denied_problem_types` (comma-separated) |
| `RATE_LIMIT_RPM` | `policy.rate_limits.requests_per_minute` |
| `MAX_CONCURRENT_SESSIONS` | `policy.rate_limits.max_concurrent_sessions` |
| `MAX_TURNS` | `deployment.lifecycle.max_turns` |
| `SESSION_TIMEOUT` | `deployment.lifecycle.session_timeout_seconds` |
| `CALCULATOR_MCP_PORT` | Port for calculator MCP server (default: 8001) |
| `PALINDROME_MCP_PORT` | Port for palindrome MCP server (default: 8002) |

---

## MCP Fallback Behaviour

When an MCP server is unreachable at startup, `_load_tools()` follows this decision tree:

```
MCPToolset construction fails
        ↓
on_unavailable: "fail"   →  RuntimeError — agent does not start
on_unavailable: "warn"   →  check fallback_tool_id
                                 found in TOOL_REGISTRY  →  load local function
                                                             print [FALLBACK] message
                                 not found               →  skip tool entirely
                                                             print [WARN] message
```

Startup output when fallback triggers:

```
[WARN] MCP toolset 'calculator_mcp' failed to load: Connection refused
[FALLBACK] calculator_mcp unreachable → using local 'add' function
```

> Note: Fallback only applies at startup. If an MCP server goes down mid-session after the agent is already running, that is an infrastructure-level concern (health checks, retries) outside the scope of this control plane.

---

## Available Agents

| Manifest | Mode | Tools |
|---|---|---|
| `calculator_agent_manifest.yaml` | Local functions | add, subtract, multiply, divide, escalate |
| `palindrome_agent_manifest.yaml` | Local functions | is_palindrome, longest_palindrome_substring, make_palindrome, palindrome_score, escalate |
| `calculator_mcp_manifest.yaml` | MCP server (port 8001) | same calculator tools, served over HTTP |
| `palindrome_mcp_manifest.yaml` | MCP server (port 8002) | same palindrome tools, served over HTTP |

Switch between agents by changing `MANIFEST_PATH`. No restarts needed for the MCP servers.
