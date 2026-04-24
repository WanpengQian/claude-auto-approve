#!/usr/bin/env bash
# Run this on a new machine to set up Claude Code hooks.
# Usage: bash .claude/setup_claude.sh

set -e

HOOK_DIR="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Install hook script
mkdir -p "$HOOK_DIR"
cp "$SCRIPT_DIR/hooks/auto_approve.py" "$HOOK_DIR/auto_approve.py"
echo "✓ Hook installed: $HOOK_DIR/auto_approve.py"

# 2. Patch ~/.claude/settings.json — add hooks block if not present
if [ ! -f "$SETTINGS" ]; then
    echo '{}' > "$SETTINGS"
fi

PYTHONIOENCODING=utf-8 python3 - "$SETTINGS" <<'EOF'
import json, sys

path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)

hook_entry = {
    "type": "command",
    "command": "python3 ~/.claude/hooks/auto_approve.py",
    "timeout": 5
}
hooks_block = {
    "PreToolUse": [
        {"matcher": "Bash", "hooks": [hook_entry]}
    ]
}

existing = cfg.setdefault("hooks", {})
pre = existing.setdefault("PreToolUse", [])

# Check if already configured
for rule in pre:
    for h in rule.get("hooks", []):
        if "auto_approve" in h.get("command", ""):
            print("✓ Hook already in settings.json — skipped")
            sys.exit(0)

pre.append({"matcher": "Bash", "hooks": [hook_entry]})

with open(path, "w", encoding='utf-8') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
print(f"✓ Hook added to {path}")
EOF

echo ""
echo "Done. Restart VS Code / Claude Code to apply."