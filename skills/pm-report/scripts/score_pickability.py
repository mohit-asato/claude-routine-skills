#!/usr/bin/env python3
"""
Pickability scoring for the AM / PM daily report skills.

The model extracts the inputs (including the judgement calls); this script does
the arithmetic, so scores never drift between runs.

Precedence, highest first:
  1. Customer-success escalation  (hard override, outranks everything)
  2. Deadline proximity           (Jira fix version release date)
  3. Jira priority
  4. Age without real movement

Usage
-----
    python score_pickability.py --today 2026-08-19 items.json
    cat items.json | python score_pickability.py --today 2026-08-19 -

Input: a JSON array of objects. Recognised keys per item (all optional except
itemId):

    itemId              str   required, echoed back
    jiraStatus          str   Jira status name. ONLY "To Do" and "In Progress"
                              are pickable — see ELIGIBILITY below. Omit/null for
                              non-Jira items (they count as pickable).
    priority            str   "Highest"|"High"|"Medium"|"Low"|"Lowest"|"n/a"
    ageDays             int   days without real movement
    fixVersion          str   e.g. "release-08-25-2026"    (null if unset)
    releaseDate         str   "YYYY-MM-DD" from the fix version (null if unset)
    blockingSomeone     bool  a named person is actively waiting on the user
                              (review ask, direct question, unanswered request).
                              Supplies a deadline for non-Jira items — see
                              DEADLINE NOTE below.
    csEscalation        obj   null, or {author, role, quote, date, environment}
                              Set ONLY when a customer-success/support person has
                              asked for this urgently in some environment.

Output: the same array, each item gaining a `pickability` block and a `tier`,
sorted by score descending.

ELIGIBILITY
-----------
Pickability answers "should I pick this up now," so it only applies to work the
user can actually pick up: Jira status **To Do** or **In Progress**, plus
non-Jira items (a review ask has no status but is obviously actionable).

Everything else — Testing, Dev Complete, Backlog, Req Analysis, Closed — is either
waiting on somebody else or not ready to start. Those items are NOT scored. They
come back with `pickability: null` and a `pickabilityExcluded` reason, and sort
below every scored item. They still belong in the report (a ticket parked in
Testing for three weeks needs a QA nudge) — they just don't compete for the top
of the list, because the answer there is "chase someone," not "do the work."

DEADLINE NOTE
-------------
"How close is the release" is the top-weighted factor, but non-Jira work (a
review someone is blocked on, a direct Slack ask) has no fix version. Those items
still have a real deadline: a person is waiting. So deadline proximity is sourced
in this order:

    1. fix version release date, when present
    2. else, if blockingSomeone: treated as a 2-day deadline
    3. else: unscheduled baseline

Without rule 2 a teammate blocked on a review scores ~20 and sinks below a
three-month-old backlog ticket, which is the opposite of pickable.
"""
import argparse, json, sys
from datetime import date, datetime

SCORING_MODEL = "pickability-v1"

# --------------------------------------------------------------- 1. deadline
DEADLINE_MAX = 50

def deadline_points(days, has_deadline):
    """0-50. The heaviest factor."""
    if not has_deadline or days is None:
        return 8                      # unscheduled — not unimportant, just undated
    if days < 0:   return 50          # release date passed and it's still open
    if days == 0:  return 50          # ships today
    if days == 1:  return 44
    if days == 2:  return 38
    if days <= 4:  return 31
    if days <= 7:  return 24
    if days <= 14: return 15
    if days <= 30: return 8
    return 3

BLOCKED_DEADLINE_DAYS = 2             # a person waiting == a 2-day deadline

# --------------------------------------------------------------- 2. priority
PRIORITY_MAX = 30
PRIORITY_POINTS = {
    "highest": 30, "high": 22, "medium": 12, "low": 5, "lowest": 2,
}
PRIORITY_DEFAULT = 12                 # unknown / non-Jira -> Medium-equivalent

def priority_points(priority):
    if not priority:
        return PRIORITY_DEFAULT
    return PRIORITY_POINTS.get(str(priority).strip().lower(), PRIORITY_DEFAULT)

# -------------------------------------------------------------------- 3. age
AGE_MAX = 20

def age_points(age_days):
    """0-20. Capped on purpose: an ancient P3 must never outrank a fresh P0."""
    a = age_days or 0
    if a <= 1:   return 0
    if a <= 3:   return 3
    if a <= 7:   return 7
    if a <= 14:  return 11
    if a <= 30:  return 15
    if a <= 60:  return 18
    return 20

# ------------------------------------------------------- 4. the CS wildcard
# Must exceed the theoretical base max (50+30+20=100) so that any genuine
# customer-success escalation outranks every non-escalated item, including one
# shipping today. Ties between escalated items fall back to their base score.
CS_ESCALATION_POINTS = 100

# ------------------------------------------------------------- eligibility
# Only work the user can actually pick up gets scored.
PICKABLE_STATUSES = {"to do", "todo", "to-do", "in progress", "in-progress", "inprogress"}

def eligibility(item):
    """(is_pickable, reason_if_not)."""
    status = item.get("jiraStatus")
    if not status:
        return True, None                     # non-Jira item — actionable by nature
    s = str(status).strip().lower()
    if s in PICKABLE_STATUSES:
        return True, None
    return False, f"status '{status}' is not pickable — waiting on someone else or not ready to start"

# ------------------------------------------------------------------- tiers
FIRE_AT, TODAY_AT = 70, 45

def tier_for(score):
    if score >= FIRE_AT:  return "fire"
    if score >= TODAY_AT: return "today"
    return "radar"


def days_between(today, target):
    try:
        t0 = datetime.strptime(today, "%Y-%m-%d").date()
        t1 = datetime.strptime(target, "%Y-%m-%d").date()
        return (t1 - t0).days
    except (TypeError, ValueError):
        return None


def score_item(item, today):
    pickable, why_not = eligibility(item)
    if not pickable:
        out = dict(item)
        out["tier"] = None
        out["pickability"] = None
        out["pickabilityExcluded"] = {
            "reason": why_not,
            "jiraStatus": item.get("jiraStatus"),
            "model": SCORING_MODEL,
        }
        return out

    release_date = item.get("releaseDate")
    blocking = bool(item.get("blockingSomeone"))

    if release_date:
        days = days_between(today, release_date)
        has_deadline, source = True, "fixVersion"
    elif blocking:
        days = BLOCKED_DEADLINE_DAYS
        has_deadline, source = True, "personWaiting"
    else:
        days, has_deadline, source = None, False, "none"

    cs = item.get("csEscalation") or None

    comp = {
        "deadline": deadline_points(days, has_deadline),
        "priority": priority_points(item.get("priority")),
        "age": age_points(item.get("ageDays")),
        "csEscalation": CS_ESCALATION_POINTS if cs else 0,
    }
    total = sum(comp.values())

    out = dict(item)
    out["tier"] = tier_for(total)
    out["pickability"] = {
        "score": total,
        "tier": out["tier"],
        "model": SCORING_MODEL,
        "components": comp,
        "deadline": {
            "source": source,
            "daysAway": days,
            "fixVersion": item.get("fixVersion"),
            "releaseDate": release_date,
        },
        "csEscalation": cs,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items", help="path to JSON array, or - for stdin")
    ap.add_argument("--today", required=True, help="YYYY-MM-DD in the user's local timezone")
    ap.add_argument("--explain", action="store_true", help="print a readable table to stderr")
    a = ap.parse_args()

    raw = sys.stdin.read() if a.items == "-" else open(a.items).read()
    items = json.loads(raw)
    if isinstance(items, dict):
        items = items.get("items", [])

    processed = [score_item(i, a.today) for i in items]
    # scored items first by score desc; excluded items after, oldest first so the
    # most-stale thing needing a nudge leads that group
    ranked = sorted((p for p in processed if p["pickability"]),
                    key=lambda x: -x["pickability"]["score"])
    excluded = sorted((p for p in processed if not p["pickability"]),
                      key=lambda x: -(x.get("ageDays") or 0))
    scored = ranked + excluded

    if a.explain:
        w = f"{'itemId':<30}{'dl':>5}{'pri':>5}{'age':>5}{'cs':>5}{'TOT':>6}{'tier':>8}  note"
        print(w, file=sys.stderr)
        print("-" * (len(w) + 20), file=sys.stderr)
        for s in ranked:
            p, c, d = s["pickability"], s["pickability"]["components"], s["pickability"]["deadline"]
            dl = "unscheduled" if d["source"] == "none" else f"{d['daysAway']}d ({d['source']})"
            print(f"{s.get('itemId',''):<30}{c['deadline']:>5}{c['priority']:>5}{c['age']:>5}"
                  f"{c['csEscalation']:>5}{p['score']:>6}{p['tier']:>8}  {dl}", file=sys.stderr)
        if excluded:
            print(f"\n  not pickable (not To Do / In Progress) — listed, unranked:", file=sys.stderr)
            for s in excluded:
                print(f"    {s.get('itemId',''):<28} {s.get('jiraStatus','')}"
                      f"  ({s.get('ageDays', 0)}d)", file=sys.stderr)

    json.dump(scored, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
