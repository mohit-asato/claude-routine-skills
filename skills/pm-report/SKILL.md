---
name: pm-report
description: Generate Mohit's evening ("PM") wrap-up — looks back across today's Jira, GitHub, and Slack activity to see what actually got done (commits, PRs opened/merged/reviewed, Jira tickets moved, Slack help given), compares it against this morning's pending list, writes it as a structured JSON document into the user's MongoDB store (type:"pm" in daily_briefs), sends a short gist to the user's own Slack DM, and republishes the "daily-ops-dashboard" artifact in evening mode with items checked off. Use this whenever the user asks for their "evening wrap-up," "PM report," "end of day recap," "what did I actually get done today," or invokes this on a schedule (e.g. a Cowork scheduled task firing each weekday evening). Also trigger if the user asks "what did I ship today," "recap my day," or wants to know what's still hanging over from this morning. Do not use this for the morning/AM counterpart — that covers what's outstanding, not what got done.
---

# PM Report

This skill produces one thing every weekday evening: an honest look back at what
the user actually did today across Jira, GitHub, and Slack — written to MongoDB
as a structured record, and summarized in one Slack message so closing the laptop
doesn't feel like the day just evaporates.

The user built this because they're a senior engineer with ADHD and memory
issues, and the AM report already exists to say "here's what's on your plate."
This is the other half: at the end of the day, did any of that actually move? The
point isn't to make the user feel good or bad about the day — it's to produce an
accurate record, because tomorrow's AM report (and future evening reports) rely
on this data to notice when something has been dragging for days. A PM report
that quietly pads a quiet day with vague activity, or hides a genuinely
unproductive day, breaks that memory chain for no reason.

## Step 1 — Gather what actually happened today

Pull data from whichever of these are connected, scoped to today. If a source
shows genuinely nothing, leave it out rather than writing a filler line ("no
commits today" is fine to say once plainly if the day was quiet — see Step 4 on
headline honesty — but don't pad every section with empty-handed notes).

**GitHub**: commits authored by the user today (`author:<user> author-date:today`
or the repo's default branch log), PRs the user opened today, PRs the user got
merged today, and PRs the user reviewed or commented on today. A commit pushed to
a branch is progress even if the PR isn't merged yet — capture it as activity, not
just merged work.

**Jira**: issues the user transitioned (status changes), commented on, or updated
today — via `assignee = currentUser() AND updated >= startOfDay()` or by checking
the changelog/history on the items from this morning's watchlist if available.
Distinguish a real status-moving touch (e.g. To Do → In Progress, or In Progress →
Testing) from a cosmetic edit; the former is what counts as "got done," the latter
is worth noting but shouldn't be presented as if the ticket closed.

Also check `fixVersions` on any ticket touched today: if it's still empty on
active, real work, flag it the same way the AM report does — add
`"missingFixVersion"` to that item's `flags` array (see Step 4) so it's not
silently missed at release time just because the day was otherwise productive.

Also read the **comments** on each touched ticket, not just the changelog. A
status field only tells you a ticket moved — the comments tell you what actually
happened and why, which matters for writing an honest `eveningNote` (e.g. "closed
after QA confirmed the fix" vs. "closed but only because the ask got descoped" are
very different evening notes for the same status change).

**Slack**: messages the user sent today that helped someone else — answering a
question, reviewing someone's code inline, unblocking a teammate, responding to a
direct ask. This matters as much as ticket work: a day spent mostly helping
teammates is still a productive day, and hiding that behind "0 tickets closed"
would misrepresent it.

Be careful about over-reading Slack messages, in either direction. A single
ambiguous line pulled out of a thread is easy to misclassify — a teammate saying
something "looks crazy" could mean they hit a bug, or it could mean they're
impressed by a POC. Read enough of the surrounding thread to tell which before
logging it as an activity or a problem, and if it's still genuinely unclear, log
it as an "unsure, worth a look" note rather than confidently calling it a bug fixed
or a bug found. Don't default to the more dramatic reading just because it makes
for a punchier line.

If yesterday's or this morning's `daily_briefs` document (type:"am" or type:"pm")
is available via the `daily-brief-store` connector, read it to know what was pending going
into today — this is what lets the report say "AS-7854, which was flagged this
morning, actually got moved to Testing" instead of only reporting today's raw
activity in isolation. Skip this gracefully if it's not available; it's an
enhancement, not a requirement, and this skill should treat the other report's
JSON as a read-only reference, never something it modifies.

Go a few days further back than just this morning, too — this is the memory
layer that lets the skill notice patterns, not just today's delta. Look across
the last several `daily_briefs` documents for:

- **The same item marked untouched/pending report after report** — a couple of
  days is normal life, but a ticket that's been "still untouched" three or four
  evenings running has stopped being a scheduling accident and become a real
  stalling pattern worth naming.
- **A commitment made in Slack or a PR comment that keeps getting remade** —
  "will finish tomorrow" showing up again tonight when it also showed up two
  nights ago is a false-promise pattern, not a fresh commitment. Naming this
  honestly is exactly the point of keeping this history at all.

When you see this, say it plainly in the `eveningNote` rather than quietly
recording another "untouched" — e.g. "Still untouched — this is the third
evening in a row this has slipped past a 'today' promise." Skip this
gracefully without enough history; don't invent a pattern out of one or two
data points.

## Step 2 — Reconcile pending vs. done

For each item that was flagged as pending (from this morning's report, or from
Jira items the user owns), work out what actually happened to it today:

- **closed** — genuinely resolved, merged, shipped, or moved to a
  done-equivalent status.
- **progressed** — real forward motion (status changed, a commit landed, a PR
  went up) but not finished.
- **untouched** — still exactly where it was this morning. Say this plainly.
  It's tempting to soften this into "in progress" out of politeness, but an
  accurate untouched-count is the entire value of the report — a tool that only
  ever reports good news stops being trusted.

Also capture activity that wasn't on this morning's radar at all — a Slack fire
that came up mid-day, an unplanned hotfix, a review someone asked for. Real days
rarely go exactly as planned, and this new-and-unplanned work is often the
actual explanation for why a planned item didn't move.

### Re-score what's still open

Anything still `untouched` at end of day is tomorrow's problem, so it gets scored
with the same pickability model the morning report uses — same script, same
weights. Two reasons this can't just be copied from the morning document:

- **The deadline moved closer.** A ticket that was 8 days from its release this
  morning is 7 days out tonight, and next week it's the thing that ships tomorrow.
  Re-scoring is what makes that visible before it's a fire.
- **Inputs changed during the day.** Someone may have set a fix version, bumped
  the priority, or left a customer-success escalation in the comments since
  morning. The evening read is the more current one.

**Only pickable work gets scored.** Same rule as the morning report: Jira status
`To Do` or `In Progress`, plus non-Jira items. Anything in `Testing`,
`Dev Complete`, `Backlog`, `Req Analysis` or `Closed` is not scored — it's waiting
on someone else or not ready to start. Pass `jiraStatus` and the script enforces
it; excluded items come back with `pickability: null` and a `pickabilityExcluded`
reason. They still appear in the report — a ticket rotting in Testing is worth a
nudge — they just don't compete for the top of tomorrow's list.

Build the same input array as the AM skill's Step 2 — `jiraStatus`, `priority`,
`ageDays`, `fixVersion`, `releaseDate`, `blockingSomeone`, `csEscalation` — for the
**still-open items only**, and run:

```bash
python scripts/score_pickability.py open-items.json --today <local date> --explain
```

`--today` is the user's local (Asia/Kolkata) date, not UTC and not Jira's Pacific
day. See the timezone caution in Step 1.

Read the AM skill's Step 2 for the full model if you need it — the precedence is
deadline proximity (max 50) → Jira priority (max 30) → age without movement
(max 20), with a customer-success escalation as a +100 hard override that outranks
everything including a same-day release. The same guardrails apply: a customer
reporting a bug is not an escalation, a developer calling something urgent is not
an escalation, and a weeks-old escalation that's since been answered should not
keep firing.

**Closed and progressed items are not scored.** Pickability answers "should I pick
this up," which is a meaningless question about something already done or already
moving. Leave their `pickability` null and let the evening note carry the story.

## Step 3 — Write the evening note for each item

Give closed and progressed items a short, honest `eveningNote` — one line, plain
language, not a joke title (that's the AM report's style; the PM report is more
of a plain recap than a bit). E.g. "Moved to Testing after the blocker got
cleared" or "Opened the PR, still needs Shantanu's review." For items still
untouched, the note should say so without excuse-making unless there's a genuine
documented reason (blocked on someone else, out sick, a fire pulled you away) —
in which case name the real reason rather than a vague "didn't get to it."

## Step 4 — Assemble the JSON document

Build one JSON object matching this shape (the `daily_briefs` collection schema,
`type: "pm"`):

```json
{
  "date": "YYYY-MM-DD",
  "type": "pm",
  "userId": "<user's email>",
  "timezone": "<user's IANA timezone>",
  "generatedAt": "<ISO 8601 timestamp, now>",
  "scoringModel": "pickability-v1",
  "headline": "<one sentence, conversational, honestly names the shape of the day>",
  "items": [
    {
      "itemId": "<stable slug, e.g. jira key lowercased>",
      "title": "<short plain label, e.g. the Jira key + short summary>",
      "ticketGist": "<one-line plain description of what the ticket/PR is>",
      "source": { "type": "jira|github|slack", "refId": "<e.g. AS-1234>", "url": "<full link>" },
      "relatedRefs": [{ "refId": "...", "url": "..." }],
      "status": "closed|progressed|untouched",
      "eveningNote": "<honest one-line account of what happened or didn't>",
      "ageDays": 0,
      "priority": "<Jira priority or 'n/a'>",
      "jiraStatus": "<Jira status or omit for non-Jira items>",
      "fixVersion": "<e.g. release-08-25-2026, or null if unset>",
      "tier": "fire|today|radar",
      "pickability": {
        "score": 61,
        "tier": "today",
        "model": "pickability-v1",
        "components": { "deadline": 24, "priority": 30, "age": 7, "csEscalation": 0 },
        "deadline": {
          "source": "fixVersion|personWaiting|none",
          "daysAway": 7,
          "fixVersion": "release-08-25-2026",
          "releaseDate": "2026-08-25"
        },
        "csEscalation": null
      },
      "flags": ["missingFixVersion", "stalling"]
    }
  ],
  "activityLog": {
    "commits": [{ "repo": "...", "sha": "...", "message": "...", "url": "..." }],
    "pullRequests": [{ "repo": "...", "number": 0, "title": "...", "action": "opened|merged|reviewed", "url": "..." }],
    "jiraTouches": [{ "key": "...", "change": "...", "url": "..." }],
    "slackHelp": [{ "channel": "...", "summary": "...", "url": "..." }]
  }
}
```

**Item ordering:** still-open items first, in pickability order (highest score
first — the script's output order), then progressed, then closed. Downstream
consumers read the array order as the ranking, so what needs picking up tomorrow
has to sit at the top of the array, not just be correctly scored somewhere in it.

`pickability` and `tier` are only set on `untouched` items that are also pickable
(To Do / In Progress, or non-Jira). Leave them `null` on closed and progressed
items, and on untouched items whose status isn't pickable — those carry a
`pickabilityExcluded` block instead — copy the block through from the script's output
verbatim rather than retyping it, so a ranking that later looks wrong can be
audited back to which component caused it.

`activityLog` can have empty arrays for categories with nothing to report — omit
the whole `items` entries for things that never existed, but keep the
`activityLog` object's shape consistent (empty array, not a missing key) so
downstream code and future reports can rely on the schema.

`headline` should read like an honest recap to a friend, not a performance review
— "Quiet on tickets, but you spent most of the day unblocking Shantanu and
Ujjval" is a completely valid and useful headline. Don't manufacture urgency or
positivity that the data doesn't support.

`flags` is optional per item, omit it for items that don't earn one. The two in
use: `"missingFixVersion"` (an active ticket touched today with no fix version
set) and `"stalling"` (this item, or a promise like it, keeps not resolving
across recent daily briefs — see Step 1's multi-day history read). An item can
carry both.

## Step 5 — Save to MongoDB

Use the **`daily-brief-store`** connector specifically for this (tools
namespaced like `mcp__...__daily-brief-store__insert_documents`, `find`,
`list_databases`, `create_database`, `list_collections`). Other generic
MongoDB-flavored connectors that might also be connected are not reliable for
this and should not be used here — if `daily-brief-store` itself isn't
available, treat it as the memory layer being down (see below), don't fall
back to a different Mongo connector. The working database is
`asato_assistant`, collection `daily_briefs`.

Before inserting, check the database exists (`list_databases`); if not, create it
with `create_database`. Then insert the document built in Step 4 into
`daily_briefs`. If a document for the same `(userId, date, type: "pm")` already
exists (e.g. this is a re-run), prefer updating it over creating a duplicate —
use `find` first to check, then `update_documents` if one exists.

If the `daily-brief-store` connector isn't available or fails, don't let that
block the rest of the skill — tell the user plainly that the save didn't happen
and why, then still proceed to send the Slack gist. A missing memory layer is a
real gap worth flagging, not a reason to also withhold the message the user
actually reads.

## Step 6 — Send the gist to Slack

Send a message to the user's own Slack DM — short and scannable, since this is
the thing they'll actually glance at before closing their laptop. Lead with the
headline, then a quick closed-vs-still-pending count, then the handful of
concrete things that actually happened (commits/PRs/ticket moves/help given), and
finally a plain, non-judgmental note on what's still sitting untouched so
tomorrow morning isn't a surprise. If any items carry `missingFixVersion`, name
them in one short line — it's an easy fix tonight and a real problem if it's
still missing at release time. Something like:

```
Evening wrap — <headline>

✅ Done today (N):
• <item> — <one-line note> <link>

🔧 Moved forward (N):
• <item> — <one-line note> <link>

⏸️ Still untouched (N):
• <item> — <link>

Shipped: <M commits, K PRs, helped J people in Slack — whichever are nonzero>
```

Omit any of the three sections entirely if its count is zero rather than writing
"Done today (0):" — an empty section header is still visual noise the user has to
parse past. Use Slack's mrkdwn link syntax (`<url|title>`) so titles are clickable.

## Step 7 — Republish the Daily Ops dashboard in evening mode

The morning run already published today's plan to the `daily-ops-dashboard`
artifact. This step republishes it as the evening reckoning: same day, same
artifact, now showing what actually happened.

A published artifact can't query Mongo itself — the platform blocks outbound
calls from artifact pages to anything but registered claude.ai connectors, and
the Mongo store is reached through a desktop-local MCP server. So the page only
shows what was baked in at publish time, which is why regenerating it is part of
this run.

Write both this morning's `type:"am"` document (the one you already read in Step 1
for reconciliation) and the `type:"pm"` document you just built to temp files, then:

```bash
python scripts/render_dashboard.py --am <am.json> --pm <pm.json> \
  --out dashboard.html --generated "9:30 PM IST"
```

Passing `--pm` switches the renderer into evening mode: darker palette, closed
items checked off and struck through, progressed items marked with a filled dot,
still-open items left as empty boxes and sorted to the top, a closed/moved/still-open
count row, and an "unplanned" chip on anything that wasn't on the morning list.
That last part is why both files matter — the renderer diffs the two documents by
`itemId` to work out what was unplanned, so passing only the PM document would
silently mislabel every item as planned.

If this morning's AM document genuinely doesn't exist (the morning run never fired),
render with `--pm` alone omitted is not an option — instead pass the PM document as
both `--am` and `--pm`. Everything will read as planned work, which is the honest
default when there was no plan to compare against.

Then publish over the existing artifact, keeping the same id so the user gets a new
*version* rather than a second artifact (their version history is the day-to-day
history, which is why the page has no history UI of its own):

1. `SendUserFile` on `dashboard.html` to get a `file_uuid`.
2. `mcp__remote-devices__update_artifact` with `id: "daily-ops-dashboard"` and
   that `file_uuid`.

If `update_artifact` isn't available or fails — most likely because the user's
desktop app isn't open, which is a real possibility for a scheduled evening run —
say so plainly in one line and move on. The Mongo record is saved and the Slack
message sent, so a stale dashboard is a cosmetic gap, not a lost day. Don't retry
in a loop.

## Dry runs (testing / previewing)

If the invocation explicitly says **DRY_RUN** (e.g. during testing, or when the
user asks to "preview" or "show me without sending"), do everything through
Step 4 normally — pull real data, reconcile it, build the real JSON — but skip
the actual `insert_documents`/`update_documents` call in Step 5, the actual
`slack_send_message` call in Step 6, and the `update_artifact` publish in Step 7.
Instead, print the JSON document you would have inserted and the exact Slack
message text you would have sent, clearly labeled as a dry run. Rendering the
dashboard HTML locally during a dry run is fine and often useful — it's only the
publish that's skipped, so a dry run never burns an artifact version. Outside of
an explicit DRY_RUN request, always perform the real writes — a normal
invocation's whole point is that the write actually happens.

## Final response — don't yap

Once the MongoDB write and Slack DM are done (or a dry run's preview is printed),
that's the deliverable. Don't follow it with a recap, summary, or explanation of
what you just did in the chat session — the sources gathered, the generated JSON,
and the Slack DM are the output, not a chat message. A single short confirmation
line (e.g. "Saved and sent.") is enough; skip restating the headline, the
reconciliation, or the item list back in the conversation.

## Notes on judgment calls

- If this fires unattended (a scheduled task with nobody watching), don't stop to
  ask clarifying questions — make the most reasonable call (e.g. default "today"
  window, default Slack DM target) and proceed.
- Never fabricate commits, PRs, ticket moves, or Slack activity. Every
  `eveningNote` and `activityLog` entry must trace back to something actually
  pulled from Jira/GitHub/Slack in this run. If a day was genuinely quiet — few
  or no commits, no ticket movement — report that plainly rather than padding
  the JSON or the Slack message to look busier than it was. An accurate "not much
  happened today" is far more useful to future-you than a flattering fiction.
- This skill only ever writes `type: "pm"` documents. It may read a same-day
  `type: "am"` document for context (to know what was pending this morning), but
  it should never modify it or reason about fields the AM report doesn't
  actually produce — treat it as a read-only reference, not a shared object.
- Naming a stalling or broken-promise pattern is meant to help, not to shame —
  keep the same honest-friend tone as the rest of the report. The goal is
  making the pattern visible enough that the user can actually choose to break
  it, not scorekeeping past misses.
