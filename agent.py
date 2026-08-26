"""Acme PTO Assistant — a tool-calling agent that approves time off.

Speaks the `sia` command-adapter contract: a JSON object on stdin, a JSON
object on stdout.

    echo '{"input": "Ada filed PTO-301 and PTO-302, please review both."}' \
        | python3 agent.py

Configure the model through the same proxy the Foundry API uses:

    export LITELLM_PROXY_URL=https://your-proxy
    export LITELLM_PROXY_KEY=sk-...
    export AGENT_MODEL=azure_ai/claude-haiku-4-5
"""
import json
import os
import sys

import httpx

import hr
from prompts import SYSTEM

MODEL = os.environ.get("AGENT_MODEL", "azure_ai/claude-haiku-4-5")
PROXY_URL = os.environ.get("LITELLM_PROXY_URL", "").strip().rstrip("/")
# Stripped: a stray newline from `.env` would otherwise become part of the
# Authorization header, which httpx refuses to send.
PROXY_KEY = os.environ.get("LITELLM_PROXY_KEY", "").strip()
MAX_ROUNDS = 8
TIMEOUT_S = 120


def _fn(name: str, description: str, properties: dict,
        required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required}}}


TOOLS = [
    _fn("lookup_request",
        "Look up one PTO request by its id, e.g. PTO-301. Includes the "
        "working-day count and how many days of notice were given.",
        {"request_id": {"type": "string"}}, ["request_id"]),
    _fn("lookup_employee",
        "An employee's record: team, manager, start date, tenure, PTO "
        "balance and whether they are on probation.",
        {"employee_email": {"type": "string"}}, ["employee_email"]),
    _fn("list_requests",
        "List an employee's PTO requests, optionally filtered by status.",
        {"employee_email": {"type": "string"},
         "status": {"type": "string",
                    "description": "submitted, approved, denied, "
                                   "needs_changes or escalated"}},
        ["employee_email"]),
    _fn("check_coverage",
        "Teammates already off (approved or pending) on the same days as a "
        "request, and any blackout periods it touches.",
        {"request_id": {"type": "string"}}, ["request_id"]),
    _fn("lookup_manager", "The manager an employee reports to.",
        {"employee_email": {"type": "string"}}, ["employee_email"]),
    _fn("approve_request",
        "Approve a request. Deducts the days from the balance and puts the "
        "leave on the team calendar.",
        {"request_id": {"type": "string"}}, ["request_id"]),
    _fn("deny_request", "Deny a request, with a reason.",
        {"request_id": {"type": "string"}, "reason": {"type": "string"}},
        ["request_id", "reason"]),
    _fn("request_changes",
        "Send a request back to the employee to adjust, with a reason.",
        {"request_id": {"type": "string"}, "reason": {"type": "string"}},
        ["request_id", "reason"]),
    _fn("escalate_request", "Send a request to a manager to decide.",
        {"request_id": {"type": "string"}, "manager_email": {"type": "string"}},
        ["request_id", "manager_email"]),
]

IMPLS = {
    "lookup_request": hr.lookup_request,
    "lookup_employee": hr.lookup_employee,
    "list_requests": hr.list_requests,
    "check_coverage": hr.check_coverage,
    "lookup_manager": hr.lookup_manager,
    "approve_request": hr.approve_request,
    "deny_request": hr.deny_request,
    "request_changes": hr.request_changes,
    "escalate_request": hr.escalate_request,
}


def call_model(messages: list[dict], usage: list[int]) -> dict:
    """One model call. Appends what it cost to `usage`."""
    response = httpx.post(
        f"{PROXY_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {PROXY_KEY}"},
        json={"model": MODEL, "messages": messages, "tools": TOOLS,
              "max_tokens": 1200},
        timeout=TIMEOUT_S)
    response.raise_for_status()
    body = response.json()
    spent = (body.get("usage") or {}).get("total_tokens")
    if isinstance(spent, int):
        usage.append(spent)
    return body["choices"][0]["message"]


def answer(request: str) -> tuple[str, list[dict], list[int]]:
    """Run the tool loop. Returns (reply, tool_calls_for_tracing, usage)."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": request}]
    trace: list[dict] = []
    usage: list[int] = []

    for _ in range(MAX_ROUNDS):
        message = call_model(messages, usage)
        calls = message.get("tool_calls") or []
        if not calls:
            return (message.get("content") or "").strip(), trace, usage
        messages.append(message)
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            impl = IMPLS.get(name)
            result = impl(**args) if impl else {"error": f"no tool {name}"}
            trace.append({"name": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result)})

    return "I could not finish reviewing that request.", trace, usage


def with_ledger(reply: str) -> str:
    """Append what the run did to the HR system.

    The SIA judge is sent `output` and nothing else — not the tool calls — so
    an agent whose real effect is a state change has to say what that change
    was. Every eval case here is scored on this block.
    """
    summary = hr.ledger_summary()
    return (f"{reply}\n\n--- HR SYSTEM AFTER THIS REQUEST ---\n"
            f"{json.dumps(summary, indent=2, sort_keys=True)}")


def main() -> int:
    missing = [name for name, value in (("LITELLM_PROXY_URL", PROXY_URL),
                                        ("LITELLM_PROXY_KEY", PROXY_KEY))
               if not value.strip()]
    if missing:
        print(json.dumps({"error": f"{' and '.join(missing)} "
                                   f"{'are' if len(missing) > 1 else 'is'} "
                                   f"not set — export "
                                   f"{'them' if len(missing) > 1 else 'it'}, "
                                   f"or `set -a; . .env; set +a` from the "
                                   f"repo root"}))
        return 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"error": "stdin was not JSON"}))
        return 1
    try:
        reply, trace, usage = answer(str(payload.get("input") or ""))
    except httpx.HTTPError as e:
        print(json.dumps({"error": f"model call failed: {e}"}))
        return 1
    print(json.dumps({"output": with_ledger(reply), "tool_calls": trace,
                      "tokens": sum(usage) if usage else None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
