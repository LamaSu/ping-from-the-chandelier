# PTO approver agent

A tool-calling agent that reviews paid-time-off requests against employee
records (balance, tenure, team calendar, blackout dates) and posts a decision.
Structured like the SIA sample expense agent so `sia` can drive it as-is.

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cp .env.example .env            # fill in keys
    set -a; . .env; set +a
    echo '{"input": "Review PTO-330 for Grace."}' | .venv/bin/python agent.py

Files: `agent.py` (tool loop, stdin/stdout JSON), `hr.py` (in-memory HR
system), `policy.md` (the rules — what SIA patches), `prompts.py`,
`evals/pto.yaml`.
