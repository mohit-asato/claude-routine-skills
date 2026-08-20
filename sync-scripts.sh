#!/usr/bin/env bash
# render_dashboard.py lives in four places: the repo copies the cloud routines
# clone, and the two live copies the desktop Cowork skills run from. They must
# stay byte-identical or the morning and evening boards drift apart.
# Source of truth: skills/am-report/scripts/render_dashboard.py
set -euo pipefail
cd "$(dirname "$0")"
SRC="skills/am-report/scripts/render_dashboard.py"
LIVE="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/3914460d-5953-429a-9eba-2485e363611b/d06e747a-db19-497b-b4b3-4ee1f22849bb/skills"
cp "$SRC" skills/pm-report/scripts/render_dashboard.py
[ -d "$LIVE" ] && { cp "$SRC" "$LIVE/am-report/scripts/render_dashboard.py"
                    cp "$SRC" "$LIVE/pm-report/scripts/render_dashboard.py"; } || echo "live skills dir absent, repo only"
echo "synced from $SRC"
