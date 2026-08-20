#!/usr/bin/env python3
"""Read/write daily_briefs in Atlas without the local MCP.

The daily-brief-store MCP server runs on Mohit's laptop, so cloud routines
cannot use it even though the database itself is Atlas. This talks to Atlas
directly instead.

Connection string comes from MONGODB_URI in the environment. It is never
logged, never echoed, and never written to disk - errors print the failure
class only, since a pymongo exception will happily include the full URI
(password and all) in its message.

Usage:
    python scripts/brief_store.py get    --date 2026-08-20 --type am
    python scripts/brief_store.py recent --days 7
    python scripts/brief_store.py upsert --file brief.json
    python scripts/brief_store.py ping
"""
import argparse
import json
import os
import sys

DB = "asato_assistant"
COLL = "daily_briefs"


def die(msg, code=1):
    print(f"brief_store: {msg}", file=sys.stderr)
    sys.exit(code)


def client():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        die("MONGODB_URI is not set in the environment. Add it as a secret on "
            "the routine's environment; do not pass it on the command line.")
    try:
        from pymongo import MongoClient
    except ImportError:
        die("pymongo not installed. Run: pip install --quiet pymongo")
    try:
        c = MongoClient(uri, serverSelectionTimeoutMS=15000, appname="daily-briefs-routine")
        c.admin.command("ping")
        return c
    except Exception as e:
        # Deliberately not printing the exception text - pymongo embeds the URI.
        die(f"could not connect to Atlas ({type(e).__name__}). Check MONGODB_URI "
            f"and that the cluster's network access allows this runner.")


def coll():
    return client()[DB][COLL]


def cmd_ping(_):
    coll().estimated_document_count()
    print("ok: connected, collection reachable")


def cmd_get(a):
    q = {"date": a.date, "type": a.type}
    if a.user:
        q["userId"] = a.user
    doc = coll().find_one(q, {"_id": 0})
    if not doc:
        print("null")
        sys.exit(3)          # distinct code: reachable, but nothing stored
    print(json.dumps(doc, indent=1, default=str))


def cmd_recent(a):
    cur = coll().find({}, {"_id": 0}).sort("date", -1).limit(a.days * 2)
    docs = list(cur)
    if a.type:
        docs = [d for d in docs if d.get("type") == a.type]
    print(json.dumps(docs, indent=1, default=str))


def cmd_upsert(a):
    try:
        doc = json.load(open(a.file))
    except Exception as e:
        die(f"could not read {a.file}: {e}")
    for k in ("date", "type", "userId"):
        if not doc.get(k):
            die(f"document is missing required key '{k}' - refusing to write a "
                f"record that cannot be looked up again")
    if doc["type"] not in ("am", "pm"):
        die(f"type must be 'am' or 'pm', got {doc['type']!r}")
    key = {"date": doc["date"], "type": doc["type"], "userId": doc["userId"]}
    res = coll().replace_one(key, doc, upsert=True)
    what = "inserted" if res.upserted_id else ("replaced" if res.modified_count else "unchanged")
    print(f"ok: {what} {doc['type']} {doc['date']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping").set_defaults(fn=cmd_ping)

    g = sub.add_parser("get"); g.set_defaults(fn=cmd_get)
    g.add_argument("--date", required=True)
    g.add_argument("--type", required=True, choices=["am", "pm"])
    g.add_argument("--user")

    r = sub.add_parser("recent"); r.set_defaults(fn=cmd_recent)
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--type", choices=["am", "pm"])

    u = sub.add_parser("upsert"); u.set_defaults(fn=cmd_upsert)
    u.add_argument("--file", required=True)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
