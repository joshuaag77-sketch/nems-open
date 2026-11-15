# Hosting the site publicly

Status: ready to deploy, not deployed. Nothing below has been run against a live host or a real API key.

## Where it lives: nems.joshagarwal.com (recommended)

A subdomain, as its own Vercel project, with `joshagarwal.com/nems` forwarding to it.

Why not a subpath (`joshagarwal.com/nems` served in place through a Next.js rewrite): the personal site would proxy
every request to a second deployment, the Ask function would see the proxy's address instead of the visitor's (which
breaks the per-visitor limit), and the two projects' `/api` routes would collide. A subdomain keeps the two sites
apart: separate deploys, separate env vars and spend caps, and a Python function that never touches the Next.js
build. The domain is already on Vercel, so adding the subdomain is one click with no DNS records.

### Changes in the website repo

Branch `nems-open-showcase` (commit ca281ab), in a worktree of the local clone at `C:\Users\joshu\dev\jsite-nems`,
off `origin/main`. Not pushed. Three files:

| File | Change |
|---|---|
| `next.config.ts` | Temporary redirects: `/nems`, `/nems/*` and `/energy` go to nems.joshagarwal.com |
| `app/page.tsx` | One card after "What this is": "Build: NEMS Open, Your America in 2050", linking to the subdomain |
| `content/profile.md` | A "Builds" section so the homepage chat can answer questions about it |

`tsc --noEmit` and `eslint` pass on the branch (the one lint warning is an existing `<img>` further down the page).
Merging it before the subdomain is live would publish a dead link, so merge last.

## The deploy folder

```
python scripts/build_site.py            # dist/site: web/ + api/*.py + the agent's code + requirements.txt
```

`dist/site` holds the static pages, `api/ask.py` and `api/health.py`, `requirements.txt` with only `anthropic` and
`numpy`, and the policy agent under `src/nems_open/agent` with a two-line `paths.py`. The repo's `pyproject.toml`
(pandas, linopy, HiGHS), EIA's inputs and the oracles are not in it. No key is written anywhere. The root
`vercel.json` and `.vercelignore` are gone; `site/vercel.json` is the one config. Pass `--base-url` for a preview
at another address so link previews point at it.

## Go-live, in order (each step needs Josh's OK)

1. **Anthropic key with a hard cap.** In the Anthropic Console, make a workspace "nems-open-public", set its monthly
   spend limit to $20, and create a key there. This is the backstop behind every limit in code.
2. **Vercel project.** `cd dist/site && vercel link` (new project `nems-open`). In the project, add the Upstash Redis
   integration from the Marketplace (free tier; it sets `KV_REST_API_URL` and `KV_REST_API_TOKEN`), then env vars
   `ANTHROPIC_API_KEY` (sensitive) and `ASK_ENABLED=1`.
3. **Check Haiku is good enough.** No real API call has been made yet. Run
   `NEMS_AGENT_LIVE=1 NEMS_AGENT_MODEL=claude-haiku-5-5 python -m pytest tests/test_agent_live.py` (about 5 questions,
   under a cent). If it fails, set `ASK_MODEL=claude-sonnet-5-5` and read the cost table first.
4. **Preview.** `vercel deploy` (a preview, not production). Open it, check `/api/health` says `"ask": true`, ask
   three questions, and read the function logs: each answer logs one line with tokens and dollars, no question text.
5. **Production.** `vercel deploy --prod`, then add `nems.joshagarwal.com` under the project's Domains.
6. **Website.** Merge `nems-open-showcase` into the website's `main` (Vercel deploys it).

To switch questions off at any time: set `ASK_ENABLED=0` and redeploy. The pages keep working; the Ask page says
questions are switched off.

## Limits on the Ask box

All in `src/nems_open/agent/hosted.py`, each an env var with a default, so changing one is a setting:

| Setting | Default | What it stops |
|---|---|---|
| `ASK_ENABLED` | 0 (off) | Everything, until switched on |
| `ASK_MODEL` | claude-haiku-5-5 | The cheapest current model |
| `ASK_EFFORT` | low | Thinking depth per call |
| `ASK_MAX_TOKENS` | 4,000 | Output per model call |
| `ASK_MAX_OUTPUT` | 12,000 | Output summed over one question |
| `ASK_MAX_TURNS` | 8 | Model calls per question |
| `ASK_PER_IP_HOUR` / `ASK_PER_IP_DAY` | 5 / 15 | One visitor asking a lot |
| `ASK_PER_MINUTE` | 10 | Everyone together, a burst or a bot |
| `ASK_DAILY_USD` | 2.00 | The day's spend, checked before each question |

How the ceiling holds: before a question runs, its worst case under these limits (every turn at the output cap,
nothing cached: $0.043 on Haiku) is reserved against the day's total; after it runs, the reserve is replaced by the
real cost from the API's token counts. A question that would push the reserved total past the ceiling is refused
before any model call, so the day can end below the ceiling but not above it. The store fails closed: if Redis is
missing or unreachable, nothing is answered. Visitors are counted by a hash of their address; no address and no
question text is stored. Questions the scope gate declines (a single state, a single plant) are answered free and
count against nothing. `tests/test_hosted.py` covers each limit offline.

## Expected cost per 1,000 questions

Not yet measured: these are estimates from the agent's real prompt and tool sizes. The function logs real tokens and
dollars per question; replace this table after the first 20 to 50.

Inputs: system prompt and tool schemas about 2,400 tokens (measured from `loop.py` and `tools.py`). A typical
question takes 4 to 6 model calls (list levers, run one or two scenarios, read two or three results, trace, submit,
sometimes one repair). Each call resends the conversation so far, so input sums to about 20,000 to 35,000 tokens per
question; output, including thinking at low effort, about 2,000 to 4,000. Prices per million tokens (input/output):
Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10, Opus 5.5 $4/$20. Prompt caching is on; it is not counted below, so these
lean high.

| Model | Per question, typical | Per 1,000 questions | Worst case per question (the caps) |
|---|---|---|---|
| **Haiku 5.5 (default)** | $0.003 to $0.006 | **about $4 (range $3 to $6)** | $0.043 |
| Sonnet 5.5 | $0.06 to $0.11 | about $85 ($60 to $110) | $0.86 |
| Opus 5.5 | $0.12 to $0.22 | about $170 ($120 to $220) | $1.73 |

At the defaults, $2 a day buys about 450 Haiku questions; the $20 monthly workspace limit binds before the daily
ceiling would in a heavy month. Vercel (Hobby) and the Upstash free tier cover the hosting at this traffic: each
question is a few seconds of one function and three calls to the store.
