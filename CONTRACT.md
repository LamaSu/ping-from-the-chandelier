# The SIA agent contract

What `sia evals run` requires of `agent.py`. Verified against this repo at
`e697daa` — the PTO agent already satisfies all of it. Keep it that way.

## Wire format

SIA runs the agent as a subprocess, one process per eval case:

```
stdin    {"input": "Priya wants 2026-12-22 to 2026-12-31 off.", "case_id": "blackout-dec"}
stdout   {"output": "...", "tool_calls": [...], "tokens": 4213}
```

`cmd` in `.sia/config.toml` is what gets run (`python agent.py`). Anything the
agent writes to stdout that is not that one JSON object breaks the parse — keep
debug prints on stderr.

## The three things that are easy to get wrong

**1. `output` is all the judge sees.**
Not `tool_calls`, not the database, not the exit code. A PTO agent's real effect
is a state change — a request approved, a balance decremented — and the judge is
blind to it unless the agent *prints* it. That is what `with_ledger()` is for:

```python
def with_ledger(reply: str) -> str:
    summary = hr.ledger_summary()
    return (f"{reply}\n\n--- LEDGER AFTER THIS REQUEST ---\n"
            f"{json.dumps(summary, indent=2, sort_keys=True)}")
```

Every case in `evals/pto.yaml` is scored on that block. If a new tool changes
state, `ledger_summary()` has to surface it or no eval can test it.

**2. `tokens` is the cost axis.**
Summed across the whole tool loop, not just the final call — one case is every
call it took to answer. Drop it and SIA can only plot latency, which is a weaker
proxy for money. `call_model()` appends each response's `usage.total_tokens`;
`main()` sums them.

**3. Model access is the shared proxy, not a personal key.**
`.env` (gitignored, never uploaded to SIA):

```
LITELLM_PROXY_URL=https://litellm-...
LITELLM_PROXY_KEY=sk-...
AGENT_MODEL=azure_ai/claude-haiku-4-5
```

Nobody needs their own Anthropic key. `main()` checks both vars by name and
fails with a readable message rather than httpx's `Illegal header value
b'Bearer '`.

## Eval cases

`evals/pto.yaml`. Each case is `id` / `input` / `expected_behavior`, plus
optional `category` and `tags`. `expected_behavior` is prose read by an LLM
judge, so it should say what a correct run *does* — which end state is
acceptable, and what to ignore (wording, which of two ids was kept, an extra
confirming lookup).

**Controls matter as much as defects.** A patch that fixes the failing cases by
making the agent refuse everything also "passes" — the cases that pass *today*
are what catch that. Do not delete a passing case to make room.

## Checking it by hand

```bash
set -a; . .env; set +a
echo '{"input": "Priya wants the last week of December off."}' | python agent.py
```

Valid JSON on stdout with a populated `output` means SIA can run it.
