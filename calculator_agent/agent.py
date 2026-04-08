# calculator_agent/agent.py

from google.adk.agents import Agent
from .tools import add, subtract, multiply, divide, escalate
from .prompt import SYSTEM_PROMPT

root_agent = Agent(
    name="calculator_agent",
    model="gemini-2.5-pro",
    description="A calculator agent that solves math problems step by step.",
    instruction=SYSTEM_PROMPT,
    tools=[add, subtract, multiply, divide, escalate],
)