---
name: routing-subagent-models
description: Use when Claude Code runs on Claude Fable 5.2 or another expensive main model and subagents (Explore, Plan, general-purpose, custom agents) drive up token cost or usage limits, or when deciding which model or effort level a subagent should run on.
---

# Routing Subagent Models

## Overview
Subagents run on the main session's model unless told otherwise, so on Fable 5.2 ($8/$40 per MTok) every helper costs Fable prices. Route routine subagent work to Opus 5.5 ($4/$20) or Haiku 5.5 ($0.10/$0.50) and keep Fable only for the agents that need it.

## How Claude Code picks a subagent's model (docs, v2.1.251+)
1. `model` Claude passes when it starts the subagent
2. `model:` in the agent file (`inherit` = main model)
3. `CLAUDE_CODE_SUBAGENT_MODEL` env var
4. The main conversation's model

| Fact | Consequence |
|---|---|
| `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` (v2.1.257+) ignores every agent file's `model:` and Claude's per-call model | Never set it when one agent must stay on Fable |
| Built-in Explore on a Fable parent runs on Opus (Anthropic API, subscriptions) or Fable (Bedrock, Vertex, Foundry); the env var alone doesn't move Explore or Plan | To put exploration on Haiku, add a project agent named `Explore`; it replaces the built-in |
| Plan and general-purpose inherit the main model | The env var covers general-purpose and ad hoc agents; Plan stays on Fable unless a project agent named `Plan` replaces it (confirm in `/agents`) |
| `model:` accepts `fable`, `opus`, `sonnet`, `haiku`, `inherit`, or a full ID such as `claude-opus-5-5` | Pin full IDs so an alias update doesn't move the agent |
| A subagent on a different model does not get the session's effort; Opus 5.5 and Haiku 5.5 default to `medium` | Set `effort:` in every agent file |
| `CLAUDE_CODE_EFFORT_LEVEL` overrides every agent's `effort:` | Leave it unset |

## Setup
1. Check the version and for stray values: `claude --version`, `echo $CLAUDE_CODE_SUBAGENT_MODEL $CLAUDE_CODE_SUBAGENT_MODEL_FORCE $CLAUDE_CODE_EFFORT_LEVEL`, and the `env` block of `.claude/settings.json` and `~/.claude/settings.json`. Below v2.1.251 the env var outranks agent files: tell the user to upgrade.
2. Merge into `.claude/settings.json` (keep existing keys):
   ```json
   { "env": { "CLAUDE_CODE_SUBAGENT_MODEL": "claude-opus-5-5" } }
   ```
3. Copy the templates in `templates/` into `.claude/agents/`, adjusting descriptions to the project:
   - `worker.md`: Opus 5.5, `medium`, for well-specified implementation
   - `Explore.md`: Haiku 5.5, `low`, read-only search (replaces the built-in)
   - `deep-review.md`: Fable 5.2, `high`, for hard reviews and debugging
4. Find lines in CLAUDE.md, rules, skills and agent descriptions that invite delegation ("use subagents for…", "use proactively") and show them to the user: on Fable 5.2 they multiply subagent count.
5. Tell the user to restart the session or open `/agents` to load the files, then compare a few turns' cost (`/cost`, or a turn meter) before and after.

## Common mistakes
- Setting FORCE "to make sure it applies": it silently moves `deep-review` off Fable.
- A leftover `CLAUDE_CODE_SUBAGENT_MODEL=haiku` in a shell profile or CI quietly downgrades every ad hoc agent.
- Omitting `effort:` and assuming subagents follow `/effort`.
- Putting cheap models on judgment-heavy work (security review, tricky debugging): the retries cost more than the savings. Pin those to `fable`.
