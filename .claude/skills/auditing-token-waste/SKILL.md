---
name: auditing-token-waste
description: Use when Claude Code sessions burn through usage limits or cost too much per turn, prompt-cache reads are low, or CLAUDE.md, rules, skills, agent files, settings or MCP config may be bloated or carry instructions that inflate token use, especially on Claude Fable 5.2.
---

# Auditing Token Waste

## Overview
Most avoidable spend comes from what is resent on every request (instruction files, skill listings, MCP tool definitions) and from instructions that make the model write, check or delegate more. A script does the scanning so the audit itself stays cheap.

## Steps
1. Run the scanner (read-only). Pass the project root; it also reads `~/.claude` unless given `--no-user`:
   `python3 <this skill's dir>/scripts/audit.py <project-dir>`
   Do not read the config files one by one first; the script's report is the input.
2. Open only the files the report flags, to confirm each hit in context. Drop hits that are quotes, examples or unrelated uses (e.g. "twice" in prose).
3. Write the report in this shape, ranked by impact (always-loaded `*` items and large counts first):

   | # | Where (file:line) | Problem | Measured / estimated cost | Fix |
   |---|---|---|---|---|

   Then one line on what the script cannot see: account- or organization-level plugins and connectors (turned off in claude.ai settings), and real token counts (`/context`).
4. Propose the edits as a diff. Apply them only when the user approves.
5. If the project has no concise-output rules, offer to add the block in `lean-rules.md` to `.claude/CLAUDE.md` (in a GitHub Pages / Jekyll repo, `.claude/` is not published; a root `CLAUDE.md` would be).

## What the findings mean (Anthropic's Fable 5.2 guides)
| Pattern | Cost |
|---|---|
| "owner and long-term maintainer… design is up to you" | +70-80% output, unrequested changes |
| "finish the whole task" wording | +~30% output; keep only if the model stops early |
| Opening-line / recap instructions | +~20% output |
| Token budget shown to the model | Higher cost, no quality gain |
| Delegation invitations, "use proactively" | Fable 5.2 delegates readily; subagents can be most of the bill |
| "verify twice", "double-check", "think step by step" | Repeated work; name one concrete check instead |
| "never retry", "ask before every…" | Extra round trips, each resending the context |
| "don't think" | Doesn't reduce thinking at medium+; lower effort instead |
| Dates, `{{…}}`, `$(…)`, git status in instructions | Breaks the prompt cache (reads cost 1/40 of input on Fable 5.2) |
| CLAUDE.md over ~200 lines | Resent every request and to every subagent |
| Hundreds of skills / many MCP servers | Listings and tool definitions resent every request |

Subagent model or effort findings: use the routing-subagent-models skill.

## Common mistakes
- Deleting safety rules the user needs. Rewrite caution as a named exception ("retries of read-only commands need no approval"), and keep confirmation for irreversible actions.
- Counting on-demand skill bodies as per-request cost: only their descriptions are sent every request.
- Rewriting the system prompt or CLAUDE.md mid-session to test a fix: it breaks the cache. Test in a new session.
