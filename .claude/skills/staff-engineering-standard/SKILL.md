---
name: staff-engineering-standard
description: Use when fixing a bug or a wrong number, editing or deduplicating code, formulas, or SQL, delegating work to subagents, hitting a second failed test or build, or writing a final report in this repository. Gives the gates to pass before editing, before delegating, and before reporting.
---

# Staff Engineering Standard

The full rules are in `STAFF_ENGINEERING_STANDARD.md` at the repository root. Do not read that file whole. Pass the gates below in order. Open one numbered section only when a gate tells you to: `Grep "^## <n>\."` for the line number, then read from there to the next `---`.

The gates exist because the expensive failures here are quiet ones: a fix placed downstream of the real cause, a join that double counts, a caught exception that turns missing data into a zero, a report that says "fixed" with no run behind it. Each gate makes one of those visible before it ships.

## Gate 1: before the first edit

Write these three lines. If you cannot fill one in, you are not ready to edit.

```
Symptom:    <actual vs expected, and the command or query that shows it>
Root cause: <path:line where the value or state first becomes wrong>
Invariant:  <the DATA, STATE, or MATH condition the fix restores>
```

For a wrong number, recompute it by hand on 1 to 3 rows before you read code.

Open section 1 if you cannot reproduce the symptom, if the root cause sits in logic with 2 or more call sites, or if the request can be read two ways. Facts and conventions come from the repository. Ask the user only about intent, definitions, and irreversible actions, and keep working on whatever does not depend on the answer.

## Gate 2: while editing

- Put the fix at the root-cause line. A fix anywhere else is a patch on a symptom.
- Every changed line must trace to the root cause. No reformatting, no renames, no drive-by cleanup.
- Delete what your change makes unused, in the same diff. Leave unrelated dead code alone and report it.

Open section 2 before you add a helper, wrapper, guard, default value, flag, or dependency. The usual answer there is to merge or delete, not to add.

## Gate 3: before delegating

Keep a task of 1 to 3 steps in your own loop. Split only when the work has 4 or more steps and at least 2 parts that write to different files and do not depend on each other. Send every worker exactly these four lines; the worker has none of your context:

```
Goal: <observable outcome and why it matters>
Exact Scope & Files: <may read | may write>
Hard Invariants: <what must still hold afterwards>
Expected Return Format: <exact shape of the reply>
```

Open section 3 to pick the tier (1 finds, 2 builds, 3 designs and verifies).

If you are the worker: when the same test or build fails a second time after a second, different fix, stop. Do the same if two invariants in your brief conflict or the fix needs a file outside your scope. Return the trigger, your last 2 attempts with their exact output, your current hypothesis, and the files you touched. A third guess costs more than the escalation.

## Gate 4: when something blocks you

Ask one question: did a person put this barrier here on purpose?

- No (timeout, empty search, lint or test failure, rate limit): diagnose it and route around it without asking. Never get past it by skipping a test, disabling a lint rule, or catching the error.
- Yes (off-limits file, deleting data you did not create, missing credentials, denied permission): stop that action, report what you found, and continue everything else.

Open section 5 for the per-obstacle playbook and the list of actions that need no approval.

## Gate 5: before you report

Answer each line with evidence from a command you ran after your last edit. "Not run" is an acceptable answer. A guess is not.

```
1 Grain:      <row counts before and after each join; totals reconcile to what>
2 Boundaries: <empty, first, last, interval ends, date edges, sign convention tested>
3 Exceptions: <no swallowed errors or masking defaults in the diff>
4 Net lines:  <+added / -removed / net, non-test code; test lines separately>
```

If any output contradicts something you said earlier, the earlier statement is void. Say so in the report (`OVERTURNED: <claim> | Evidence | Corrected`) and re-check what depended on it. Open section 6 for the full check list.

## Gate 6: the report

Sentence 1 is the conclusion. One idea per sentence. Define a term before you use it. End with:

```
- Verified Findings: <confirmed by executed evidence, each with command or path:line>
- Changes Made: <files and effect; net lines; "none" if none>
- Open Next Step: <one action, its owner, any blocker; "none" if complete>
```

Open section 7 for the sentence rules. Section 4 covers search and context budgets; open it when a search returns more than 50 hits or nothing.

## Worked example

Request: "Monthly revenue on the dashboard is too high. Fix it."

```
Symptom:    March revenue = 184,200; SUM(orders.amount) for March = 121,900.
Root cause: reports/revenue.sql:14, orders JOIN shipments (1 order : N shipments).
Invariant:  DATA. One row per order before SUM(amount).
```

- Wrong fix: `SUM(DISTINCT amount)` in the dashboard query. It sits downstream of the cause and drops two real orders that share an amount.
- Right fix: aggregate shipments to one row per order before the join, at line 14. Two other reports use the same view, so the fix goes in the view (section 1.2), not in three queries.
- Audit: 4,312 rows before the join and 4,312 after. March total = 121,900 and matches the orders table. Net lines +3 / -1.
- Handoff: "March revenue was overstated by 62,300 because the shipments join duplicated order rows; the view now joins one row per order." Then the three bullets.
