# Self-improving agents: a PTO approver that fixes itself

*Built at the **AWS × SIA hackathon**.*

**An AI agent finds another agent's bugs and writes the patch. No human writes the fix.**

The agent under test approves time-off requests. It reads employee records —
balance, tenure, team calendar, blackout dates, project urgency — and decides.
The interesting part isn't the HR domain; it's the loop wrapped around it.

![The agent deciding real requests](docs/demo.gif)

*One full cycle, captured live: an extension it refuses, a maternity request it
escalates, and the same blackout request decided twice — before and after the
patch.*

---

## What SIA did to the agent

**SIA's one patch took it from 81% → 95%. Three failures fixed. Zero regressions.**

| Run | Score | What changed | By |
|---|---|---|---|
| 1 | 53% | first scored run | — |
| 2 | 81% | 4 fixes | by hand |
| 3 | **95%** | **rewrote the broken rule** | **SIA** |
| 4 | 95% | caught a wrong claim in the agent's wording | **SIA** |
| 5 | **100%** | last remaining case | by hand |

SIA found the failure modes itself, wrote the diffs, and cost **$1.62** across
four scored runs. It read the agent's source and its results — nobody told it
which rule was wrong.

*Best run 21/21; an immediate re-run scored 19/21. Call it 19–21 out of 21 — not a solved agent.*

![SIA Foundry scoring the agent](docs/sia-overview.png)

*SIA Foundry's own scoreboard: 90/100, +15 on the previous run, 21 cases.*

## The good part: what SIA *didn't* do

Four tests failed, all tracing to one rule — a "requests under 2 days are
auto-approved, skip every check" shortcut.

The lazy fix is obvious: **delete the shortcut.** That clears all four failures
instantly. It also breaks four *other* tests that exist to catch exactly that
move — the ones proving the agent still approves ordinary requests quickly.

SIA didn't take it. It kept the shortcut fast and carved out only the three
checks that make it safe. **Three failures fixed, zero regressions.**

Same request, before and after its patch:

```
BEFORE   lookup_request → approve_request        ← never checked the calendar
         "PTO-320 approved."                       wrong: it's inside a blackout

AFTER    lookup_request → lookup_employee → check_coverage → escalate_request
         "Escalated to Grace's manager, Priya, because the request overlaps
          the Product launch week blackout period (Policy §4.4)."
```

## Two bugs that weren't the agent's fault

Worth knowing, because both looked like agent failures and weren't:

- **A test failed because the *judge* misread the data.** A field showed an
  unchanged balance; the judge read it as a deduction. Fixed by stating the
  deduction outright instead of leaving it to be inferred.
- **A test demanded a capability that didn't exist.** No tool could amend a
  request's dates, so the agent could only ever decide the wrong one. Fixed by
  building the tool.

And one I caused myself: adding a convenience field to one tool removed the
agent's reason to call another — so it silently stopped checking probation.
Convenience in one place can quietly delete a check somewhere else.

## Try it

```bash
git clone https://github.com/msoliman6/ping-from-the-chandelier.git
cd ping-from-the-chandelier
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add the two model-proxy values

set -a; . .env; set +a
echo '{"input": "Review PTO-330 for Grace."}' | .venv/bin/python agent.py
```

No credentials handy? This checks all 21 tests are satisfiable without a model:

```bash
.venv/bin/python tests/test_policy_oracle.py
```

## What's inside

| | |
|---|---|
| `agent.py` | the tool loop — 11 tools, stdin/stdout JSON |
| `hr.py` | simulated HR system: 20 employees, 8 teams, 24 requests |
| `policy.md` | the rules in plain English — **this is what SIA edits** |
| `evals/pto.yaml` | 21 tests: 9 planted defects, 12 regression guards |
| `harness/run_evals.py` | runs each test in its own process, scores with an LLM judge |

📄 **[Full details](docs/DETAILS.md)** — setup, the HR system, all 21 tests,
reasoning traces, and SIA's own reports.

📄 **Paper:** [SIA: Self Improving AI with Harness & Weight Updates](https://arxiv.org/abs/2605.27276)
(Hebbar et al., 2026) · framework at [hexo-ai/sia](https://github.com/hexo-ai/sia)

<sub>Built with Claude Code. The loop, the failures, and the numbers above are all real runs — nothing staged.</sub>
