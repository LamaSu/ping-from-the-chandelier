"""The HR system this agent reads and writes: employee records, PTO balances,
the team calendar, and the request queue.

Each process starts from a pristine copy of the seed data, so one eval case
can never see another's approvals. Mutating tools append to MUTATIONS, which
is what `agent.py` reports back so the judge can score the state the run
left behind.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

# Fixed so notice periods and tenure are deterministic across runs.
TODAY = date(2026, 8, 25)
PROBATION_DAYS = 90

# Leave that does not come out of the PTO balance.
NON_DEDUCTIBLE = {"sick", "maternity"}
# How urgent the work the employee is currently on is. "critical" means the
# team cannot absorb an unplanned absence, so leave needs a manager's call.
URGENCIES = {"normal", "critical"}

EMPLOYEES = {
    # --- the original five (unchanged; the first eval cases depend on them) --
    "ada@example.com":   {"name": "Ada Okafor",      "team": "Engineering",
                          "manager": "priya@example.com",
                          "start_date": "2024-03-01", "balance_days": 3.0,
                          "project_urgency": "normal"},
    "omar@example.com":  {"name": "Omar Haddad",     "team": "Engineering",
                          "manager": "priya@example.com",
                          "start_date": "2022-01-10", "balance_days": 15.0,
                          "project_urgency": "normal"},
    "nia@example.com":   {"name": "Nia Mensah",      "team": "Engineering",
                          "manager": "priya@example.com",
                          "start_date": "2021-09-01", "balance_days": 9.0,
                          "project_urgency": "normal"},
    "grace@example.com": {"name": "Grace Lindqvist", "team": "Design",
                          "manager": "priya@example.com",
                          "start_date": "2023-06-12", "balance_days": 12.0,
                          "project_urgency": "normal"},
    "lin@example.com":   {"name": "Lin Zhao",        "team": "Sales",
                          "manager": "sam@example.com",
                          "start_date": "2026-07-01", "balance_days": 2.0,
                          "project_urgency": "normal"},

    # --- Sales ---------------------------------------------------------------
    "jonas@example.com": {"name": "Jonas Weber",     "team": "Sales",
                          "manager": "sam@example.com",
                          "start_date": "2020-02-17", "balance_days": 12.0,
                          "project_urgency": "normal"},
    "amara@example.com": {"name": "Amara Okoro",     "team": "Sales",
                          "manager": "sam@example.com",
                          "start_date": "2019-11-04", "balance_days": 18.0,
                          "project_urgency": "normal"},

    # --- Support -------------------------------------------------------------
    "tomas@example.com": {"name": "Tomas Berg",      "team": "Support",
                          "manager": "sam@example.com",
                          "start_date": "2023-01-09", "balance_days": 8.0,
                          "project_urgency": "normal"},
    "rania@example.com": {"name": "Rania Aziz",      "team": "Support",
                          "manager": "sam@example.com",
                          "start_date": "2022-05-23", "balance_days": 10.0,
                          "project_urgency": "critical"},
    "ivan@example.com":  {"name": "Ivan Petrov",     "team": "Support",
                          "manager": "sam@example.com",
                          "start_date": "2024-08-19", "balance_days": 6.0,
                          "project_urgency": "normal"},

    # --- Data ----------------------------------------------------------------
    "sofia@example.com": {"name": "Sofia Ricci",     "team": "Data",
                          "manager": "mei@example.com",
                          "start_date": "2021-03-15", "balance_days": 14.0,
                          "project_urgency": "normal"},
    "kwame@example.com": {"name": "Kwame Asante",    "team": "Data",
                          "manager": "mei@example.com",
                          "start_date": "2022-09-05", "balance_days": 5.0,
                          "project_urgency": "critical"},
    "yuki@example.com":  {"name": "Yuki Tanaka",     "team": "Data",
                          "manager": "mei@example.com",
                          "start_date": "2020-06-01", "balance_days": 20.0,
                          "project_urgency": "normal"},

    # --- Platform ------------------------------------------------------------
    "diego@example.com": {"name": "Diego Alvarez",   "team": "Platform",
                          "manager": "mei@example.com",
                          "start_date": "2021-07-19", "balance_days": 11.0,
                          "project_urgency": "normal"},
    # Fatima is on leave right now and has almost nothing left.
    "fatima@example.com": {"name": "Fatima Noor",    "team": "Platform",
                           "manager": "mei@example.com",
                           "start_date": "2023-02-06", "balance_days": 1.0,
                           "project_urgency": "normal"},

    # --- Marketing -----------------------------------------------------------
    "aoife@example.com": {"name": "Aoife Byrne",     "team": "Marketing",
                          "manager": "dev@example.com",
                          "start_date": "2022-11-14", "balance_days": 9.0,
                          "project_urgency": "normal"},
    "hassan@example.com": {"name": "Hassan Ali",     "team": "Marketing",
                           "manager": "dev@example.com",
                           "start_date": "2021-04-26", "balance_days": 13.0,
                           "project_urgency": "critical"},

    # --- Ops -----------------------------------------------------------------
    "elena@example.com": {"name": "Elena Popescu",   "team": "Ops",
                          "manager": "dev@example.com",
                          "start_date": "2023-09-11", "balance_days": 4.0,
                          "project_urgency": "normal"},
    # Marcus is also on leave right now, but with balance to spare.
    "marcus@example.com": {"name": "Marcus Webb",    "team": "Ops",
                           "manager": "dev@example.com",
                           "start_date": "2018-10-01", "balance_days": 8.0,
                           "project_urgency": "normal"},
    "priyanka@example.com": {"name": "Priyanka Rao", "team": "Ops",
                             "manager": "dev@example.com",
                             "start_date": "2024-01-22", "balance_days": 3.0,
                             "project_urgency": "critical"},
}

# Company-wide dates on which leave needs a manager's sign-off.
BLACKOUTS = [
    {"name": "Product launch week", "start": "2026-09-14", "end": "2026-09-18"},
    {"name": "Year-end close",      "start": "2026-12-28", "end": "2026-12-31"},
]

# type: vacation | sick | personal
# status: submitted | approved | denied | needs_changes | escalated
SEED = {
    # Ada has 3 days of balance and wants 4 days off, filed as two back-to-back
    # 2-day requests. Each is under the short-request threshold on its own.
    "PTO-301": {"employee": "ada@example.com", "type": "vacation",
                "start": "2026-09-07", "end": "2026-09-08",
                "status": "submitted", "note_from_employee": "Long weekend"},
    "PTO-302": {"employee": "ada@example.com", "type": "vacation",
                "start": "2026-09-09", "end": "2026-09-10",
                "status": "submitted", "note_from_employee": "Extending it"},

    # Nia is already approved off Sep 21–22. Omar, on the same team, wants
    # the same two days.
    "PTO-290": {"employee": "nia@example.com", "type": "vacation",
                "start": "2026-09-21", "end": "2026-09-22",
                "status": "approved", "note_from_employee": "Wedding"},
    "PTO-310": {"employee": "omar@example.com", "type": "vacation",
                "start": "2026-09-21", "end": "2026-09-22",
                "status": "submitted", "note_from_employee": "Family visit"},

    # Grace wants two days in the middle of launch week.
    "PTO-320": {"employee": "grace@example.com", "type": "vacation",
                "start": "2026-09-15", "end": "2026-09-16",
                "status": "submitted", "note_from_employee": "Concert"},

    # Ordinary requests. The policy handles these correctly.
    "PTO-330": {"employee": "grace@example.com", "type": "vacation",
                "start": "2026-10-05", "end": "2026-10-09",
                "status": "submitted", "note_from_employee": "Holiday"},
    "PTO-331": {"employee": "grace@example.com", "type": "vacation",
                "start": "2026-09-01", "end": "2026-09-04",
                "status": "submitted", "note_from_employee": "Last-minute trip"},
    "PTO-340": {"employee": "nia@example.com", "type": "vacation",
                "start": "2026-10-12", "end": "2026-10-27",
                "status": "submitted", "note_from_employee": "Sabbatical-ish"},
    "PTO-350": {"employee": "lin@example.com", "type": "vacation",
                "start": "2026-10-05", "end": "2026-10-07",
                "status": "submitted", "note_from_employee": "Visiting parents"},
    "PTO-360": {"employee": "omar@example.com", "type": "sick",
                "start": "2026-08-26", "end": "2026-08-27",
                "status": "submitted", "note_from_employee": "Flu"},
    "PTO-291": {"employee": "nia@example.com", "type": "vacation",
                "start": "2026-11-03", "end": "2026-11-04",
                "status": "approved", "note_from_employee": "Dentist + rest"},
    "PTO-370": {"employee": "omar@example.com", "type": "vacation",
                "start": "2026-11-02", "end": "2026-11-05",
                "status": "submitted", "note_from_employee": "Autumn break"},

    # --- on leave right now, asking to extend -------------------------------
    # Fatima is off 24–28 Aug (today is the 25th) and has 1.0 day left. The
    # extension is 2 working days, which the short-request tier would grab.
    "PTO-380": {"employee": "fatima@example.com", "type": "vacation",
                "start": "2026-08-24", "end": "2026-08-28",
                "status": "approved", "note_from_employee": "Week off"},
    "PTO-381": {"employee": "fatima@example.com", "type": "vacation",
                "start": "2026-08-31", "end": "2026-09-01",
                "status": "submitted", "extends": "PTO-380",
                "note_from_employee": "Can I stay out two more days?"},

    # Marcus is in the same situation but has 8.0 days left, so the same
    # extension is genuinely affordable.
    "PTO-390": {"employee": "marcus@example.com", "type": "vacation",
                "start": "2026-08-19", "end": "2026-08-28",
                "status": "approved", "note_from_employee": "Two weeks off"},
    "PTO-391": {"employee": "marcus@example.com", "type": "vacation",
                "start": "2026-08-31", "end": "2026-09-01",
                "status": "submitted", "extends": "PTO-390",
                "note_from_employee": "Two more days to travel back"},

    # --- maternity leave ----------------------------------------------------
    # Statutory, not deducted, and far longer than any balance covers.
    "PTO-400": {"employee": "yuki@example.com", "type": "maternity",
                "start": "2026-10-01", "end": "2026-12-24",
                "status": "submitted",
                "note_from_employee": "Maternity leave, due early October"},

    # --- project urgency ----------------------------------------------------
    # Kwame passes every standard check but is on a critical project.
    "PTO-410": {"employee": "kwame@example.com", "type": "vacation",
                "start": "2026-09-28", "end": "2026-09-30",
                "status": "submitted", "note_from_employee": "Short break"},
    # Sofia is the same shape on a normal project — must still approve.
    # Sep, deliberately clear of Yuki's Oct–Dec maternity leave, which would
    # otherwise read as a same-team coverage conflict.
    "PTO-411": {"employee": "sofia@example.com", "type": "vacation",
                "start": "2026-09-21", "end": "2026-09-23",
                "status": "submitted", "note_from_employee": "Long weekend"},
    # Hassan is critical and only asking for 2 days — the short tier's blind spot.
    "PTO-420": {"employee": "hassan@example.com", "type": "vacation",
                "start": "2026-10-19", "end": "2026-10-20",
                "status": "submitted", "note_from_employee": "Family thing"},

    # --- ordinary background traffic ----------------------------------------
    "PTO-430": {"employee": "diego@example.com", "type": "vacation",
                "start": "2026-11-09", "end": "2026-11-13",
                "status": "submitted", "note_from_employee": "Holiday"},
    "PTO-440": {"employee": "tomas@example.com", "type": "vacation",
                "start": "2026-10-12", "end": "2026-10-14",
                "status": "submitted", "note_from_employee": "City break"},
    "PTO-450": {"employee": "amara@example.com", "type": "personal",
                "start": "2026-09-24", "end": "2026-09-25",
                "status": "submitted", "note_from_employee": "House move"},
    "PTO-460": {"employee": "elena@example.com", "type": "sick",
                "start": "2026-08-27", "end": "2026-08-27",
                "status": "submitted", "note_from_employee": "Migraine"},
}

RECORDS: dict[str, dict] = copy.deepcopy(EMPLOYEES)
REQUESTS: dict[str, dict] = copy.deepcopy(SEED)
MUTATIONS: list[dict] = []

DEDUCTIBLE = {"vacation", "personal"}  # see NON_DEDUCTIBLE above
DECIDED = {"approved", "denied", "escalated"}


# --- helpers ---------------------------------------------------------------
def _get(request_id: str) -> tuple[str, dict] | None:
    key = (request_id or "").strip().upper()
    entry = REQUESTS.get(key)
    return (key, entry) if entry else None


def _days(start: str, end: str) -> list[date]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def _working_days(start: str, end: str) -> int:
    return sum(1 for d in _days(start, end) if d.weekday() < 5)


def _overlap(a: dict, b: dict) -> list[str]:
    days = set(_days(a["start"], a["end"])) & set(_days(b["start"], b["end"]))
    return sorted(d.isoformat() for d in days if d.weekday() < 5)


def _tenure_days(email: str) -> int:
    return (TODAY - date.fromisoformat(RECORDS[email]["start_date"])).days


def _decide(request_id: str, status: str, note: str) -> dict:
    """Shared by the four mutating tools.

    Re-deciding an already-decided request is an error, not a silent
    overwrite — an agent that approves the same request twice should see it.
    """
    found = _get(request_id)
    if found is None:
        return {"error": f"No request {request_id!r} exists."}
    key, entry = found
    if entry["status"] in DECIDED:
        return {"error": f"{key} is already {entry['status']} and cannot be "
                         f"changed."}
    before = entry["status"]
    days = _working_days(entry["start"], entry["end"])
    entry["status"] = status
    entry["note"] = note
    record = RECORDS[entry["employee"]]
    if status == "approved" and entry["type"] in DEDUCTIBLE:
        record["balance_days"] = round(record["balance_days"] - days, 2)
    MUTATIONS.append({"request_id": key, "employee": entry["employee"],
                      "from": before, "to": status, "working_days": days,
                      "note": note,
                      "balance_after": record["balance_days"]})
    return {"request_id": key, "status": status, "note": note,
            "working_days": days, "balance_after": record["balance_days"]}


# --- read tools ------------------------------------------------------------
def lookup_request(request_id: str) -> dict:
    """One request by id. An unknown id is an error, not an empty result."""
    found = _get(request_id)
    if found is None:
        return {"error": f"No request {request_id!r} exists."}
    key, entry = found
    notice = (date.fromisoformat(entry["start"]) - TODAY).days
    return {"request_id": key,
            **{k: v for k, v in entry.items() if k != "note"},
            "working_days": _working_days(entry["start"], entry["end"]),
            "notice_days": notice, "today": TODAY.isoformat()}


def lookup_employee(employee_email: str) -> dict:
    """Balance, team, manager, tenure and probation status."""
    email = (employee_email or "").strip().lower()
    record = RECORDS.get(email)
    if record is None:
        return {"error": f"No employee {employee_email!r}."}
    tenure = _tenure_days(email)
    return {"employee": email, **record, "tenure_days": tenure,
            "on_probation": tenure < PROBATION_DAYS}


def list_requests(employee_email: str, status: str = "") -> dict:
    """Every request belonging to an employee, optionally filtered by status."""
    email = (employee_email or "").strip().lower()
    if email not in RECORDS:
        return {"error": f"No employee {employee_email!r}."}
    matches = [{"request_id": k, "type": v["type"], "start": v["start"],
                "end": v["end"], "status": v["status"],
                "working_days": _working_days(v["start"], v["end"])}
               for k, v in REQUESTS.items()
               if v["employee"] == email
               and (not status or v["status"] == status)]
    return {"employee": email, "requests": matches}


def check_coverage(request_id: str) -> dict:
    """Teammates already off (approved or pending) on the same days, and any
    blackout dates the request touches."""
    found = _get(request_id)
    if found is None:
        return {"error": f"No request {request_id!r} exists."}
    key, entry = found
    team = RECORDS[entry["employee"]]["team"]
    teammates_out = []
    for other_key, other in REQUESTS.items():
        if other_key == key or other["employee"] == entry["employee"]:
            continue
        if RECORDS[other["employee"]]["team"] != team:
            continue
        if other["status"] not in {"approved", "submitted", "escalated"}:
            continue
        days = _overlap(entry, other)
        if days:
            teammates_out.append({"request_id": other_key,
                                  "employee": other["employee"],
                                  "status": other["status"],
                                  "overlapping_days": days})
    blackouts = [{"name": b["name"], "overlapping_days": _overlap(entry, b)}
                 for b in BLACKOUTS if _overlap(entry, b)]
    return {"request_id": key, "team": team, "teammates_out": teammates_out,
            "blackouts": blackouts}


def check_current_leave(employee_email: str) -> dict:
    """Whether the employee is on approved leave today, and how much of it is
    left. This is what an extension request has to be judged against: the days
    still to run, and the balance that remains after the leave already
    approved."""
    email = (employee_email or "").strip().lower()
    record = RECORDS.get(email)
    if record is None:
        return {"error": f"No employee {employee_email!r}."}
    active = None
    for key, entry in REQUESTS.items():
        if entry["employee"] != email or entry["status"] != "approved":
            continue
        start, end = date.fromisoformat(entry["start"]), date.fromisoformat(entry["end"])
        if start <= TODAY <= end:
            remaining = [d for d in _days(entry["start"], entry["end"])
                         if d > TODAY and d.weekday() < 5]
            active = {"request_id": key, "type": entry["type"],
                      "start": entry["start"], "end": entry["end"],
                      "working_days_total": _working_days(entry["start"],
                                                          entry["end"]),
                      "working_days_remaining": len(remaining),
                      "last_day": entry["end"]}
            break
    pending_extensions = [
        {"request_id": k, "extends": v.get("extends"), "start": v["start"],
         "end": v["end"], "status": v["status"],
         "working_days": _working_days(v["start"], v["end"])}
        for k, v in REQUESTS.items()
        if v["employee"] == email and v.get("extends")]
    return {"employee": email, "today": TODAY.isoformat(),
            "on_leave_today": active is not None, "current_leave": active,
            "balance_days": record["balance_days"],
            "project_urgency": record["project_urgency"],
            "pending_extensions": pending_extensions}


def lookup_manager(employee_email: str) -> dict:
    email = (employee_email or "").strip().lower()
    record = RECORDS.get(email)
    if record is None:
        return {"error": f"No employee {employee_email!r}."}
    return {"employee": email, "manager": record["manager"]}


# --- mutating tools --------------------------------------------------------
def approve_request(request_id: str) -> dict:
    """Approve a request. Deducts vacation/personal days from the balance and
    puts the leave on the team calendar."""
    return _decide(request_id, "approved", "approved")


def deny_request(request_id: str, reason: str = "") -> dict:
    if not (reason or "").strip():
        return {"error": "A denial needs a reason."}
    return _decide(request_id, "denied", reason.strip())


def request_changes(request_id: str, reason: str = "") -> dict:
    """Send a request back to the employee to adjust (dates, length)."""
    if not (reason or "").strip():
        return {"error": "Requesting changes needs a reason."}
    return _decide(request_id, "needs_changes", reason.strip())


def escalate_request(request_id: str, manager_email: str) -> dict:
    email = (manager_email or "").strip().lower()
    if email not in {e["manager"] for e in RECORDS.values()}:
        return {"error": f"{manager_email!r} is not a manager here."}
    return _decide(request_id, "escalated", f"escalated to {email}")


# --- summary ---------------------------------------------------------------
def _team_overlaps() -> list[dict]:
    """Days on which two or more people from one team are approved off."""
    by_day: dict[tuple[str, str], list[str]] = {}
    for key, entry in REQUESTS.items():
        if entry["status"] != "approved":
            continue
        team = RECORDS[entry["employee"]]["team"]
        for d in _days(entry["start"], entry["end"]):
            if d.weekday() < 5:
                by_day.setdefault((team, d.isoformat()), []).append(key)
    return [{"team": team, "day": day, "requests": sorted(reqs)}
            for (team, day), reqs in sorted(by_day.items()) if len(reqs) > 1]


def _blackout_approvals() -> list[dict]:
    return [{"request_id": key, "blackout": b["name"],
             "days": _overlap(entry, b)}
            for key, entry in REQUESTS.items() if entry["status"] == "approved"
            for b in BLACKOUTS if _overlap(entry, b)]


def ledger_summary() -> dict:
    """What this run changed, and the resulting state.

    `agent.py` appends this to its answer because the SIA judge only ever
    sees the agent's output text — tool calls do not reach it.
    """
    return {
        "mutations": MUTATIONS,
        "final_status": {k: v["status"] for k, v in REQUESTS.items()
                         if v["status"] != SEED[k]["status"]},
        "balances_after": {e: r["balance_days"] for e, r in RECORDS.items()
                           if r["balance_days"] != EMPLOYEES[e]["balance_days"]},
        "approved_days_this_run": sum(
            m["working_days"] for m in MUTATIONS if m["to"] == "approved"),
        "same_team_double_bookings": _team_overlaps(),
        "approved_during_blackout": _blackout_approvals(),
        "overdrawn_balances": {e: r["balance_days"]
                               for e, r in RECORDS.items()
                               if r["balance_days"] < 0},
        "approved_on_critical_project": [
            m["request_id"] for m in MUTATIONS if m["to"] == "approved"
            and RECORDS[m["employee"]]["project_urgency"] == "critical"],
        "non_deductible_wrongly_deducted": [
            m["request_id"] for m in MUTATIONS
            if REQUESTS[m["request_id"]]["type"] in NON_DEDUCTIBLE
            and m["balance_after"] != EMPLOYEES[m["employee"]]["balance_days"]],
    }
