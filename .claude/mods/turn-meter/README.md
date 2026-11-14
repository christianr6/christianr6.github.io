# turn-meter

A Claude Code mod that shows, above the prompt, what the last turn used and cost:

```
Last turn: in 48.2k (cache read 41.0k, write 3.1k) · out 2.3k · 1m 12s · $0.21 · incl. 2 subagent runs
Session: 7 turns · in 310.5k · out 14.8k · 6m 40s · $1.37
```

- **in**: input tokens (fresh + read from the prompt cache + written to it). A high cache-read share means caching works.
- **out**: output tokens.
- **time**: from the start of the model's turn to its end.
- **cost**: the change in the session's cost during the turn, as `/cost` counts it (API prices; on a subscription it is an estimate, not a charge).
- Subagent runs started during the turn are included in its tokens and cost.

`/turn-meter` hides or shows the band.

## Install

At the prompt of a terminal session:

```
/plugin install turn-meter --marketplace christianr6/christianr6.github.io
```

From a shell:

```
claude plugin install turn-meter --marketplace christianr6/christianr6.github.io
```

Answer `y` to add the marketplace, then pick a scope. The install reads the repository's default branch.
