#!/usr/bin/env python3
"""Token-waste audit for a Claude Code setup.

Usage: python3 audit.py [PROJECT_DIR] [--no-user]

Scans the project's and the user's Claude Code configuration (instruction files,
rules, agents, skills, settings, MCP config, installed plugins) and prints a
compact report: what loads on every request, how big it is, settings that move
models or effort, and lines matching patterns known to inflate token use on
Claude Fable 5.2. Read-only; stdlib only. Token counts are estimates (chars / 4).
"""
import json
import os
import re
import sys
from pathlib import Path

SELF_DIRS = ("auditing-token-waste", "routing-subagent-models")
MAX_HITS_PER_PATTERN = 8

# (id, regex, impact). Impacts cite Anthropic's Fable 5.2 prompting and cost guides.
PATTERNS = [
    ("ownership", r"owner and (long[- ]term )?maintainer|design is up to you|you own (this|the) (codebase|code)",
     "+70-80% output tokens and unrequested changes on Fable 5.2"),
    ("finish-task", r"finish the (whole|entire) task|do not stop (until|before)|keep going until",
     "+~30% output; keep only if the model stops early"),
    ("recap", r"\brecap\b|summar(y|ize) of (everything|all|what you did)|(start|begin|end) (every|each) (reply|response|message) with",
     "+~20% output; output costs 5x input"),
    ("token-budget", r"budget of [\d,.]+\s*k?\s*tokens|token budget|[\d,]{5,}\s*tokens",
     "a budget shown to the model raised cost with no quality gain"),
    ("delegation", r"\b(always )?(use|spawn|delegate to|launch) (a |the )?(sub-?agents?|agents?)\b|use proactively|delegate (everything|all|every)",
     "invites delegation; Fable 5.2 delegates readily and subagents can dominate cost"),
    ("re-check", r"\b(verify|check|review|test)\w*\b.{0,30}\btwice\b|double[- ]check|triple[- ]check|think step by step|re-?review (all|every)",
     "stale for always-thinking models; repeated work. Name one concrete check instead"),
    ("caution", r"never retry|ask (me )?(before|for (permission|approval) before) (every|each|any)|be extremely careful|always ask (before|for)",
     "piled-up caution: extra round trips that resend the whole context. Use permission settings"),
    ("no-think", r"(don'?t|do not|never) think|without (thinking|reasoning)|skip (the )?(reasoning|thinking)",
     "does not reduce thinking at medium+ effort; lower effort instead"),
    ("cache-breaker", r"\{\{|\$\(|today'?s date|current (date|time)|git status",
     "per-session/per-turn content in the cached prefix breaks prompt caching"),
]
COMPILED = [(pid, re.compile(rx, re.I), why) for pid, rx, why in PATTERNS]


def est(chars):
    return (chars + 3) // 4


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_json(p):
    try:
        return json.loads(read(p) or "null")
    except ValueError:
        return None


def is_self(p):
    return any(part in SELF_DIRS for part in Path(p).parts)


def frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out, key = {}, None
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            out[key] = m.group(2).strip().strip("\"'")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def scan(path, label, hits, always):
    for n, line in enumerate(read(path).splitlines(), 1):
        for pid, rx, why in COMPILED:
            if rx.search(line):
                hits.setdefault(pid, []).append((always, label, n, line.strip()[:100], why))


def rel(p, base):
    try:
        return str(Path(p).relative_to(base))
    except ValueError:
        return str(p).replace(str(Path.home()), "~")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_user = "--no-user" not in sys.argv
    proj = Path(args[0] if args else ".").resolve()
    home = Path.home() / ".claude"
    hits, warnings = {}, []

    print(f"TOKEN AUDIT  project={proj}  user-config={'yes' if use_user else 'no'}")
    print("Estimates: tokens ~= chars/4. Real counts: /context in Claude Code.\n")

    # 1. Instruction files loaded on every request.
    always = [proj / "CLAUDE.md", proj / "CLAUDE.local.md", proj / ".claude" / "CLAUDE.md"]
    always += sorted((proj / ".claude" / "rules").rglob("*.md"))
    always += [d / "CLAUDE.md" for d in proj.parents if d != Path.home()]
    if use_user:
        always += [home / "CLAUDE.md"] + sorted((home / "rules").rglob("*.md"))
    print("Loaded on every request:")
    total = 0
    for p in always:
        if not p.is_file() or is_self(p):
            continue
        text = read(p)
        lines = text.count("\n") + 1
        total += est(len(text))
        flag = "  <- over 200 lines" if lines > 200 else ""
        print(f"  {est(len(text)):>7,}  {rel(p, proj)} ({lines} lines){flag}")
        scan(p, rel(p, proj), hits, True)
    print(f"  {total:>7,}  total instruction files\n")

    # 2. Skills: descriptions are listed every request; bodies load on use.
    def skills_in(root):
        out = []
        for s in sorted(Path(root).rglob("SKILL.md")) if Path(root).is_dir() else []:
            if is_self(s):
                continue
            out.append((s, frontmatter(read(s)).get("description", "")))
        return out

    groups = [("project", skills_in(proj / ".claude" / "skills"))]
    if use_user:
        groups += [("user", skills_in(home / "skills")), ("plugins (installed)", skills_in(home / "plugins"))]
    print("Skill listings (descriptions are sent every request):")
    for name, items in groups:
        chars = sum(len(d) for _, d in items)
        print(f"  {len(items):>5} skills  ~{est(chars):,} tokens  {name}")
        if name == "project":
            for s, _ in items:
                scan(s, rel(s, proj), hits, False)
    print()

    # 3. Agents: model/effort and delegation-inviting descriptions.
    agent_dirs = [proj / ".claude" / "agents"] + ([home / "agents"] if use_user else [])
    agents = [a for d in agent_dirs if d.is_dir() for a in sorted(d.glob("*.md")) if not is_self(a)]
    print(f"Agents: {len(agents)}")
    for a in agents:
        fm = frontmatter(read(a))
        model = fm.get("model", "(inherits main model)")
        effort = fm.get("effort", "(none: non-main models use their default)")
        print(f"  {rel(a, proj)}: model={model} effort={effort}")
        scan(a, rel(a, proj), hits, False)
    print()

    # 4. Settings that move models or effort.
    print("Settings:")
    settings = [proj / ".claude" / "settings.json", proj / ".claude" / "settings.local.json"]
    if use_user:
        settings.append(home / "settings.json")
    enabled_plugins = 0
    env_seen = {}
    keys = ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL")
    for s in settings:
        data = load_json(s)
        if not isinstance(data, dict):
            continue
        label = rel(s, proj)
        if "model" in data:
            print(f"  {label}: model={data['model']}")
        for k in keys:
            v = (data.get("env") or {}).get(k)
            if v is not None:
                print(f"  {label}: env {k}={v}")
                env_seen.setdefault(k, (str(v), label))
        enabled_plugins += sum(1 for v in (data.get("enabledPlugins") or {}).values() if v)
    for k in keys:
        if os.environ.get(k):
            print(f"  shell: {k}={os.environ[k]}")
            env_seen[k] = (os.environ[k], "shell")  # shell wins over settings files
    sub, where = env_seen.get("CLAUDE_CODE_SUBAGENT_MODEL", ("", ""))
    if env_seen.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", ("",))[0] == "1":
        warnings.append("CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 overrides every agent file's model (pins to Fable are ignored)")
    if re.search(r"haiku|sonnet", sub, re.I):
        warnings.append(f"CLAUDE_CODE_SUBAGENT_MODEL={sub} ({where}): every ad hoc subagent runs on it - check it is intended")
    if re.search(r"xhigh|max", env_seen.get("CLAUDE_CODE_EFFORT_LEVEL", ("",))[0], re.I):
        warnings.append("CLAUDE_CODE_EFFORT_LEVEL is xhigh/max and overrides every agent's effort")
    if enabled_plugins:
        print(f"  enabledPlugins: {enabled_plugins}")
    print()

    # 5. MCP servers: each connected server's tool definitions ride every request.
    mcp = {}
    data = load_json(proj / ".mcp.json")
    if isinstance(data, dict):
        mcp["project .mcp.json"] = len(data.get("mcpServers") or {})
    if use_user:
        cj = load_json(Path.home() / ".claude.json")
        if isinstance(cj, dict):
            mcp["user ~/.claude.json"] = len(cj.get("mcpServers") or {})
            pj = (cj.get("projects") or {}).get(str(proj)) or {}
            mcp["~/.claude.json for this project"] = len(pj.get("mcpServers") or {})
        names = set()
        for f in (home / "plugins").rglob(".mcp.json") if (home / "plugins").is_dir() else []:
            d = load_json(f)
            if isinstance(d, dict):
                names.update((d.get("mcpServers", d) or {}).keys())
        mcp["plugins (installed, unique names)"] = len(names)
    print("MCP servers (tool definitions sent every request unless deferred):")
    for k, v in mcp.items():
        print(f"  {v:>5}  {k}")
    print()

    # 6. Findings.
    print("Findings (* = in a file loaded every request):")
    if not hits and not warnings:
        print("  none")
    for w in warnings:
        print(f"  ! {w}")
    for pid, _, why in COMPILED:
        found = sorted(hits.get(pid, []), key=lambda h: not h[0])
        if not found:
            continue
        print(f"  [{pid}] {why}")
        for is_always, label, n, text, _ in found[:MAX_HITS_PER_PATTERN]:
            print(f"    {'*' if is_always else ' '} {label}:{n}  {text}")
        if len(found) > MAX_HITS_PER_PATTERN:
            print(f"      ... {len(found) - MAX_HITS_PER_PATTERN} more")


if __name__ == "__main__":
    main()
