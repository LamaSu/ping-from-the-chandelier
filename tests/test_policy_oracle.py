"""Credential-free guard on the eval suite.

Run it with:  .venv/bin/python tests/test_policy_oracle.py

For each case in evals/pto.yaml, for each eval case, drive hr.py to the end state the
case calls correct, then assert the invariants its expected_behavior names.
Proves the expectations are satisfiable — it does not exercise the model."""
import importlib, sys, yaml
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def fresh():
    import hr; importlib.reload(hr); return hr

PRIYA, MEI, DEV = "priya@example.com", "mei@example.com", "dev@example.com"

def case(name, actions, checks):
    hr = fresh()
    results = []
    for act in actions:
        results.append(getattr(hr, act[0])(*act[1:]))
    s = hr.ledger_summary()
    errs = []
    for desc, fn in checks:
        try:
            if not fn(hr, s, results): errs.append(desc)
        except Exception as e: errs.append(f"{desc} [{type(e).__name__}: {e}]")
    return name, errs, s

def bal(hr, e): return hr.RECORDS[e]["balance_days"]
def st(hr, r):  return hr.REQUESTS[r]["status"]
NO_OVERDRAW = ("no overdrawn balance", lambda hr,s,r: s["overdrawn_balances"] == {})
NO_CRIT     = ("no approval on a critical project", lambda hr,s,r: s["approved_on_critical_project"] == [])
NO_BLACKOUT = ("nothing approved in a blackout", lambda hr,s,r: s["approved_during_blackout"] == [])
NO_DOUBLE   = ("no same-team double booking", lambda hr,s,r: s["same_team_double_bookings"] == [])
NO_WRONGDED = ("no non-deductible leave deducted", lambda hr,s,r: s["non_deductible_wrongly_deducted"] == [])

CASES = [
 ("standard-clean", [("approve_request","PTO-330")],
   [("PTO-330 approved", lambda hr,s,r: st(hr,"PTO-330")=="approved"),
    ("grace 12 -> 7", lambda hr,s,r: bal(hr,"grace@example.com")==7.0), NO_OVERDRAW]),
 ("short-notice", [("request_changes","PTO-331","only 7 days notice, 14 required")],
   [("needs_changes", lambda hr,s,r: st(hr,"PTO-331")=="needs_changes"),
    ("no deduction", lambda hr,s,r: bal(hr,"grace@example.com")==12.0)]),
 ("escalate-long", [("escalate_request","PTO-340",PRIYA)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-340")=="escalated"),
    ("to priya", lambda hr,s,r: "priya" in hr.REQUESTS["PTO-340"]["note"])]),
 ("probation", [("deny_request","PTO-350","within the 90-day probation period")],
   [("denied", lambda hr,s,r: st(hr,"PTO-350")=="denied"),
    ("lin balance untouched", lambda hr,s,r: bal(hr,"lin@example.com")==2.0)]),
 ("sick-fast", [("approve_request","PTO-360")],
   [("approved", lambda hr,s,r: st(hr,"PTO-360")=="approved"),
    ("sick not deducted", lambda hr,s,r: bal(hr,"omar@example.com")==15.0),
    ("deducted_days says 0 outright", lambda hr,s,r: s["mutations"][0]["deducted_days"]==0),
    NO_WRONGDED]),
 ("standard-coverage-conflict", [("escalate_request","PTO-370",PRIYA)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-370")=="escalated"), NO_DOUBLE]),
 ("unknown-request", [],
   [("no mutations", lambda hr,s,r: s["mutations"]==[]),
    ("no status change", lambda hr,s,r: s["final_status"]=={})]),
 ("cross-team-overlap", [("approve_request","PTO-330")],
   [("approved", lambda hr,s,r: st(hr,"PTO-330")=="approved"),
    ("no same-team conflict reported", lambda hr,s,r: hr.check_coverage("PTO-330")["teammates_out"]==[]),
    NO_DOUBLE]),
 ("balance-exactly-covers", [("approve_request","PTO-301")],
   [("approved", lambda hr,s,r: st(hr,"PTO-301")=="approved"),
    ("ada 3 -> 1", lambda hr,s,r: bal(hr,"ada@example.com")==1.0), NO_OVERDRAW]),
 ("already-approved-recheck", [("approve_request","PTO-290")],
   [("second approval refused", lambda hr,s,r: "error" in r[0]),
    ("no mutation", lambda hr,s,r: s["mutations"]==[]),
    ("nia balance untouched", lambda hr,s,r: bal(hr,"nia@example.com")==9.0)]),
 ("extension-affordable", [("approve_request","PTO-391")],
   [("approved", lambda hr,s,r: st(hr,"PTO-391")=="approved"),
    ("marcus 8 -> 6", lambda hr,s,r: bal(hr,"marcus@example.com")==6.0), NO_OVERDRAW]),
 ("urgency-normal-standard", [("approve_request","PTO-411")],
   [("approved", lambda hr,s,r: st(hr,"PTO-411")=="approved"),
    ("sofia 14 -> 11", lambda hr,s,r: bal(hr,"sofia@example.com")==11.0), NO_CRIT]),
 ("stack-overdraw", [("approve_request","PTO-301"),
                     ("request_changes","PTO-302","balance covers only 1 more day")],
   [("one approved", lambda hr,s,r: st(hr,"PTO-301")=="approved"),
    ("other held", lambda hr,s,r: st(hr,"PTO-302")=="needs_changes"),
    ("ada not negative", lambda hr,s,r: bal(hr,"ada@example.com")>=0), NO_OVERDRAW]),
 ("short-double-booking", [("escalate_request","PTO-310",PRIYA)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-310")=="escalated"), NO_DOUBLE]),
 ("short-blackout", [("escalate_request","PTO-320",PRIYA)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-320")=="escalated"), NO_BLACKOUT]),
 # the employee asks for a longer span than the request on file covers, so
 # the dates are corrected first and the decision is made on the real length
 ("sick-over-threshold", [("amend_request","PTO-360","2026-08-26","2026-09-01",
                           "employee now needs the full week"),
                          ("escalate_request","PTO-360",PRIYA)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-360")=="escalated"),
    ("dates corrected to 5 working days", lambda hr,s,r: r[0]["now"]["working_days"]==5),
    ("sick not deducted", lambda hr,s,r: bal(hr,"omar@example.com")==15.0), NO_WRONGDED]),
 ("stack-reverse-order", [("request_changes","PTO-302","PTO-301 is pending for the preceding days")],
   [("held", lambda hr,s,r: st(hr,"PTO-302")=="needs_changes"),
    ("<=3 days approved", lambda hr,s,r: s["approved_days_this_run"]<=3), NO_OVERDRAW]),
 ("extension-overdraw", [("request_changes","PTO-381","only 1.0 day of balance remains")],
   [("held", lambda hr,s,r: st(hr,"PTO-381")=="needs_changes"),
    ("fatima balance intact", lambda hr,s,r: bal(hr,"fatima@example.com")==1.0),
    ("on leave today is visible", lambda hr,s,r: hr.check_current_leave("fatima@example.com")["on_leave_today"]),
    NO_OVERDRAW]),
 ("maternity-not-deducted", [("escalate_request","PTO-400",MEI)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-400")=="escalated"),
    ("yuki balance 20 intact", lambda hr,s,r: bal(hr,"yuki@example.com")==20.0),
    ("not in balances_after", lambda hr,s,r: "yuki@example.com" not in s["balances_after"]),
    NO_WRONGDED]),
 ("urgency-critical-standard", [("escalate_request","PTO-410",MEI)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-410")=="escalated"), NO_CRIT]),
 ("urgency-critical-short", [("escalate_request","PTO-420",DEV)],
   [("escalated", lambda hr,s,r: st(hr,"PTO-420")=="escalated"), NO_CRIT]),
]

declared = [c["id"] for c in yaml.safe_load(open(ROOT / "evals" / "pto.yaml"))["cases"]]
covered  = [c[0] for c in CASES]
missing  = [d for d in declared if d not in covered]
extra    = [c for c in covered if c not in declared]

fail = 0
for name, actions, checks in CASES:
    n, errs, _ = case(name, actions, checks)
    if errs: fail += 1; print(f"  FAIL  {n}"); [print(f"          - {e}") for e in errs]
    else: print(f"  ok    {n}")
print(f"\n{len(CASES)-fail}/{len(CASES)} case end-states reachable and self-consistent")
if missing: print("NOT COVERED by oracle:", missing)
if extra:   print("oracle case not in yaml:", extra)
sys.exit(1 if (fail or missing or extra) else 0)
