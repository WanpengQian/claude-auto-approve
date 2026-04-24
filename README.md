# claude-auto-approve

Claude Code `PreToolUse` hook that auto-approves common read-only and
build-only Bash commands, so you stop getting prompted for every
`git status`, `pio run`, `grep`, etc.

Quote-aware pipeline parsing — fixes the bug in Claude Code's built-in
allowlist where pipes inside quoted strings are incorrectly split.

## What gets auto-approved

- Read-only git: `status`, `log`, `diff`, `show`, `branch`, `fetch`, …
- PlatformIO builds (`pio run`, `pio check`, …) — blocks `--target upload/erase/fuses`
- `dotnet build/publish/test/…`, read-only `gh` / `gh api` (GET only)
- `npm ls/info/audit`, `node --version`, `npx lv_font_conv`
- `make` / `cmake` / `ninja` / `idf.py` compile (blocks `distclean`, `erase`)
- `esptool` read ops (blocks `write_flash`, `erase_*`)
- Navigation / inspection: `ls`, `cat`, `grep`, `rg`, `find`, `jq`, `xxd`, …
- `python --version` and import-check one-liners (blocks arbitrary `-c`)

Dangerous patterns are blocked regardless of command:
`rm -rf`, `dd of=`, `curl | sh`, `sudo`, `chmod 777`, `mkfs`, fork bombs.

## Install

```bash
git clone https://github.com/WanpengQian/claude-auto-approve.git
bash claude-auto-approve/setup_claude.sh
```

Then restart VS Code / Claude Code.

Installs to `~/.claude/hooks/auto_approve.py` and patches
`~/.claude/settings.json` (user-scope — applies to every project).
Idempotent: re-run after `git pull` to pick up rule updates.

Requires `python3` on `PATH`.

## Uninstall

Delete the `PreToolUse` block from `~/.claude/settings.json` and
`rm ~/.claude/hooks/auto_approve.py`.
