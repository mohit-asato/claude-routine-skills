---
name: am-report
description: Generate Mohit's morning ("AM") work sync — pulls open work from Jira, GitHub, and Slack, scores and tiers it by urgency, writes the result as a structured JSON document into the user's MongoDB store (type:"am" in the daily_briefs collection), sends a short gist of it to the user's own Slack DM, and republishes the "daily-ops-dashboard" artifact with the day's plan. Use this whenever the user asks for their "morning sync," "AM report," "daily brief," "what do I need to do today," or invokes this on a schedule (e.g. a Cowork scheduled task firing each weekday morning). Also trigger if the user asks to "catch me up on Jira/GitHub/Slack" first thing in the day, or asks what's on fire / what's pending / what's overdue across their tools. Do not use this for the evening/PM counterpart — that is a separate report covering what got done, not what's outstanding.
---

# AM Report

This skill produces one thing every weekday morning: an honest, prioritized picture of
everything sitting on the user's desk across Jira, GitHub, and Slack — written to
MongoDB as a structured record, and summarized in one Slack message so the user
doesn't have to open a dashboard to know what matters today.

The user built this because they're a senior engineer with ADHD and memory issues.
The point isn't to produce a report that *looks* thorough — it's to produce
something that actually reduces the cost of figuring out "what do I do right now."
Every design choice below exists to serve that: real links (not vague references),
short reasons instead of walls of text, and tiers that reflect genuine urgency
rather than an evenly-padded list.

## Step 1 — Gather from every connected source

Pull data from whichever of these are connected. If a source has genuinely nothing
relevant, leave it out entirely rather than writing a filler line about it (e.g.
never write something like "no meeting notes found" — silence is fine, a
manufactured absence-note is not).

**Jira** (via the Atlassian MCP tools): find the user's open work. A good starting
query is JQL like `assignee = currentUser() AND resolution = Unresolved ORDER BY
priority DESC, updated ASC` — this surfaces stale-and-important items first. Pull
`summary`, `status`, `priority`, `updated`, `created`, `duedate`, `fixVersions` for
each. Compute `ageDays` from whichever timestamp best represents "how long has this
sat without real progress" — usually `updated` for in-progress work, `created` for
things that were never picked up.

Check `fixVersions` specifically: if it's empty on a ticket that's otherwise real,
active work (not a brand-new, unrefined backlog item), that's worth flagging on
its own — a ticket with no fix version is a ticket that can silently miss a
release with nobody noticing. Add `"missingFixVersion"` to that item's `flags`
array (see Step 4) so the report actually surfaces "hey, go add a fix version to
this" rather than letting it slide.

Also pull the **comments** on each ticket, not just the field metadata. The fields
tell you the ticket's official state; the comments tell you what's actually going
on — a ticket sitting in "In Progress" for a week might have a comment from
yesterday saying it's blocked on someone else, or nearly done, or that the
original ask changed. That context is often the difference between a fair
`reasonAdded` and a misleading one, so read the comments before writing the
tiering decision, not just the status field.

**GitHub**: search for PRs authored by the user that are still open and waiting on
review (`is:pr author:<user> is:open`), and check for review requests the user
hasn't acted on. A PR that's been waiting weeks on someone else's review is a real
"nudge them" item, not a "you're behind" item — the reasoning you write should make
that distinction, since the user shouldn't feel responsible for someone else's
delay.

**Slack**: search recent messages (roughly the last 3-5 days) for genuine
commitments — phrases like "will do," "on it," "today," "ASAP," or a direct
promise made to a named person. These matter because the user's own words are the
most reliable due-date signal there is: if they told someone "I'll ship this
today" three days ago, that's now overdue in a way the ticket tracker doesn't
show. Also check if the user has a personal automation/bot posting daily
recaps into a DM (some setups have one) — if so, it's often a rich, already-
synthesized source worth reading rather than duplicating.

Be careful about over-reading Slack messages. A single ambiguous line out of
context is easy to misclassify — "looks crazy to me" from a teammate could mean
"this is broken" or it could mean "this is an impressive POC demo," and those two
readings should produce completely different items. Read enough of the
surrounding thread (not just the one line) to tell which it is. If after doing
that you're still genuinely not sure whether something is a real problem, a
commitment, or just chatter, don't guess and don't default to the scarier
reading — surface it honestly as an "unsure, worth a look" item instead of
labeling it a bug/blocker/promise you can't actually back up. Something like
`reasonAdded: "Shantanu said this 'looks crazy to him' in #eng — not clear if
that's a bug report or him being impressed by a POC, worth a quick check"` is far
more useful than confidently mislabeling it. Only tier something as a real fire
or commitment when the evidence actually supports it.

If the `daily-brief-store` connector is available (see Step 5), also read back
the **last several days of `daily_briefs` documents** (both `type:"am"` and
`type:"pm"`),
not just yesterday's — this is the skill's actual memory, and it's what lets it
notice patterns a single day's snapshot can't. Specifically look for:

- **The same item showing up "pending"/"untouched" across multiple consecutive
  reports** — one repeat isn't a pattern, but three or four mornings in a row
  with no real movement on the same ticket is. That's not just an aging item
  anymore, it's a stalling pattern worth naming directly.
- **A Slack commitment ("will do today," "by EOD," "tomorrow morning") that
  reappears report after report without ever resolving** — i.e. the same kind
  of promise gets remade because the last one quietly expired. That's the
  "false promise" pattern the user specifically wants surfaced: not to shame
  them, but because noticing it themselves in the moment is exactly what ADHD
  makes hard, and that's the whole reason this memory layer exists.

When you spot this, don't just fold it into the ordinary `reasonAdded` — say it
plainly, e.g. `reasonAdded: "Third morning in a row this has been 'today's
priority' with no actual movement — worth asking why it keeps slipping rather
than re-committing again"`. Skip this gracefully if the history isn't available
or there isn't enough of it yet; it's an enhancement, not a requirement, and a
single day of data isn't enough to call something a pattern.

## Step 2 — Score pickability

Nobody with ADHD needs a list where the 40th item looks as urgent as the 1st. But
"how urgent is this" is not a vibe — the user has a specific model of what makes a
task worth picking up, and the ordering has to follow it rather than whatever feels
important while reading.

**Do not compute the score in your head.** Extract the inputs, then run the
bundled script — arithmetic done by hand drifts between runs, and the whole point
is that today's ordering is comparable to yesterday's.

### Only pickable work gets scored

Pickability answers "should I pick this up now," so it only applies to work the
user can actually pick up:

- **Jira status `To Do` or `In Progress`** — scored and ranked.
- **Non-Jira items** (a review someone's blocked on, an unanswered direct ask) —
  no Jira status, but obviously actionable, so also scored.
- **Everything else — `Testing`, `Dev Complete`, `Backlog`, `Req Analysis`,
  `Closed` — is not scored.** It's either waiting on somebody else or not ready to
  start.

Pass `jiraStatus` on every Jira item and the script enforces this. Excluded items
come back with `pickability: null` plus a `pickabilityExcluded` reason, sorted
after every scored item, oldest first.

**Excluded does not mean deleted.** A ticket parked in Testing for three weeks or
sat at Dev Complete since May still belongs in the report — that's exactly the kind
of thing that rots invisibly. It just doesn't compete for the top of the list,
because the action there is *chase someone*, not *do the work*. Say which in the
`reasonAdded`: "waiting on QA, worth a nudge" reads very differently from "pick
this up today," and conflating them is what made the old ordering useless.

### The model, in precedence order

1. **Deadline proximity — heaviest factor (max 50 pts).** Primarily: how close is
   the release this ticket is scheduled into. Read `fixVersions[].releaseDate` in
   Jira. A ticket shipping today, or one whose release date has already passed
   while it's still open, is the most pickable thing on the board.
2. **Jira priority (max 30 pts).** Highest > High > Medium > Low > Lowest.
3. **Age without real movement (max 20 pts).** Capped deliberately, so a
   three-month-old Low can never outrank a fresh Highest.
4. **Customer-success escalation — hard override (+100 pts).** See below. This
   deliberately exceeds the 100-point ceiling of the other three combined, so a
   genuine CS escalation outranks *everything*, including a ticket shipping today.

### Inputs to extract per item

Build a JSON array with one object per item and hand it to the script:

```jsonc
[
  {
    "itemId": "as-7854",
    "jiraStatus": "To Do",          // REQUIRED on Jira items — gates eligibility
    "priority": "Highest",          // exact Jira priority name, or "n/a"
    "ageDays": 7,                   // days without real movement
    "fixVersion": "release-08-18-2026",
    "releaseDate": "2026-08-18",    // from the fix version; null if unset
    "blockingSomeone": false,       // see "items with no fix version" below
    "csEscalation": null            // or the object described below
  }
]
```

Then:

```bash
python scripts/score_pickability.py items.json --today 2026-08-18 --explain
```

`--today` is the user's **local** (Asia/Kolkata) date — not UTC, and not Jira's
Pacific-time day. Getting this wrong shifts every deadline calculation by a day;
see the timezone note in Step 1.

The script returns the same array sorted by score descending, each item carrying a
`pickability` block and a `tier`. Use that order and those tiers directly. Don't
re-sort by feel afterwards.

### Items with no fix version

Two distinct cases, and conflating them is the main way this model goes wrong:

- **A Jira ticket with no fix version set.** It gets the unscheduled baseline
  (8 pts) and earns the `missingFixVersion` flag. Unscheduled means undated, not
  unimportant — but it genuinely can't compete with a dated release, which is what
  the user asked for.
- **A non-Jira item where a named person is actively waiting** — a review ask, an
  unanswered direct question, a PR someone needs looked at. Set
  `"blockingSomeone": true`. The script treats a waiting person as a two-day
  deadline, because that's exactly what it is. Without this, a teammate blocked on
  a review scores below a three-month-old backlog ticket, which is the opposite of
  pickable.

Only set `blockingSomeone` when a *specific named person* is genuinely held up. A
general FYI mention, a channel broadcast, or an item the user merely feels bad
about does not qualify.

### The customer-success wildcard

This is the one input that can override the release date, and it exists because
customer success sometimes needs a fix in **dev or staging** long before any
production release is scheduled — a situation the release-date signal cannot see.

Set `csEscalation` only when **both** hold:

- the comment is authored by someone on the customer-success / support side (not a
  developer, not a PM, not the user themselves), and
- they are asking for this urgently — "we need this today," "customer is blocked,"
  "needed on staging for a demo," a named customer waiting.

```jsonc
"csEscalation": {
  "author": "Priya Nair",
  "role": "Customer Success",
  "quote": "we need this on staging today, customer demo tomorrow",
  "date": "2026-08-18",
  "environment": "staging"
}
```

Guardrails, because this override is powerful enough to be worth abusing:

- **A customer reporting a bug is not an escalation.** A bug report is a bug
  report; an escalation is CS saying they need the fix, urgently, somewhere.
- **A developer calling something urgent is not an escalation.** Role matters.
- **Check whether it's stale.** If the escalation comment is weeks old and the
  thread shows it was since answered, resolved, or descoped, don't keep firing it
  every morning — note in `reasonAdded` that it looks resolved and leave
  `csEscalation` null. A permanently-escalated item makes the override meaningless.
- Always carry the quote, author and date. An escalation you can't evidence is an
  escalation you shouldn't have scored.

### After scoring

Tier boundaries are applied by the script (`fire` ≥ 70, `today` ≥ 45, else
`radar`), so tiers now mean something specific and comparable across days rather
than being a fresh judgement each morning.

Two things still need judgement after the script runs:

- **Grouping.** When several tickets are clearly one underlying issue (duplicate
  bug reports, a cluster of related sub-tasks), collapse them into one item with
  the others as `relatedRefs` **before** scoring, so one problem occupies one slot
  rather than three.
- **Stalling context.** The multi-day history read in Step 1 doesn't change the
  score — deliberately, since the user's model is release/priority/age — but it
  absolutely belongs in `reasonAdded`. "Fourth morning running this has been
  today's priority with no movement" is exactly the sentence that makes a
  mid-ranked item finally get picked up.

Drop a tier from the output entirely if nothing qualifies for it — never pad it
with a placeholder line.

## Step 3 — Write titles that are quirky AND informative

This is a deliberate style choice the user asked for directly: every item gets a
short, fun, memorable title instead of a raw ticket ID — "The Everyone's Waiting UI
Ticket" instead of "AS-7854." Uncensored/cheeky language is fine and encouraged;
match the user's own tone rather than playing it safe and corporate.

But a joke name alone loses information. Every item also needs a one-line
`ticketGist` in plain language describing what the ticket is actually about — e.g.
title "The Survey Job That Ghosts You", gist "usage-survey send job hangs instead
of failing cleanly." The title hooks attention; the gist tells you what it is. Both
are required for every item — a title without a gist forces the user to click
through just to remember what the thing even is, which defeats the entire purpose
of a memory aid.

Every item must carry its real source link (Jira issue URL, GitHub PR URL) — never
a bare ticket ID with no way to jump to it.

## Step 4 — Assemble the JSON document

Build one JSON object matching this shape (this is the `daily_briefs` collection
schema, `type: "am"`):

```json
{
  "date": "YYYY-MM-DD",
  "type": "am",
  "userId": "<user's email>",
  "timezone": "<user's IANA timezone>",
  "generatedAt": "<ISO 8601 timestamp, now>",
  "scoringModel": "pickability-v1",
  "headline": "<one sentence, conversational, names the real shape of the day>",
  "items": [
    {
      "itemId": "<stable slug, e.g. jira key lowercased>",
      "title": "<quirky title>",
      "ticketGist": "<one-line plain description>",
      "source": { "type": "jira|github|slack", "refId": "<e.g. AS-1234>", "url": "<full link>" },
      "relatedRefs": [{ "refId": "...", "url": "..." }],
      "tier": "fire|today|radar",
      "status": "pending",
      "reasonAdded": "<why this made the cut, specific not generic>",
      "ageDays": 0,
      "priority": "<Jira priority or 'n/a'>",
      "jiraStatus": "<Jira status or omit for non-Jira items>",
      "fixVersion": "<e.g. release-08-25-2026, or null if unset>",
      "pickability": {                 // null when not To Do / In Progress
        "score": 87,
        "tier": "fire",
        "model": "pickability-v1",
        "components": { "deadline": 50, "priority": 30, "age": 7, "csEscalation": 0 },
        "deadline": {
          "source": "fixVersion|personWaiting|none",
          "daysAway": 0,
          "fixVersion": "release-08-18-2026",
          "releaseDate": "2026-08-18"
        },
        "csEscalation": null
      },
      "flags": ["missingFixVersion", "stalling"]
    }
  ]
}
```

Items that aren't pickable carry `"pickability": null`, `"tier": null`, and a
`pickabilityExcluded` block instead:

```jsonc
"pickabilityExcluded": {
  "reason": "status 'Dev Complete' is not pickable — waiting on someone else or not ready to start",
  "jiraStatus": "Dev Complete",
  "model": "pickability-v1"
}
```

**`items` must be stored in pickability order — highest score first, then the
unscored ones (oldest first).** The
consumers of this document (the dashboard, tomorrow's report, the weekly rollup)
read the array order as the ranking, so a correctly-scored but wrongly-ordered
array is worse than useless. The script already returns them sorted; keep that
order.

Copy the `pickability` block through from the script's output verbatim rather than
retyping it — it's stored so that the ordering is auditable after the fact. When a
ranking later looks wrong, the components tell you whether it was the deadline
read, the priority, or a bad escalation call, and that's not recoverable if only
the final score was kept. `csEscalation` stays `null` on most items and carries the
full evidence object when set.

`flags` is an optional array, omit it entirely for items that don't trigger any
of it — don't pad it with an empty array-of-nothing note. Two flags currently
apply: `"missingFixVersion"` (an active Jira ticket with no fix version set —
see Step 1) and `"stalling"` (this item, or a promise like it, has repeatedly
failed to resolve across recent daily briefs — see Step 1's memory read). An
item can carry both if it's earned both.

`headline` should read like a person summarizing the day to a friend, not a status
report — "Six quiet days, then Friday dumped a bug pile on your desk" rather than
"3 high priority items require attention." Say what's actually true about the
pattern, not a templated sentence.

## Step 5 — Save to MongoDB

This skill's whole point is that today's report becomes tomorrow's memory. Use
the **`daily-brief-store`** connector specifically for this (tools namespaced
like `mcp__...__daily-brief-store__insert_documents`, `find`, `list_databases`,
`create_database`, `list_collections` — search for these if they're not already
visible). Other generic MongoDB-flavored connectors that might also be
connected are not reliable for this and should not be used here — if
`daily-brief-store` itself isn't available, treat it as the memory layer being
down (see below), don't fall back to a different Mongo connector. The working
database is `asato_assistant`, collection `daily_briefs`.

Before inserting, check the database exists (`list_databases`); if not, create it
with `create_database`. Then insert the document built in Step 4 into
`daily_briefs`. If a document for the same `(userId, date, type: "am")` already
exists (e.g. this is a re-run), prefer updating it over creating a duplicate —
use `find` first to check, then `update_documents` if one exists.

If the `daily-brief-store` connector isn't available or fails, don't let that
block the rest of the skill — tell the user plainly that the save didn't happen
and why, then still proceed to send the Slack gist. A missing memory layer is a
real gap worth flagging, not a reason to also withhold the Slack message the
user actually reads.

## Step 6 — Send the gist to Slack

Send a message to the user's own Slack DM (search for their own user, or use
whatever "send yourself a note" pattern is available) — this is the thing they'll
actually glance at, so keep it short: the headline, then the fire-tier items
only (title + one-line reason + link), maybe a one-line mention of the today-tier
count. Don't paste the entire JSON or every tier — that defeats the purpose of a
quick morning glance. If any items carry the `missingFixVersion` flag, add one
short line naming them so it's an actual nudge, not just a buried JSON field —
this is the one flag worth surfacing even outside the fire tier, since it's a
quick fix if caught early and a real problem if missed until release time.
Something like:

```
Morning sync — <headline>

🔥 Do first:
• <title> — <short reason> <link>
• <title> — <short reason> <link>

+<N> more things on the radar today.
```

Use Slack's mrkdwn link syntax (`<url|title>`) so titles are clickable rather than
pasting raw URLs.

## Step 7 — Republish the Daily Ops dashboard

The Slack gist is the glance; the dashboard is where the user actually sits with
the day. A published artifact can't query Mongo on its own — the platform blocks
outbound calls from artifact pages to anything but registered claude.ai
connectors, and the Mongo store is reached through a desktop-local MCP server.
So the artifact only ever shows what was baked into it the last time it was
published, which is why regenerating it here is part of the run rather than
something the page does for itself.

Run the bundled renderer against the document you just built:

```bash
python scripts/render_dashboard.py --am <am.json> --out dashboard.html \
  --generated "9:00 AM IST"
```

Write the Step 4 JSON to a temp file first and pass its path as `--am`. With no
`--pm` argument the renderer produces morning mode: light palette, a "Do this
first" hero, and every item as an open checkbox. Pass `--generated` a short local
time string — it shows next to the date.

Then publish it over the existing artifact, keeping the same id so the user gets
a new *version* of one artifact rather than a pile of separate ones (their version
history is the day-to-day history, which is why the page itself has no history UI):

Call the **`Artifact`** tool with `file_path` pointing at `dashboard.html` and
`url: "https://claude.ai/code/artifact/3b3f1b7f-cd71-4a6e-a327-ca732419c068"`. Passing that `url` is what makes this a new *version* of the
existing board instead of a brand-new artifact — omit it and you silently fork a
second dashboard every run. Keep `favicon` stable across runs (the tab icon is
how the user finds the page); the document's own `<title>` names it, so there is
no need to pass `title`.

Do **not** use `mcp__remote-devices__update_artifact` — that tool only exists in
the desktop Cowork session and is absent in a cloud routine. The older
`daily-ops-dashboard` desktop artifact is frozen history; this URL is the live one.

If the `Artifact` publish isn't available or fails, say so plainly in one line
and move on. The Mongo record is already safe and the Slack
message already sent, so a stale dashboard is a cosmetic gap, not a lost day. Do
not retry in a loop or hold up the rest of the run for it.

## Dry runs (testing / previewing)

If the invocation explicitly says **DRY_RUN** (e.g. during testing, or when the
user asks to "preview" or "show me without sending"), do everything through
Step 4 normally — pull real data, score it, build the real JSON — but skip the
actual `insert_documents`/`update_documents` call in Step 5, the actual
`slack_send_message` call in Step 6, and the `Artifact` publish in Step 7.
Instead, print the JSON document you would have inserted and the exact Slack
message text you would have sent, clearly labeled as a dry run. Rendering the
dashboard HTML locally during a dry run is fine and often useful — it's only the
publish that's skipped. This lets the skill be tested or previewed without writing
duplicate Mongo documents, spamming the user's Slack DM, or burning an artifact
version. Outside of an explicit DRY_RUN request, always perform the real writes —
a normal invocation's whole point is that the write actually happens.

## Final response — don't yap

Once the MongoDB write and Slack DM are done (or a dry run's preview is printed),
that's the deliverable. Don't follow it with a recap, summary, or explanation of
what you just did in the chat session — the whole point of this skill is that the
Jira/GitHub/Slack sources, the generated JSON, and the Slack DM are the output,
not a chat message. A single short confirmation line (e.g. "Saved and sent.") is
enough; skip restating the headline, the tiers, or the item list back in the
conversation.

## Notes on judgment calls

- If this fires unattended (a scheduled task with nobody watching), don't stop to
  ask clarifying questions — make the most reasonable call (e.g. default JQL
  scope, default Slack DM target) and proceed. State any assumption briefly in
  the Slack message only if it's a real judgment call, not routine operation.
- Never fabricate ticket content, links, or quotes. Every `reasonAdded` and
  `evidenceQuotes`-style claim must trace back to something actually pulled from
  Jira/GitHub/Slack in this run.
- This skill only ever writes `type: "am"` documents. It should never need to read
  or reason about the PM/evening report's fields — that's a separate skill by
  design, so each stays simple and neither breaks if the other's shape changes.
- Naming a stalling or broken-promise pattern is meant to be useful, not a
  gotcha — keep the tone the same honest-friend register as the rest of the
  report, not a scoreboard of failures. The point is to make the pattern visible
  so the user can actually decide to break it, not to make them feel bad about it.
