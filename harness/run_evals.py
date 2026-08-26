"""Bring-your-own eval harness for SIA.

Wired in via `.sia/config.toml`:

    [engine]
    questions_file = "evals/pto.yaml"
    eval_command   = "python harness/run_evals.py"

SIA runs this with cwd = repo root and reads `eval_results.jsonl` back —
one JSON object per line. It invokes the agent itself and scores itself;
SIA does not adapt or judge the output.

Each case gets its own agent process, which is what keeps the HR state in
`hr.py` clean between cases — the module-level RECORDS/REQUESTS are
per-process, so a case that approves leave cannot leak a mutated balance
into the next one.
"""
import concurrent.futures as futures
import json
import os
import pathlib
import subprocess
import sys

# `eval_command` in .sia/config.toml is a plain `python harness/run_evals.py`
# so it stays cross-platform, but the interpreter that resolves to may not be
# the one with this repo's dependencies installed. Re-exec under the project
# venv if that is the case. The guard variable stops it looping.
def _reexec_under_venv() -> None:
    if os.environ.get("_PTO_HARNESS_REEXEC"):
        return                                  # already tried; fall through
    root = pathlib.Path(__file__).resolve().parent.parent
    for candidate in (root / ".venv" / "bin" / "python",
                      root / ".venv" / "Scripts" / "python.exe"):
        if candidate.exists() and candidate.resolve() != pathlib.Path(sys.executable).resolve():
            env = dict(os.environ, _PTO_HARNESS_REEXEC="1")
            os.execve(str(candidate), [str(candidate), *sys.argv], env)


try:
    import httpx
    import yaml
except ModuleNotFoundError:
    _reexec_under_venv()
    try:
        import httpx
        import yaml
    except ModuleNotFoundError as exc:      # pragma: no cover - setup error
        sys.stderr.write(
            f"harness: missing dependency {exc.name!r}. Install them with:\n"
            f"  .venv/bin/pip install -r requirements.txt\n"
            f"(running under {sys.executable})\n")
        raise SystemExit(1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "evals" / "pto.yaml"
OUT = ROOT / "eval_results.jsonl"

PROXY_URL = os.environ.get("LITELLM_PROXY_URL", "").strip().rstrip("/")
PROXY_KEY = os.environ.get("LITELLM_PROXY_KEY", "").strip()
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "azure_ai/claude-haiku-4-5")
PYTHON = os.environ.get("AGENT_PYTHON") or sys.executable

JUDGE = """You are grading one run of an HR leave-approval agent.

You are shown what the agent replied, including a machine-readable
"HR SYSTEM AFTER THIS REQUEST" block giving the end state. Grade the END
STATE and the reasoning against the expected behavior. Ignore wording,
tone, formatting, and any extra confirming lookups.

EXPECTED BEHAVIOR:
{expected}

AGENT OUTPUT:
{output}

Reply with a single JSON object and nothing else:
{{"correct": true or false, "reason": "<one sentence>"}}"""


def run_agent(case: dict) -> dict:
    """One case, one fresh agent process."""
    payload = json.dumps({"input": case["input"], "case_id": case["id"]})
    try:
        proc = subprocess.run(
            [PYTHON, "agent.py"], input=payload, capture_output=True,
            text=True, cwd=ROOT, timeout=240)
    except subprocess.TimeoutExpired:
        return {"output": "", "tokens": None, "error": "agent timed out"}
    try:
        body = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"output": "", "tokens": None,
                "error": f"agent stdout was not JSON: {proc.stdout[-300:]}"}
    return {"output": body.get("output") or "", "tokens": body.get("tokens"),
            "tool_calls": body.get("tool_calls") or [], "error": body.get("error")}


def judge(case: dict, output: str) -> tuple[bool, str]:
    if not output.strip():
        return False, "agent produced no output"
    response = httpx.post(
        f"{PROXY_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {PROXY_KEY}"},
        json={"model": JUDGE_MODEL, "max_tokens": 300, "messages": [
            {"role": "user", "content": JUDGE.format(
                expected=case["expected_behavior"], output=output)}]},
        timeout=120)
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"].strip()
    # The judge is asked for bare JSON; a fenced block is the common slip.
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return False, f"judge returned unparseable verdict: {text[:160]}"
    return bool(verdict.get("correct")), str(verdict.get("reason") or "")


LEDGER_MARKERS = ("--- HR SYSTEM AFTER THIS REQUEST ---",
                  "--- LEDGER AFTER THIS REQUEST ---")


def extract_ledger(output: str):
    """The end-state block the agent appends. SIA reads this to see what the
    run actually changed, so it has to come back as structured data rather
    than staying buried in the reply text."""
    for marker in LEDGER_MARKERS:
        if marker in output:
            tail = output.split(marker, 1)[1].strip()
            try:
                return json.loads(tail[tail.index("{"):tail.rindex("}") + 1])
            except (ValueError, json.JSONDecodeError):
                return None
    return None


def score(case: dict) -> dict:
    run = run_agent(case)
    if run.get("error") and not run["output"]:
        correct, reason = False, run["error"]
    else:
        correct, reason = judge(case, run["output"])
    tags = case.get("tags") or []
    # `output`, `tool_calls` and `ledger` are what SIA reads back to analyse a
    # run. Without them it reports "no results" even though every case scored.
    return {"question_id": case["id"], "case_id": case["id"],
            "correct": correct, "score": 100.0 if correct else 0.0,
            "category": case.get("category", ""), "tags": tags,
            "kind": "defect" if "defect" in tags else "control",
            "tokens": run.get("tokens"), "reason": reason,
            "output": run.get("output") or "",
            "tool_calls": run.get("tool_calls") or [],
            "ledger": extract_ledger(run.get("output") or "")}


def main() -> int:
    missing = [n for n, v in (("LITELLM_PROXY_URL", PROXY_URL),
                              ("LITELLM_PROXY_KEY", PROXY_KEY)) if not v]
    if missing:
        print(f"{' and '.join(missing)} not set", file=sys.stderr)
        return 1
    cases = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["cases"]
    with futures.ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(score, cases))
    rows.sort(key=lambda r: r["question_id"])
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows),
                   encoding="utf-8")

    passed = sum(1 for r in rows if r["correct"])
    for kind in ("defect", "control"):
        group = [r for r in rows if r["kind"] == kind]
        ok = sum(1 for r in group if r["correct"])
        print(f"{kind:8} {ok}/{len(group)}", file=sys.stderr)
    print(f"TOTAL    {passed}/{len(rows)}  ->  {OUT.name}", file=sys.stderr)
    for r in rows:
        if not r["correct"]:
            print(f"  FAIL {r['question_id']}: {r['reason'][:110]}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
