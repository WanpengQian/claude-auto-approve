#!/usr/bin/env python3
"""
Claude Code PreToolUse hook — auto-approves common safe Bash commands.
Quote-aware pipeline parsing fixes the bug in Claude Code's built-in allowlist
where pipes inside quoted strings are incorrectly split.

Location: ~/.claude/hooks/auto_approve.py
"""
import json, re, sys

# ── Pipeline splitting ─────────────────────────────────────────────────────────

def split_pipeline(cmd: str) -> list:
    """Split command by |, &&, ||, ; — respecting single and double quotes."""
    parts, cur, sq, dq, i = [], [], False, False, 0
    while i < len(cmd):
        c = cmd[i]
        if   c == "'" and not dq: sq = not sq
        elif c == '"' and not sq: dq = not dq
        elif not sq and not dq:
            two = cmd[i:i+2]
            if two in ('&&', '||'):
                parts.append(''.join(cur).strip()); cur = []; i += 2; continue
            elif c in ('|', ';'):
                parts.append(''.join(cur).strip()); cur = []; i += 1; continue
        cur.append(c); i += 1
    if s := ''.join(cur).strip(): parts.append(s)
    return [p for p in parts if p]

def base_cmd(stage: str) -> str:
    """Return the base command name, skipping env-var assignments."""
    for tok in stage.split():
        if re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tok): continue
        return re.split(r'[/\\]', tok)[-1].lower()
    return ''

# ── Safety rules ───────────────────────────────────────────────────────────────

# Never auto-approve these patterns regardless of command.
BLOCK_PATTERNS = [
    r'\brm\s+.*-[^\s]*f',          # rm -rf / rm -f
    r'\bdd\b.*of=',                 # dd writing to device
    r':\s*\(\)\s*\{.*:\s*\|',      # fork bomb
    r'(curl|wget)\s+.*\|\s*(ba)?sh', # curl|sh
    r'\bsudo\b',                    # privilege escalation
    r'\bchmod\s+[0-7]*7[0-7][0-7]', # chmod 777 / 777x
    r'\bmkfs\b',                    # format filesystem
]

# Git subcommands that are purely read-only.
GIT_READ = {
    'status', 'log', 'diff', 'show', 'branch', 'tag', 'remote',
    'ls-files', 'ls-remote', 'config', 'rev-parse', 'describe',
    'stash', 'reflog', 'shortlog', 'cat-file', 'for-each-ref',
    'worktree', 'blame', 'check-ignore', 'merge-base', 'name-rev',
    'symbolic-ref', 'fetch', 'submodule', 'archive',
}

# Git subcommands that modify state — keep prompted.
GIT_WRITE = {
    'add', 'commit', 'push', 'pull', 'merge', 'rebase', 'reset',
    'checkout', 'switch', 'restore', 'cherry-pick', 'revert',
    'rm', 'mv', 'clean', 'apply', 'am', 'bisect', 'init', 'clone',
}

# ── Per-command checkers ───────────────────────────────────────────────────────

def git_safe(stage: str) -> bool:
    tokens = stage.split()
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t == '-C' and i + 1 < len(tokens): i += 2; continue
        if t.startswith('-') and t != '--': i += 1; continue
        break
    if i >= len(tokens): return True
    sub = tokens[i].lower()
    if sub in GIT_READ:  return True
    if sub in GIT_WRITE: return False
    return False  # unknown subcommand — prompt

def pio_safe(stage: str) -> bool:
    # Allow compile; block upload/erase/fuses.
    if re.search(r'--target\s+(upload|fuses|erase|program)', stage): return False
    if re.search(r'-t\s+(upload|erase)', stage): return False
    tokens = stage.split()
    # find pio/platformio token then check subcommand
    for i, t in enumerate(tokens):
        bn = re.split(r'[/\\]', t)[-1].lower()
        if bn in ('pio', 'pio.exe', 'platformio', 'platformio.exe'):
            if i + 1 < len(tokens):
                sub = tokens[i + 1].lower()
                if sub.startswith('-'): return True   # e.g. pio --version
                return sub in {'run', 'check', 'test', 'debug', 'device',
                                'boards', 'lib', 'platform', 'update', 'upgrade'}
            return True
    return True

def dotnet_safe(stage: str) -> bool:
    tokens = stage.split()
    if len(tokens) < 2: return True
    sub = tokens[1].lower()
    return sub in {
        'build', 'publish', 'restore', 'list', 'run',
        '--version', '-h', '--help', 'nuget', 'tool', 'test',
        'format', 'clean', 'pack',
    }

def gh_safe(stage: str) -> bool:
    MUTATE = {'create', 'close', 'merge', 'delete', 'edit',
              'approve', 'push', 'sync', 'deploy'}
    tokens = stage.split()
    if len(tokens) < 2: return True
    sub = tokens[1].lower()
    # gh api is fine for GET; block POST/PATCH/DELETE
    if sub == 'api':
        return not re.search(r'-[Xx]\s*(POST|PATCH|DELETE|PUT)', stage, re.I)
    if len(tokens) >= 3 and tokens[2].lower() in MUTATE: return False
    return sub in {'pr', 'issue', 'run', 'workflow', 'repo',
                   'release', 'auth', 'gist', 'search', 'status'}

def esptool_safe(stage: str) -> bool:
    # Read operations only
    READ_OPS = {'read_flash', 'flash_id', 'chip_id', 'read_mac',
                'read_mem', 'version', 'get_default_loader'}
    for op in READ_OPS:
        if op in stage: return True
    # write_flash and erase_* are NOT safe
    return False

# ── Main stage checker ─────────────────────────────────────────────────────────

def stage_safe(stage: str) -> bool:
    if not stage: return True

    # Block dangerous patterns first.
    for pat in BLOCK_PATTERNS:
        if re.search(pat, stage, re.IGNORECASE): return False

    tok = base_cmd(stage)
    if not tok: return True

    # Dispatch to specialised checkers.
    if tok == 'git':          return git_safe(stage)
    if tok in ('pio', 'pio.exe', 'platformio', 'platformio.exe'):
                              return pio_safe(stage)
    if tok == 'dotnet':       return dotnet_safe(stage)
    if tok == 'gh':           return gh_safe(stage)
    if tok in ('esptool', 'esptool.py', 'esptool.exe'):
                              return esptool_safe(stage)

    # Allow common read / info / build commands.
    ALWAYS_OK = {
        # Navigation
        'ls', 'dir', 'cd', 'pwd', 'echo', 'which', 'where',
        # File reading (already auto-allowed, but needed inside &&-chains)
        'cat', 'head', 'tail', 'wc', 'file', 'stat',
        # Search
        'grep', 'rg', 'find', 'fd', 'ack', 'ag',
        # Text processing
        'sort', 'uniq', 'awk', 'diff', 'cmp', 'comm',
        # sed: only read-only (-n, no -i)
        # (handled below)
        # System info
        'ps', 'df', 'du', 'uname', 'hostname', 'date',
        'uptime', 'env', 'printenv', 'whoami', 'id',
        'ifconfig', 'ipconfig', 'netstat',
        # Archives (inspect)
        'tar', 'unzip', 'zip',
        # JSON/YAML
        'jq', 'yq',
        # C# / Node tools
        'node', 'npm', 'npx',
        # Python version / import checks (exact; NOT arbitrary -c)
        # (handled below)
        # Misc
        'curl', 'wget', 'ping', 'tasklist',
        'xxd', 'hexdump', 'strings',
        'make', 'cmake', 'ninja',
        'idf.py',
        # Windows
        'where.exe', 'cmd.exe',
    }

    if tok == 'sed':
        # sed -i modifies files — keep prompted.
        if re.search(r'\s-[^\s]*i', stage): return False
        return True

    if tok in ('python3', 'python', 'python.exe'):
        # Allow --version and -c 'import X; print(...)' type checks,
        # but NOT arbitrary -c execution or piped scripts.
        if re.search(r'--version|-V\b', stage): return True
        if re.search(r'-c\s+["\']import\s+\w', stage): return True
        # Disallow arbitrary script execution
        return False

    if tok in ('node', 'node.exe'):
        if re.search(r'--version|-v\b', stage): return True
        # Disallow arbitrary -e scripts
        if re.search(r'\s+-e\s+', stage): return False
        return True

    if tok in ('npm', 'npx'):
        # Read-only npm commands
        if re.search(r'\s+(ls|list|info|view|search|audit|outdated|version)\b', stage):
            return True
        # npx lv_font_conv and similar build tools
        if 'lv_font_conv' in stage or 'font_conv' in stage: return True
        return False

    if tok in ('make', 'cmake', 'ninja', 'idf.py'):
        # Compile is fine; clean or dangerous targets are not.
        if re.search(r'\b(distclean|mrproper|erase)\b', stage): return False
        return True

    if tok in ('cmd.exe', 'cmd'):
        # Only allow safe /c "where ..." style
        if re.search(r'/c\s+"?where\s+', stage, re.I): return True
        return False

    if tok == 'tasklist': return True
    if tok == 'taskkill':
        # Allow /PID or /IM for specific processes — keep prompted for safety
        return False

    return tok in ALWAYS_OK

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # parse error → pass through

    tool_name = data.get('tool_name', '') or data.get('hook_event_name', '')

    # Only handle Bash tool.
    if tool_name != 'Bash':
        sys.exit(0)

    cmd = (data.get('tool_input') or {}).get('command', '')
    if not cmd:
        sys.exit(0)

    stages = split_pipeline(cmd)
    if stages and all(stage_safe(s) for s in stages):
        print(json.dumps({'decision': 'approve'}))
    # else: output nothing → normal permission flow (user sees prompt)

if __name__ == '__main__':
    main()
