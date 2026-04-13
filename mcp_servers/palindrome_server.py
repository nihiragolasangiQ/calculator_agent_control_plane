"""
Palindrome MCP Server — exposes palindrome analysis tools via the MCP protocol.

Wraps calculator_agent/palindrome_tools.py. No logic is duplicated here.
escalate is intentionally excluded — it is a local side-effect function
and must not be remoted over MCP.

Run:
    python -m mcp_servers.palindrome_server

Listens on: http://0.0.0.0:8002/mcp  (streamable-http transport)

Concurrency: FastMCP / uvicorn handles concurrent HTTP connections via
async handlers. Each tool call is a stateless HTTP request — no shared
mutable state between calls.
"""

import os
import sys

# Allow running from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set port before FastMCP initializes — it reads settings at import time
from mcp.server.fastmcp import FastMCP
from calculator_agent.palindrome_tools import (
    is_palindrome as _is_palindrome,
    longest_palindrome_substring as _longest,
    make_palindrome as _make,
    palindrome_score as _score,
)

_PORT = int(os.getenv("PALINDROME_MCP_PORT", "8002"))
mcp = FastMCP("Palindrome MCP Server", port=_PORT)


@mcp.tool()
def is_palindrome(text: str) -> dict:
    """Checks if a word or sentence is a palindrome. Ignores case, spaces, and punctuation."""
    return _is_palindrome(text)


@mcp.tool()
def longest_palindrome_substring(text: str) -> dict:
    """Finds the longest palindromic substring within the given text."""
    return _longest(text)


@mcp.tool()
def make_palindrome(word: str) -> dict:
    """Appends the minimum number of characters to a word to make it a palindrome."""
    return _make(word)


@mcp.tool()
def palindrome_score(text: str) -> dict:
    """Scores how close text is to being a palindrome on a 0-100 scale."""
    return _score(text)


if __name__ == "__main__":
    port = mcp.settings.port
    print(f"Starting Palindrome MCP Server on port {port} at /mcp ...")
    mcp.run(transport="streamable-http")
