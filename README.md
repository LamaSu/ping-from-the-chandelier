# PTO approver agent

A tool-calling agent that reviews paid-time-off requests against a simulated HR
system — balances, tenure, team calendar, blackout dates, project urgency — and
posts a decision. Structured to the SIA command-adapter contract (see
[CONTRACT.md](CONTRACT.md)) so `sia` can drive it as-is.

---

## Running it locally

### 1. Prerequisites

Python 3.12 or newer, and the `sia` CLI if you want to run the eval suite:

```bash
pip install sia-foundry
```

### 2. Clone and install

```bash
git clone https://github.com/LamaSu/ping-from-the-chandelier.git
cd ping-from-the-chandelier

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Use the venv's interpreter (`.venv/bin/python`) for everything below —
`.sia/config.toml` points SIA at it too.

### 3. Configure `.env`

Copy the template and fill in the two values from the team sheet:

```bash
cp .env.example .env
chmod 600 .env
```

```
LITELLM_PROXY_URL=https://...     # from the sheet
LITELLM_PROXY_KEY=sk-...          # from the sheet
AGENT_MODEL=azure_ai/claude-haiku-4-5
```

Nobody needs a personal Anthropic key — model access is the shared LiteLLM
proxy. `.env` is gitignored; **never commit it**.

`SIA_TOKEN` is optional. It is an alternative to `sia login`, which stores a
token in `~/.sia/credentials.json`. If you have logged in, leave it empty.

### 4. Run one request by hand

The agent reads one JSON object on stdin and writes one on stdout. Load `.env`
into the shell first — **from the repo root**:

```bash
set -a; . .env; set +a

echo '{"input": "Review PTO-330 for Grace."}' | .venv/bin/python agent.py
```

Expected: a single JSON object with a populated `output` ending in an
`HR SYSTEM AFTER THIS REQUEST` block. Some inputs worth trying:

| Input | What it exercises |
|---|---|
| `Review PTO-330 for Grace.` | the clean path — approve, balance 12 → 7 |
| `Review PTO-350 for Lin.` | probation — deny |
| `Fatima asked to extend her time off — PTO-381.` | extension while already on leave |
| `Yuki filed PTO-400 for maternity leave.` | statutory leave, never deducted |
| `Please review PTO-410 for Kwame.` | critical project — escalate |
| `Please approve PTO-999.` | unknown id — no decision at all |

Each process starts from a pristine copy of the seed data, so runs never
contaminate each other.

### 5. Run the eval suite

```bash
sia login --foundry https://sia.hexo.ai --device
sia status                   # what exists and what to do next
sia evals run
```

`.sia/config.toml` sets `questions_file = "evals/pto.yaml"`, so SIA reads the
handwritten suite in this repo rather than synthesizing its own. Add cases
there — and read the "Controls matter as much as defects" note in
[CONTRACT.md](CONTRACT.md) before deleting any.

---

## Troubleshooting

**`.: no such file or directory: .env`**
You are not in the repo root. `cd` there and re-run `set -a; . .env; set +a`.

**`{"error": "LITELLM_PROXY_URL and LITELLM_PROXY_KEY are not set ..."}`**
The vars did not reach the process. Check `echo $LITELLM_PROXY_URL` prints
something, and that `.env` has real values rather than the `<placeholder>`
text from `.env.example`.

**`ModuleNotFoundError: No module named 'httpx'`**
You are running system Python instead of the venv. Use `.venv/bin/python`, or
re-run `.venv/bin/pip install -r requirements.txt`.

**SIA runs the wrong agent / evals mention `E-201`**
`.sia/versions/baseline/` is a *snapshot* SIA takes at `sia init`, not your
working tree. If it drifts, copy the current source over it.

**Never run `sia` with `-y` / `--full`.** That disables the tool-call gate, and
a generate run once overwrote `.env` with `.env.example` that way. The deny
rules in `.sia/settings.json` now block writes to `.env`, but the gate is the
real protection.

---

## Layout

| File | What it is |
|---|---|
| `agent.py` | the tool loop; stdin/stdout JSON, token accounting |
| `hr.py` | the HR system — 20 employees, 24 requests, balances, calendar |
| `policy.md` | the rules, in plain English. **This is what SIA patches** |
| `prompts.py` | thin wrapper that mounts `policy.md` as the system prompt |
| `evals/pto.yaml` | the eval suite — 21 cases |
| `CONTRACT.md` | what `sia evals run` requires of `agent.py` |

## The HR system

20 employees across 8 teams (Engineering, Design, Sales, Support, Data,
Platform, Marketing, Ops), reporting to 4 managers. Each record carries a team,
manager, start date, PTO balance, and a `project_urgency` of `normal` or
`critical`. Tenure and probation are computed against a fixed `TODAY` of
2026-08-25 so runs stay deterministic.

Leave types: `vacation`, `personal` (both deducted), `sick` and `maternity`
(neither deducted). Two employees are on approved leave *right now* and have
pending extension requests — one affordable, one not.
