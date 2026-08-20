---
name: weekly-report
description: Generate Mohit's weekly report — reads back the whole week's am/pm daily_briefs documents from the user's MongoDB store plus the week's Slack conversations, and synthesizes them into a lightweight four-section update (Highlights, Lowlights, Dependencies, Plan for Next Week — three bullets each), written in plain, formal product language with no Jira ticket IDs or engineering jargon, then sends it to Slack. Use this whenever the user asks for their "weekly report," "weekly update," "weekly sync," "friday recap," "week in review," or invokes this on a schedule (e.g. a Cowork scheduled task firing every Friday). Also trigger if the user asks "what should I tell the team this week," "summarize my week," or wants a team-facing update on progress/blockers/next steps. Do not use this for the daily am/pm reports — those are internal, ticket-level, and Jira-ID-friendly; this skill produces the polished, team-facing weekly rollup instead.
---

# Weekly Report

This skill produces one thing every week: a short, honest, team-readable summary of
what happened — written for two audiences at once. The user reads it back to get
clarity on what actually got done and what still needs focus. Their teammates read
it to stay aligned without having to ask "hey, what's going on with your stuff?"

Because it's read by other people, this report is a different register from the
am-report/pm-report daily briefs. Those are for the user alone — ticket-ID-dense,
tiered by urgency, written in their own voice. This one is the polished, product-
friendly version: no Jira IDs, no internal jargon, no "AS-1234" — just plain
language about what the work actually was and where it stands. If a daily brief
says "AS-7854, the survey job that ghosts you," the weekly report says "fixed a
bug where the usage-survey job could hang instead of failing cleanly." Same fact,
translated for someone who doesn't live in the tracker.

## Step 1 — Gather the week's history from MongoDB

Use the **`daily-brief-store`** connector specifically for this (tools
namespaced like `mcp__...__daily-brief-store__find`, `list_databases`,
`list_collections`). Other generic MongoDB-flavored connectors that might also
be connected are not reliable for this and should not be used here — if
`daily-brief-store` itself isn't available, treat this step as unavailable
(see Step 1's fallback below), don't fall back to a different Mongo connector.
The working database is `asato_assistant`, collection `daily_briefs`.

Query for all documents belonging to the user (`userId`) with a `date` falling in
the current week (Monday through the day this runs, typically Friday) — both
`type: "am"` and `type: "pm"` documents. Together these are the week's actual
record: what was flagged as pending each morning, and what genuinely got done or
didn't each evening. Read all of them, not just the most recent day — the whole
point of a weekly report is the arc across the week, not a snapshot of Friday
alone.

If the collection has too little history (e.g. this is the first week the daily
reports have been running, or several days are missing), work with what exists
and don't fabricate the gaps — a week built from three real days of data is more
useful than a week padded with invented ones. If genuinely nothing is available,
say so plainly rather than inventing a report; it's fine to fall back to asking
the user directly what happened this week in that case.

### Cloud routines: briefs live in the `daily-briefs` repo, not Mongo

The `daily-brief-store` MCP server runs on Mohit's laptop, and Atlas itself is
also unreachable from a cloud routine: the sandbox only allows outbound 443, so
port 27017 times out on every cluster node. This was measured, not assumed.

So cloud routines read and write briefs as **files** in the
[`mohit-asato/daily-briefs`](https://github.com/mohit-asato/daily-briefs) repo,
which is attached as a second source and cloned alongside this one. One file per
brief: `briefs/<YYYY-MM-DD>-<am|pm|weekly>.json`.

```bash
cd ../daily-briefs          # sibling checkout; adjust if the runner nests differently
python3 brief_store.py list
python3 brief_store.py recent --days 7            # the memory read in Step 1
python3 brief_store.py get --date <YYYY-MM-DD> --type am
python3 brief_store.py write --file <the document you built>
```

`write` keys on `date` + `type` and replaces, so a re-run corrects the day
instead of duplicating it. It writes atomically, so an interrupted run never
leaves half a brief behind. `get` exits **3** when a brief simply does not exist
yet — that is not an error, do not report it as one.

**A write is not saved until it is committed and pushed:**

```bash
git add briefs/<the file> &&   git -c user.email=routine@asato.ai -c user.name="Report Routine"       commit -m "<type> brief for <date>" &&   git push origin HEAD:main
```

If the push fails, say so plainly in one line and carry on to the Slack step —
the brief is written but unsaved, which is worth flagging and is not a reason to
withhold the message the user actually reads.

Prefer the `daily-brief-store` MCP when its tools **are** present (desktop runs).
Atlas still holds the pre-2026-08-20 history and remains the archive.

## Step 2 — Pull this week's Slack conversations

Dependencies and next-week plans live in conversation, not in tickets — search
Slack for the user's own messages and the threads they're part of over the past
week (roughly the last 5-7 days). Look specifically for:

- **Asks the user made of someone else**, or asks someone made of the user, that
  haven't visibly resolved yet ("can you review this," "waiting on you for X,"
  "I'll get you Y by Friday"). These are the dependencies.
- **Forward-looking language** — mentions of what's coming up, what the user said
  they'd focus on next, planning discussions, sprint/cycle kickoffs. These inform
  the plan for next week.

As with the daily reports, read enough surrounding context to be sure of what a
message actually means before treating it as a dependency or commitment — a
single line pulled out of context is easy to misread. If something is genuinely
ambiguous after reading the thread, it's fine to phrase it softly ("still
confirming with the team whether X is needed") rather than stating it as settled
fact.

## Step 3 — Synthesize into four sections, three bullets each

Keep it lightweight — this is a skim-in-30-seconds document, not a comprehensive
log. For each section, pick the three points that matter most; if there are
genuinely fewer than three real things to say, use fewer rather than padding with
filler ("no significant blockers this week" is fine to say once as the only
bullet in Lowlights if that's the truth — don't invent two more just to hit a
count).

- **Highlights** — real wins, progress, or breakthroughs from the week's am/pm
  history. Something that shipped, a hard problem that got unblocked, meaningful
  forward motion on something that had been stuck.
- **Lowlights** — genuine challenges, blockers, or things that didn't go well.
  This should be as honest as the daily reports are — a week that was rough
  should read as rough, not softened into vague positivity. If the daily history
  shows something stalling repeatedly across the week, that belongs here.
- **Dependencies** — drawn from Step 2's Slack read: things the user is waiting
  on from someone else, or things someone else is waiting on from the user.
  Phrase both directions plainly (e.g. "waiting on design sign-off before this
  can ship" vs. "the team is waiting on my review of the migration plan").
- **Plan for next week** — the user's real priorities and focus areas going
  forward, grounded in what's actually still open (from the am/pm history) and
  what's been discussed in Slack (from Step 2) — not a generic restatement of
  the backlog.

**Write every bullet in plain, formal product language.** No Jira IDs, no ticket
keys, no internal engineering shorthand a teammate outside the immediate team
might not follow. Translate: instead of "AS-4521 moved to Testing," write
"the reporting export fix is in testing now." Instead of "PR #812 merged," write
"shipped the update to the onboarding flow." The daily reports already have the
precise ticket-level record if anyone needs to trace a bullet back to its source
— this report's job is to be readable by someone who has never opened Jira.

## Step 4 — Compose the Slack message

There is no separate JSON schema step here — the deliverable for this skill is
the Slack message itself (unlike am-report/pm-report, which produce a stored
JSON document as their primary output). Format it clearly with the four
sections, three bullets max each, and skip a section header entirely if that
section has nothing genuine to report:

```
Weekly update — <date range, e.g. Mon Aug 11 – Fri Aug 15>

✅ Highlights
• <bullet>
• <bullet>
• <bullet>

⚠️ Lowlights
• <bullet>
• <bullet>

🔗 Dependencies
• <bullet>

📅 Plan for next week
• <bullet>
• <bullet>
• <bullet>
```

Send this to the user's own Slack DM by default — the same "send yourself a
note" pattern the daily reports use — so the user can review and forward it to
their team themselves rather than this skill posting into a team channel
unprompted. If the user has told you (in this conversation or a prior one) that
this should go straight to a specific channel or person instead, send it there
directly. When in doubt about the destination and this is running unattended
(see Notes below), default to the user's own DM — sending team-visible updates
to the wrong channel is a much worse failure mode than the user having to
forward it themselves.

## Step 5 — Save the week's report for future reference (optional but recommended)

In a cloud routine, write it into the `daily-briefs` repo with
`python3 brief_store.py write --file <doc>` (set `type` to `"weekly"`), then
commit and push it as described above. Otherwise, if the `daily-brief-store` connector is available, insert the composed
report as a document in `daily_briefs` with `type: "weekly"`, `date` set to the
last day of the covered week, and a `sections` object mirroring the four bullet
lists sent to Slack. This isn't required for the Slack message to go out, but
it's what lets a future weekly report (or a future daily report) notice a
pattern spanning multiple weeks instead of starting from a blank slate every
Friday. If `daily-brief-store` isn't available or the insert fails, don't let
that block sending the Slack message — the Slack message is the actual
deliverable here. As with Step 1, don't substitute a different Mongo-flavored
connector if `daily-brief-store` is down; just skip the save.

## Final response — don't yap

Once the Slack message is sent (and the optional Mongo save attempted), that's
the deliverable. Don't recap the four sections back in the chat — the user can
read the Slack message directly. A single short confirmation line (e.g. "Sent
the weekly update to your DM.") is enough.

## Notes on judgment calls

- Never fabricate a highlight, blocker, dependency, or plan item. Every bullet
  must trace back to something actually found in the week's am/pm history or
  Slack conversations. If a section is genuinely thin, let it be thin rather
  than inventing content to fill three bullets.
- If this fires unattended (a scheduled Friday task with nobody watching), make
  the most reasonable call on scope (the current Mon-through-today window) and
  destination (the user's own DM, per Step 4) and proceed without stopping to
  ask.
- This skill reads `type: "am"` and `type: "pm"` documents but never modifies
  them — treat the daily reports as a read-only source, the same way pm-report
  treats am-report's output.
