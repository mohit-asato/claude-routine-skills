# claude-routine-skills

Skills cloned by Claude Code cloud routines (migrated from Cowork scheduled tasks).

- `skills/am-report` — morning sync (Jira/GitHub/Slack → MongoDB `daily_briefs` type:"am" → Slack DM → dashboard artifact)
- `skills/pm-report` — evening wrap-up (type:"pm")
- `skills/weekly-report` — Friday synthesis from the week's briefs + Slack

## MongoDB access

`daily_briefs` lives in Atlas (`asato_assistant.daily_briefs`).

- **Desktop / Cowork runs** use the `daily-brief-store` MCP server, which runs
  locally. Preferred when available — no network allowance needed.
- **Cloud routines** cannot see that server (local process, even though the DB
  is cloud), so they use `scripts/brief_store.py`, which connects to Atlas
  directly with pymongo.

`brief_store.py` reads `MONGODB_URI` from the environment. Set it as a secret on
the routine's environment. Never commit it, never pass it as an argument, never
echo it — pymongo puts the full URI in its exception messages, which is why the
script prints only the exception class on connection failure.

The Atlas user behind that URI should be scoped to `asato_assistant` with
`readWrite` and nothing more.
