# Handoff: cutting Claude Fable 5.2 token use

**Goal:** spend fewer tokens (and dollars) when working in Claude Code with Claude Fable 5.2 as the main model, without losing quality on hard work.
**Branch:** `claude/gracious-noether-uq5680` (pushed, not merged). Everything lives under hidden folders, so the GitHub Pages site doesn't publish it.

## What's built

| Piece | Where | What it does | Status |
|---|---|---|---|
| Subagent routing | `.claude/settings.json`, `.claude/agents/` | Helpers Claude starts without a set model run on Opus 5.5; `worker` = Opus 5.5 (medium effort), `Explore` = Haiku 5.5 (low, replaces the built-in), `deep-review` = Fable 5.2 (high) | Active for sessions opened in this repo after the files load; savings not yet measured |
| Skill `routing-subagent-models` | `.claude/skills/routing-subagent-models/` | Instructions plus agent templates to set up the routing in any project | Tested: an agent with the skill got every fact right; without it, precedence and Explore facts were wrong |
| Skill `auditing-token-waste` | `.claude/skills/auditing-token-waste/` | `scripts/audit.py` scans instruction files, skills, agents, settings and MCP config for bloat and token-inflating instructions; proposes fixes, applies only with approval; `lean-rules.md` holds a concise-output block | Tested on a planted project: 10/10 problems found, ~98k vs ~157k tokens for an unaided audit |
| Mod `turn-meter` | `.claude/mods/turn-meter/`, listed in `.claude-plugin/marketplace.json` | Band above the prompt: last turn's input (with cache read/write), output, duration, cost incl. subagents; session totals; `/turn-meter` toggles it | Ran in the cloud session; installs cleanly from a local clone (tested) |

## Next steps
1. **Install on the Mac** (the cloud session couldn't reach it: the only Remote Control folder, "Firm Trader", isn't offered to cloud sessions). Run in Terminal, then restart Claude Code:
   ```bash
   git clone -b claude/gracious-noether-uq5680 https://github.com/christianr6/christianr6.github.io.git ~/claude-tools
   claude plugin marketplace add ~/claude-tools
   claude plugin install turn-meter@christianr6-tools
   mkdir -p ~/.claude/skills ~/.claude/agents
   cp -R ~/claude-tools/.claude/skills/. ~/.claude/skills/
   cp ~/claude-tools/.claude/agents/*.md ~/.claude/agents/
   python3 - <<'EOF'
   import json, pathlib
   p = pathlib.Path.home() / ".claude" / "settings.json"
   d = json.loads(p.read_text()) if p.exists() else {}
   d.setdefault("env", {})["CLAUDE_CODE_SUBAGENT_MODEL"] = "claude-opus-5-5"
   p.write_text(json.dumps(d, indent=2) + "\n")
   EOF
   ```
   Check: `/agents` lists `worker`, `Explore`, `deep-review`; the turn-meter band shows after the first turn.
2. **Measure:** compare the turn-meter's cost per turn and cache-read share on similar tasks before and after the routing. Aim for cache reads ≥80% of input.
3. **Run the audit** (`/auditing-token-waste`) on the Mac. Expected top finding: ~423 plugin skills (~35k tokens of descriptions) and ~72 plugin MCP servers loaded every request. Those plugins come from the claude.ai account; turn off unused ones in claude.ai settings.
4. **Optional:** merge the branch so `/plugin install turn-meter --marketplace christianr6/christianr6.github.io` works without a clone (that install reads the default branch).

## Decisions and why
- **Opus 5.5 for helpers, Fable kept for `deep-review`:** Opus 5.5 is half Fable's per-token price ($4/$20 vs $8/$40 per MTok); judgment-heavy work stays on Fable because retries cost more than the savings.
- **No `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`:** it would override `deep-review`'s Fable pin.
- **`effort:` set in every agent:** subagents on another model don't inherit the session's effort; Opus/Haiku 5.5 default to medium.
- **Files in hidden folders:** a root `.md` would be published by GitHub Pages.

## Caveats
- The user-level setting sends ad hoc helpers to Opus 5.5 even when the main model is Sonnet or Haiku (a cost increase there); remove it from `~/.claude/settings.json` when not on Fable.
- Turn-meter cost is in API dollars (an estimate on a subscription). A background subagent still running when a turn ends counts in session totals, not that turn's line.
- Audit token counts are estimates (chars/4); `/context` gives real counts. It can't see account-level plugins/connectors.

## Key facts (Claude Code docs)
- Subagent model precedence (v2.1.251+): per-call `model` > agent file `model:` > `CLAUDE_CODE_SUBAGENT_MODEL` > main model.
- On a Fable parent, built-in Explore runs on Opus (Anthropic API/subscriptions); a project or user agent named `Explore` replaces it.
- `CLAUDE_CODE_EFFORT_LEVEL` overrides every agent's `effort:`; leave it unset.
- Fable 5.2 token wasters (Anthropic): "owner and long-term maintainer" line +70–80% output; recap/opening lines +~20%; "finish the whole task" +~30%; a token budget shown to the model raises cost with no gain.

Sources: code.claude.com/docs/en/sub-agents, platform.claude.com Fable 5.2 prompting guide and "Optimizing for cost and intelligence".
