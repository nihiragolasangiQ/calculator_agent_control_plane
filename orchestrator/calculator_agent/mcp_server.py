"""
Calculator MCP Server — exposes arithmetic tools via the MCP protocol.

Wraps orchestrator/calculator_agent/tools.py. No logic is duplicated here.
escalate is intentionally excluded — it is a local side-effect function
and must not be remoted over MCP.

Run:
    python -m orchestrator.calculator_agent.mcp_server

Listens on: http://0.0.0.0:8001/mcp  (streamable-http transport)
"""

import os
import sys

# Allow running from the project root (3 levels up from this file)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server.fastmcp import FastMCP
from orchestrator.calculator_agent.tools import (
    add as _add,
    subtract as _subtract,
    multiply as _multiply,
    divide as _divide,
)

_PORT = int(os.getenv("CALCULATOR_MCP_PORT", "8001"))
mcp = FastMCP("Calculator MCP Server", port=_PORT)


@mcp.tool()
def add(a: float, b: float) -> dict:
    """Adds two numbers together."""
    return _add(a, b)


@mcp.tool()
def subtract(a: float, b: float) -> dict:
    """Subtracts b from a."""
    return _subtract(a, b)


@mcp.tool()
def multiply(a: float, b: float) -> dict:
    """Multiplies two numbers together."""
    return _multiply(a, b)


@mcp.tool()
def divide(a: float, b: float) -> dict:
    """Divides a by b. Returns error dict if b is zero."""
    return _divide(a, b)


if __name__ == "__main__":
    port = mcp.settings.port
    print(f"Starting Calculator MCP Server on port {port} at /mcp ...")
    mcp.run(transport="streamable-http")
