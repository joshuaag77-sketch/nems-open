"""The policy agent: ask questions about US energy policy in plain English, answered from the model's own tools.

    python -m nems_open.agent "What does a $50 carbon price do to US energy CO2 in 2040?"

See docs/agent.md. Numbers come only from tool results and carry module, variable and grade (rules.py).
"""

from nems_open.agent.loop import DEFAULT_MODEL, AgentAnswer, PolicyAgent  # noqa: F401
