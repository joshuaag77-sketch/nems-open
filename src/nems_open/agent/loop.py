"""The policy agent: a Claude tool-use loop over the model's tools, with the rules applied to its answer in code.

    from nems_open.agent import PolicyAgent
    answer = PolicyAgent().ask("What does a $50 carbon price do to US energy CO2 in 2040?")
    print(answer.text)

The client is injected, so tests run offline with a stub. With none given, the real SDK client is built from the
environment (ANTHROPIC_API_KEY); a key is never stored or logged.

The loop is manual (not the SDK's tool runner) because the answer has to pass through rules.check before it is
accepted: a rejected submit_answer goes back to the model as a tool error naming what to fix.
"""

import json
import os
from dataclasses import dataclass, field

from nems_open.agent import rules
from nems_open.agent.tools import SCHEMAS, Toolbox

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TURNS = 14
MAX_REPAIRS = 3

SYSTEM = """You answer questions about US energy policy using NEMS Open, an open rebuild of EIA's National Energy Modeling System, through the tools you are given. You are not the source of any number: the tools are.

Rules, which the program enforces whether or not you follow them:
- State a number only through submit_answer: write {c1}, {c2}... in the text and list each as a claim giving the result id (r1, r2...) and the field. The program prints the number with its unit and adds its module, variable and grade as a source. So write {c1}, never "{c1} million tons" or "{c1}%": no unit and no percent sign after a placeholder. Do not type any other number, except years and numbers the user gave you or you set in run_scenario.
- The difference fields print as sizes without a sign. Say "lower" or "higher" yourself, using the result's direction. Never write "-7% lower".
- Comparisons need two numbers from read_result (value and reference), or use its difference fields.
- Anything you say that the tools did not give you (background, how a policy is designed, what a term means, what other studies find) goes in not_from_model, one sentence each, with no numbers, or is left out. Do not put it in the answer. Prefer leaving it out.
- Most of this model is fitted stand-ins, not EIA's own modules, and the program says so under your answer. Say in your own words what a number does and does not mean; do not call a policy effect EIA's result.
- You can set eight levers: carbon price, EV sales, data center and other new load, early coal closures, wind and solar cost, gas supply, oil price and nuclear output. Building codes and appliance standards are not available. If the question needs something the model cannot resolve (a place below the national level, a site, hours, a year outside 2025 to 2050, a lever that is not listed, a topic outside US energy and CO2), set can_answer to false, say why, and put the closest question about the US as a whole in suggestion. Do not approximate it from national numbers. Do not name internal lever or field names in your text; use plain words.
- Policy starts in 2027, so a result for an earlier year is EIA's reference.
- Write plain sentences: no markdown, no bullets, no bold. Keep answers short.
- Finish by calling submit_answer exactly once."""


@dataclass
class AgentAnswer:
    text: str
    declined: bool = False
    stand_in: bool = False
    claims: list = field(default_factory=list)
    gated: bool = False                 # declined by the scope gate, with no model call
    tool_calls: list = field(default_factory=list)
    turns: int = 0
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0                  # billed at a tenth of the input price
    cache_write_tokens: int = 0                 # billed at 1.25x the input price
    error: str = ""
    runs: list = field(default_factory=list)    # lever settings of every scenario the question ran, in order
    body: str = ""                              # the prose with numbers filled in (text adds sources and basis)
    basis: str = ""
    outside: list = field(default_factory=list)  # sentences that are not from the model
    sources: list = field(default_factory=list)  # one per fact: markers, line, grade


def make_client():
    """The real SDK client, from the environment. Raises RuntimeError when there is no key."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("no ANTHROPIC_API_KEY in the environment")
    import anthropic            # imported here so offline tests and the gate need no SDK
    return anthropic.Anthropic()


class PolicyAgent:
    def __init__(self, client=None, model: str | None = None, fallbacks: bool = True,
                 max_turns: int = MAX_TURNS, effort: str = "medium", max_tokens: int = 16000,
                 output_budget: int | None = None, cache: bool = False):
        """max_tokens caps each model call; output_budget caps output tokens summed over the whole question (checked
        between turns, so one call can overshoot it by at most max_tokens). cache turns on automatic prompt caching:
        each turn resends the conversation so far, and cached input costs a tenth."""
        self._client = client
        self.model = model or os.environ.get("NEMS_AGENT_MODEL") or DEFAULT_MODEL
        self.fallbacks = fallbacks
        self.max_turns = max_turns
        self.effort = effort
        self.max_tokens = max_tokens
        self.output_budget = output_budget
        self.cache = cache

    @property
    def client(self):
        if self._client is None:
            self._client = make_client()
        return self._client

    def _create(self, messages):
        kw = dict(model=self.model, max_tokens=self.max_tokens, system=SYSTEM, tools=SCHEMAS + [rules.SUBMIT], messages=messages,
                  thinking={"type": "adaptive"})
        # output_config and fallbacks go through extra_body so older SDK releases accept them
        extra = {"output_config": {"effort": self.effort}}
        if self.cache:
            extra["cache_control"] = {"type": "ephemeral"}
        headers = {}
        if self.fallbacks:             # a refusal is retried on a fallback model chosen by the API, same call
            extra["fallbacks"] = "default"
            headers["anthropic-beta"] = FALLBACK_BETA
        return self.client.messages.create(**kw, extra_body=extra, **({"extra_headers": headers} if headers else {}))

    def ask(self, question: str) -> AgentAnswer:
        declined = rules.gate(question)
        if declined:
            text = rules.decline_text(declined.reason, declined.suggestion)
            return AgentAnswer(text=text, body=text, declined=True, gated=True)

        box = Toolbox()
        messages = [{"role": "user", "content": question}]
        out = AgentAnswer(text="", model=self.model)
        repairs = nudges = 0
        for turn in range(1, self.max_turns + 1):
            out.turns = turn
            resp = self._create(messages)
            out.input_tokens += getattr(resp.usage, "input_tokens", 0) or 0
            out.output_tokens += getattr(resp.usage, "output_tokens", 0) or 0
            out.cache_read_tokens += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
            out.cache_write_tokens += getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
            if resp.stop_reason == "refusal":
                out.text, out.declined = ("The model provider's safety system declined this request, so there is no "
                                          "answer to give."), True
                return out
            if resp.stop_reason == "max_tokens":
                out.error = "the response hit max_tokens"
                out.text = "The answer was cut off before it finished; nothing was produced."
                return out
            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue
            messages.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                if nudges >= 1:
                    out.error = "no submit_answer"
                    out.text = "The model ended without a checked answer, so none is given."
                    return out
                nudges += 1
                messages.append({"role": "user", "content": "Finish by calling submit_answer."})
                continue

            results, done = [], None
            for call in calls:
                if call.name == "submit_answer":
                    rendered, problems = rules.check(call.input, box, question)
                    if rendered is not None:
                        done = rendered
                        results.append({"type": "tool_result", "tool_use_id": call.id, "content": "accepted"})
                    else:
                        repairs += 1
                        results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                                        "content": "Rejected. Fix and call submit_answer again: " + "; ".join(problems)})
                    continue
                result, is_error = box.call(call.name, dict(call.input))
                out.tool_calls.append({"tool": call.name, "input": dict(call.input), "error": is_error})
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(result),
                                **({"is_error": True} if is_error else {})})
            if done is not None:
                out.text, out.declined, out.stand_in, out.claims = done.text, done.declined, done.stand_in, done.claims
                out.runs = list(box.runs)
                out.body, out.basis, out.outside, out.sources = done.body or done.text, done.basis, done.outside, done.sources
                return out
            if repairs > MAX_REPAIRS:
                out.error = "answer rejected too many times"
                out.text = "The model could not produce an answer that passes the citation rules, so none is given."
                return out
            if self.output_budget and out.output_tokens >= self.output_budget:
                out.error = "output budget spent"
                out.text = "This question needed more work than one answer is allowed here, so none is given. Try a narrower question."
                return out
            messages.append({"role": "user", "content": results})
        out.error = "too many turns"
        out.text = "The model used all its turns without an answer."
        return out
