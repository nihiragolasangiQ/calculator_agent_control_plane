# calculator_agent/agent_from_manifest.py

import yaml
from pathlib import Path

from calculator_agent.tools import add, subtract, multiply, divide, escalate
from google.adk.agents import Agent
from calculator_agent.prompt import SYSTEM_PROMPT

import asyncio
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part


import os
from dotenv import load_dotenv

# load .env file
load_dotenv("calculator_agent/.env")

# -----------------------------------------------------------------------------
# MANIFEST LOADER
# Reads the yaml and gives us a clean dict to work with
# -----------------------------------------------------------------------------
def load_manifest(manifest_path: str) -> dict:
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found at: {manifest_path}")
    
    with open(path, "r") as f:
        manifest = yaml.safe_load(f)
    
    print(f" Manifest loaded: {manifest['identity']['display_name']} v{manifest['identity']['version']}")
    return manifest


# -----------------------------------------------------------------------------
# TOOL LOADER
# Reads allowed tools from manifest — no hardcoding
# -----------------------------------------------------------------------------

TOOL_REGISTRY = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
    "escalate": escalate,
}

def load_tools_from_manifest(manifest: dict) -> list:
    allowed_tools = []
    
    for tool in manifest["capabilities"]["tools"]:
        if tool["allowed"]:
            tool_id = tool["tool_id"]
            if tool_id in TOOL_REGISTRY:
                allowed_tools.append(TOOL_REGISTRY[tool_id])
                print(f"   Tool loaded : {tool_id}")
            else:
                print(f"   Tool not found in registry: {tool_id}")
        else:
            print(f"   Tool disabled : {tool['tool_id']}")
    
    return allowed_tools

# -----------------------------------------------------------------------------
# POLICY ENFORCER
# Reads rules from manifest and validates every request
# Control plane responsibility — agent code knows nothing about this
# -----------------------------------------------------------------------------
def enforce_policy(problem: str, manifest: dict) -> dict:
    policy = manifest["policy"]
    
    # check denied problem types
    denied_types = policy["denied_problem_types"]
    for denied in denied_types:
        if denied.lower() in problem.lower():
            return {
                "allowed": False,
                "reason": f"Problem type '{denied}' is not allowed per policy."
            }
    
    # check rate limits (stub for now)
    # in production → control plane checks this against a counter
    rpm = policy["rate_limits"]["requests_per_minute"]
    print(f"   Rate limit    : {rpm} rpm (not enforced locally)")

    return {"allowed": True, "reason": None}

# -----------------------------------------------------------------------------
# FINAL AGENT BUILDER
# Wires manifest loader + tool loader + policy enforcer together
# -----------------------------------------------------------------------------


def build_agent_from_manifest(manifest: dict) -> Agent:
    print("\n Building agent from manifest...")

    tools = load_tools_from_manifest(manifest)

    agent = Agent(
        name=manifest["identity"]["name"],
        model=manifest["model"]["base_model_id"],
        description=manifest["identity"]["description"],
        instruction=SYSTEM_PROMPT,
        tools=tools,
    )

    print(f" Agent built : {manifest['identity']['display_name']}")
    print(f"  Model : {manifest['model']['base_model_id']}")
    print(f"  Tools : {len(tools)} tools loaded")
    return agent

# def run_from_manifest(problem: str, manifest: dict):
#     print(f"\n Problem: {problem}")
    
#     # step 1 — policy check first
#     policy_result = enforce_policy(problem, manifest)
#     if not policy_result["allowed"]:
#         print(f"Blocked by policy: {policy_result['reason']}")
#         return

#     # step 2 — build agent from manifest
#     agent = build_agent_from_manifest(manifest)
    
#     print(f"\n Policy passed — handing to agent...")


async def run_from_manifest(problem: str, manifest: dict):
    print(f"\n Problem: {problem}")
    
    # step 1 — policy check
    policy_result = enforce_policy(problem, manifest)
    if not policy_result["allowed"]:
        print(f" Blocked by policy: {policy_result['reason']}")
        return

    # step 2 — build agent
    agent = build_agent_from_manifest(manifest)

    # step 3 — run the agent
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=manifest["identity"]["name"],
        user_id="user_001",
    )

    runner = Runner(
        agent=agent,
        app_name=manifest["identity"]["name"],
        session_service=session_service,
    )

    message = Content(role="user", parts=[Part(text=problem)])

    print(f"\n Agent response:")
    async for event in runner.run_async(
        user_id="user_001",
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response():
            print(event.content.parts[0].text)
# -----------------------------------------------------------------------------
# QUICK TEST — just to make sure loader works
# -----------------------------------------------------------------------------
if __name__ == "__main__":
 
    manifest = load_manifest("calculator_agent/manifest/calculator_agent_manifest.yaml")
    asyncio.run(run_from_manifest("what is 12 * 15?", manifest))
    asyncio.run(run_from_manifest("solve this calculus problem: d/dx x^2", manifest))