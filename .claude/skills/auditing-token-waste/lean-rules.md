# Lean rules block

Add under a heading in `.claude/CLAUDE.md` (merge with existing rules; don't duplicate):

```markdown
## Keeping token use down
- Lead with the answer. Leave out unnecessary details unless the reader asks and practice concision.
- Delegate to a subagent when the work is large, runs in parallel, or would fill this context with output (long logs, broad searches). Do small and sequential steps directly: a subagent re-reads context and its report must be read back.
- When a subagent reports back, build on its findings instead of redoing its work.
- Search before reading: grep or glob for the target, then read only the relevant part of a file.
- Check work by running the project's tests or build once, rather than re-reviewing by hand.
```

The second bullet follows Anthropic's Fable 5.2 guidance: describing delegation with its cost first (tested in the subagent tool's description) cut subagent use by about a third at the same success rate.
