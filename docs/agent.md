# The policy agent

Ask a question about US energy policy in plain English and get an answer built from the model's own tools, with
every number traced to its module, variable and grade.

```
pip install anthropic                 # or: pip install -e ".[agent]"
export ANTHROPIC_API_KEY=...          # read from the environment, never stored or logged
python -m nems_open.agent "What does a $50 carbon price do to US energy CO2 in 2040?"
python -m nems_open.agent --questions       # the 10 sample questions and what each should do
python -m nems_open.agent --check-gate      # which of them the scope gate declines (no API call)
```

Without a key the command prints that nothing was sent and exits 3. A question the scope gate declines is answered
without a key and without an API call. `--model` or `NEMS_AGENT_MODEL` picks the model (default `claude-opus-5-5`,
adaptive thinking, effort `medium`). `--no-fallbacks` turns off the server-side refusal fallback the agent opts into
by default (a refused request is retried on a fallback model chosen by the API, in the same call).

## What is built, and what is not

The interface to the model is real today: five tools in `src/nems_open/agent/tools.py` that read the same data the
demo shows. The model call is thin: a manual tool-use loop in `loop.py` (about 130 lines). There is no web
interface, nothing is published, and no API call has been made with a real key as part of building this: the tests
use a scripted stand-in for the model, and one test drives the real SDK against a fake transport to check what
would be sent. **A key from Josh is needed before the first real answer.** `NEMS_AGENT_LIVE=1 pytest
tests/test_agent_live.py` then checks five questions against the real API.

## The tools

| Tool | What it does |
|---|---|
| `list_levers` | The three levers (carbon price 0 to 200 dollars a ton, plug-in share of new light-duty sales in 2035, building energy use in 2050 as a fraction of EIA's), the years (2025 to 2050), the region level (US total), the measures it can read, and what is not available. |
| `run_scenario` | Run the model with a set of levers (every sector on the fitted stand-ins). Settings on the demo's grid are read from `web/data/scenarios/` and are instant; others run live (4 to 8 seconds), at most 4 per question. Returns a scenario id. |
| `read_result` | One measure, one year, from a scenario: the value, EIA's reference, the difference and the percent difference. |
| `trace_number` | The modules behind a measure, each one's grade, the variable, and how far a no-policy run is from EIA's reference (`web/data/fidelity.json`). |
| `read_uncertainty` | 10th, 50th and 90th percentile of US CO2, household bill or home gas price at a carbon price of 0, 50 or 100, from the sampling in `docs/uncertainty.md`. |

Measures: US energy CO2, average electricity price, home gas price, gasoline price, diesel price, gasoline use,
electricity sales and energy use by sector (`knowledge.py`). Values equal the demo's, because the same function
makes them.

## The rules, in code (`rules.py`)

The prompt asks for these. The code makes them true.

1. **Every number cites module, variable and grade.** The agent ends by calling `submit_answer` with prose that holds
   placeholders (`{c1}`) and a list of claims (result id and field). The code puts the stored number in place of
   each placeholder, adds a source line with module, variable and grade, and **rejects any number written another
   way**. The only numbers allowed outside a claim are years and numbers the user or the agent's own run settings
   supplied. A rejected answer goes back to the model as a tool error naming what to fix (three tries), and an
   answer that never passes is not shown.
2. **A stand-in is declared.** If any claim has a grade below "matches EIA" (a fitted stand-in, or our own model),
   the code appends the statement that the numbers rest on stand-ins, names the modules, and says a policy effect is
   an estimate from fitted curves, not EIA's result. The model cannot leave it out or soften it.
3. **What the model cannot resolve is declined, not answered.** A scope gate declines, before any model call,
   questions that name a street, hill, zip code, county, town, a state or major city, an hour or day, a year before
   2025 or after 2050, or a topic outside energy and CO2. The model can also decline through `submit_answer`
   (for a lever that is not listed, for example). A decline gives the reason and what the model does resolve.

Grades come from `web/data/fidelity.json`: "matches EIA" (ported from EIA's code and checked against its Fortran),
"our own model" (not a port, measured against EIA) and "stand-in" (a fitted curve). Nothing about accuracy is
written by hand in the agent.

## What the answers are not

- National totals only. The model has census divisions inside, but this interface reads the US total.
- The runs use the fast stand-ins for every sector, so a policy effect is a fitted curve's estimate. With no policy
  the stand-ins reproduce EIA's reference by construction, so "0.00% gap" in the fidelity data is not evidence of
  accuracy for a policy.
- Commercial building-code and efficiency-standard levers exist in the model but need the slow ported commercial
  module; the agent does not run them and says so.
- A carbon price above 100 dollars a ton is extrapolation; the tool says so.

## The ten sample questions

`src/nems_open/agent/sample_questions.json` (and `python -m nems_open.agent --questions`):

| # | Question | Expected |
|---|---|---|
| 1 | What does a $50 carbon price do to US energy CO2 in 2040, compared with EIA's reference? | Answer. Runs the $50 grid scenario, reads CO2 for 2040, cites the emissions, demand and supply stand-ins, says they are stand-ins. |
| 2 | How much more would a household pay per MMBtu for gas in 2035 with a $100 carbon price? | Answer. Reads the home gas price against the reference; says it is a price, not a bill. |
| 3 | If 80% of new light-duty vehicles sold in 2035 are plug-ins, how much less gasoline do we use in 2040? | Answer. Scenario with ev_share_2035 0.8, reads gasoline use for 2040 against the reference. |
| 4 | Which module produces the electricity price, and how far can I trust it? | Answer. `trace_number`: module, variable `MPBLK/pelas`, grade. No scenario. |
| 5 | How uncertain is US energy CO2 in 2050 with no carbon price? | Answer. `read_uncertainty`: the three percentiles, labelled our sampling on stand-ins, not EIA's. |
| 6 | What levers can I change, and over what range? | Answer. `list_levers`; each limit is a claim; says what is not available. |
| 7 | What will electricity cost on my street in Pittsburgh in 2032? | Decline by the gate: a street and a city. |
| 8 | Would a wind farm on the hill behind my town be profitable if we put a $100 carbon price on? | Decline by the gate: a specific site. |
| 9 | What was US energy CO2 in 1975? | Decline by the gate: before 2025, history is EIA's data. |
| 10 | If we tax carbon, what happens to the S&P 500? | Decline by the gate: outside US energy and CO2. |

The gate's side of questions 7 to 10 and the pass-through of 1 to 6 are tested (`tests/test_agent.py`). The model's side
of 1 to 6 is checked with a scripted model offline and, with a key, by `tests/test_agent_live.py`.

## Tests

`tests/test_agent.py` (40 tests, offline): the gate on every sample question; each tool against the demo's own data
files; each rule (an unsourced number, a bad result id or field, an unused or undefined claim, a decline carrying a
number); the loop with a scripted model (a full conversation, a rejected answer repaired, a model decline, a gated
question that never reaches the model, an answer never submitted, a refusal); and one test through the real
`anthropic` client against a fake HTTP transport that checks the request body (model, adaptive thinking, effort,
fallbacks header, strict closed tool schemas, no forced `tool_choice`) and that SDK content blocks go back on the next
turn.
