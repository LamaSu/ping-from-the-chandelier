"""The PTO ledger this agent reads and writes.

Each process starts from a pristine copy of SEED, so one eval case can never
see another's approvals. Mutating tools append to MUTATIONS, which is what
`agent.py` reports back so the judge can score the state the run left behind.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

EMPLOYEES = {
    "ada@example.com": {"name": "Ada Okafor", "department": "Engineering",
                        "manager": "priya@example.com",
                        "pto_balance_days": 12, "hire_date": "2024-03-15"},
    "grace@example.com": {"name": "Grace Lindqvist", "department": "Design",
                          "manager": "priya@example.com",
                          "pto_balance_days": 8, "hire_date": "2023-06-01"},
    "lin@example.com": {"name": "Lin Zhao", "department": "Sales",
                        "manager": "sam@example.com",
                        "pto_balance_days": 3, "hire_date": "2025-01-10"},
}

BLACKOUT_PERIODS = [
    {"start": "2026-09-14", "end": "2026-09-18", "reason": "Company all-hands"},
    {"start": "2026-12-28", "end": "2026-12-31", "reason": "Year-end close"},
]

# status: submitted | approved | rejected | escalated | withdrawn
SEED = {
    # Ada requests the same 3-day block twice — two separate request ids.
    "PTO-101": {"employee": "ada@example.com", "type": "vacation",
                "start_date": "2026-09-08", "end_date": "2026-09-10",
                "days": 3, "status": "submitted",
                "reason": "Family trip to Tahoe"},
    "PTO-102": {"employee": "ada@example.com", "type": "vacation",
                "start_date": "2026-09-08", "end_date": "2026-09-10",
                "days": 3, "status": "submitted",
                "reason": "Tahoe vacation"},

    # Grace requests two adjacent blocks that together span the blackout.
    "PTO-110": {"employee": "grace@example.com", "type": "vacation",
                "start_date": "2026-09-11", "end_date": "2026-09-12",
                "days": 2, "status": "submitted",
                "reason": "Extended weekend"},
    "PTO-111": {"employee": "grace@example.com", "type": "vacation",
                "start_date": "2026-09-15", "end_date": "2026-09-17",
                "days": 3, "status": "submitted",
                "reason": "Personal travel"},

    # Ordinary requests. The policy handles these correctly.
    "PTO-120": {"employee": "lin@example.com", "type": "sick",
                "start_date": "2026-08-20", "end_date": "2026-08-20",
                "days": 1, "status": "submitted",
                "reason": "Not feeling well"},
    "PTO-121": {"employee": "ada@example.com", "type": "vacation",
                "start_date": "2026-10-20", "end_date": "2026-10-24",
                "days": 5, "status": "submitted",
                "reason": "Fall break with family"},
    "PTO-130": {"employee": "grace@example.com", "type": "vacation",
                "start_date": "2026-11-03", "end_date": "2026-11-14",
                "days": 10, "status": "submitted",
                "reason": "Trip to Japan"},
    "PTO-140": {"employee": "lin@example.com", "type": "vacation",
                "start_date": "2026-09-01", "end_date": "2026-09-05",
                "days": 5, "status": "submitted",
                "reason": "Beach trip"},
    "PTO-150": {"employee": "ada@example.com", "type": "bereavement",
                "start_date": "2026-08-25", "end_date": "2026-08-27",
                "days": 3, "status": "submitted",
                "reason": "Family loss"},
}

LEDGER: dict[str, dict] = copy.deepcopy(SEED)
MUTATIONS: list[dict] = []

VALID_TYPES = {"vacation", "sick", "personal", "bereavement"}
DECIDED = {"approved", "rejected", "escalated"}


def _get(request_id: str) -> tuple[str, dict] | None:
    key = (request_id or "").strip().upper()
    entry = LEDGER.get(key)
    return (key, entry) if entry else None


def _dates_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    try:
        a0, a1 = date.fromisoformat(s1), date.fromisoformat(e1)
        b0, b1 = date.fromisoformat(s2), date.fromisoformat(e2)
        return a0 <= b1 and b0 <= a1
    except ValueError:
        return False


def _decide(request_id: str, status: str, note: str) -> dict:
    found = _get(request_id)
    if found is None:
        return {"error": f"No PTO request {request_id!r} exists."}
    key, entry = found
    if entry["status"] in DECIDED:
        return {"error": f"{key} is already {entry['status']} and cannot be "
                         f"changed."}
    before = entry["status"]
    entry["status"] = status
    entry["note"] = note
    MUTATIONS.append({"request_id": key, "from": before, "to": status,
                      "days": entry["days"], "note": note})
    return {"request_id": key, "status": status, "note": note,
            "days": entry["days"]}


# --- read tools -------------------------------------------------------------
def lookup_request(request_id: str) -> dict:
    found = _get(request_id)
    if found is None:
        return {"error": f"No PTO request {request_id!r} exists."}
    key, entry = found
    return {"request_id": key, **{k: v for k, v in entry.items()
                                  if k != "note"}}


def list_requests(employee_email: str, status: str = "") -> dict:
    email = (employee_email or "").strip().lower()
    if email not in EMPLOYEES:
        return {"error": f"No employee {employee_email!r}."}
    matches = [{"request_id": k, "type": v["type"], "days": v["days"],
                "start_date": v["start_date"], "end_date": v["end_date"],
                "status": v["status"]}
               for k, v in LEDGER.items()
               if v["employee"] == email
               and (not status or v["status"] == status)]
    return {"employee": email, "requests": matches}


def find_overlapping_requests(request_id: str) -> dict:
    """Other requests by the same employee whose dates overlap."""
    found = _get(request_id)
    if found is None:
        return {"error": f"No PTO request {request_id!r} exists."}
    key, entry = found
    overlaps = []
    for other_key, other in LEDGER.items():
        if other_key == key or other["employee"] != entry["employee"]:
            continue
        if _dates_overlap(entry["start_date"], entry["end_date"],
                          other["start_date"], other["end_date"]):
            overlaps.append({"request_id": other_key, "days": other["days"],
                             "start_date": other["start_date"],
                             "end_date": other["end_date"],
                             "status": other["status"],
                             "reason": other["reason"]})
    total_days = entry["days"] + sum(o["days"] for o in overlaps)
    return {"request_id": key, "overlapping": overlaps,
            "combined_days": total_days}


def check_balance(employee_email: str) -> dict:
    email = (employee_email or "").strip().lower()
    emp = EMPLOYEES.get(email)
    if emp is None:
        return {"error": f"No employee {employee_email!r}."}
    approved_days = sum(v["days"] for v in LEDGER.values()
                        if v["employee"] == email and v["status"] == "approved")
    return {"employee": email, "total_balance": emp["pto_balance_days"],
            "used": approved_days,
            "remaining": emp["pto_balance_days"] - approved_days}


def check_blackout(start_date: str, end_date: str) -> dict:
    conflicts = []
    for bp in BLACKOUT_PERIODS:
        if _dates_overlap(start_date, end_date, bp["start"], bp["end"]):
            conflicts.append(bp)
    return {"start_date": start_date, "end_date": end_date,
            "conflicts": conflicts, "blocked": len(conflicts) > 0}


def lookup_manager(employee_email: str) -> dict:
    email = (employee_email or "").strip().lower()
    employee = EMPLOYEES.get(email)
    if employee is None:
        return {"error": f"No employee {employee_email!r}."}
    return {"employee": email, "manager": employee["manager"]}


# --- mutating tools ---------------------------------------------------------
def approve_request(request_id: str) -> dict:
    return _decide(request_id, "approved", "approved")


def reject_request(request_id: str, reason: str = "") -> dict:
    if not (reason or "").strip():
        return {"error": "A rejection needs a reason."}
    return _decide(request_id, "rejected", reason.strip())


def escalate_request(request_id: str, manager_email: str) -> dict:
    email = (manager_email or "").strip().lower()
    if email not in {e["manager"] for e in EMPLOYEES.values()}:
        return {"error": f"{manager_email!r} is not a manager here."}
    return _decide(request_id, "escalated", f"escalated to {email}")


def ledger_summary() -> dict:
    return {
        "mutations": MUTATIONS,
        "approved_total_days": sum(e["days"] for e in LEDGER.values()
                                   if e["status"] == "approved"),
        "final_status": {k: v["status"] for k, v in LEDGER.items()
                         if v["status"] != SEED[k]["status"]},
    }
