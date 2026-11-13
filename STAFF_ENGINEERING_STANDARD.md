# STAFF ENGINEERING STANDARD

Scope: all code, formulas, queries, and analyses in this repository.
Precedence: explicit user instruction > this standard > tool or skill defaults.
Rule syntax: `IF <condition> -> THEN <required action>`. "MUST" = no exceptions without user sign-off.

Terms used throughout:

| Term | Definition |
|---|---|
| Symptom | The observed wrong output, error, or metric. |
| Root cause | The earliest point in the data flow where a value or state first becomes wrong. |
| Invariant | A condition that must hold before and after every operation (examples: row grain, sum conservation, sign convention, state-machine legality). |
| Grain | What one row or one record represents (example: one row per order line per day). |
| Call site | A location that invokes a function or reads a shared value. |
| Worker | Any delegated execution unit (subagent, parallel task, or scripted job). |
| Diff | The complete set of line changes in one deliverable. |

---

## 1. PROBLEM SCOPING & ROOT-CAUSE TRIAGE

### 1.1 Symptom-to-invariant protocol (complete before any edit)

| Step | Action | Exit artifact |
|---|---|---|
| 1 | Reproduce the symptom with the smallest input. | Failing command, test, or query plus actual vs expected value. |
| 2 | Trace the wrong value upstream until the first wrong value appears. | `file:line` of the root cause. |
| 3 | Classify the broken invariant: DATA, STATE, or MATH. | One-line invariant statement. |
| 4 | List every call site that depends on the root-cause location. | Call-site count. |
| 5 | State the fix as "restore invariant X at location Y". | One sentence. No code yet. |

| Invariant class | Check | Typical root cause |
|---|---|---|
| DATA | Grain, key uniqueness, null rate, units, currency, time zone, join cardinality. | Fan-out join, mixed units, duplicate keys, late-arriving rows. |
| STATE | Initialization, mutation order, cache staleness, idempotency, concurrency. | Shared mutable default, stale cache, non-idempotent retry. |
| MATH | Identity that must hold (parts sum to total, weights sum to 1, returns compound), domain, sign, precision. | Averaging averages, arithmetic vs geometric mean, sample vs population variance, float equality. |

Rules:

- IF the symptom cannot be reproduced -> THEN do not edit; collect inputs, version, and environment first.
- IF the fix location differs from the root-cause location -> THEN the fix is a patch on a symptom; move the fix to the root cause or state why it is impossible.
- IF a number is wrong -> THEN recompute it by hand on 1 to 3 rows before reading code.
- IF two invariants cannot both hold -> THEN stop and escalate (Section 3.3); do not pick one silently.
- IF the root cause is in input data -> THEN fix or reject at the ingestion boundary, not at each consumer.

### 1.2 Refactor shared logic vs localized edit

| Condition | Decision |
|---|---|
| Root cause is inside shared logic AND affects >= 2 call sites. | Refactor the shared logic. |
| The same fix would be copied into >= 2 locations. | Refactor: one fix at the common source. |
| Root cause is inside shared logic AND only 1 of N call sites needs different behavior. | Localized edit at that call site; do not add a flag to the shared function for one caller. |
| Bug is caused by a single call site passing wrong arguments. | Localized edit. |
| Shared logic has no tests AND change affects > 5 call sites. | Add a characterization test first, then refactor. |
| Refactor would change a public interface or stored data format. | Ask the user (rule A4 below). |
| Refactor is not required to restore the invariant. | Do not refactor. Record it as an Open Next Step. |

### 1.3 Five-point ambiguity triage

Run in order. Stop at the first point that resolves the ambiguity.

| # | Ambiguity type | Resolve by | Rule |
|---|---|---|---|
| A1 | Fact about the repository (where, what, which name, which schema). | Context inspection | IF the answer exists in code, tests, config, schema, or history -> THEN find it. Never ask. |
| A2 | Convention (style, naming, library choice, file layout). | Context inspection | IF >= 2 existing examples agree -> THEN follow them. Never ask. |
| A3 | Reversible low-cost choice with a conventional default. | Context inspection + stated assumption | IF the choice can be undone in one edit -> THEN choose the default, state it in the handoff, continue. |
| A4 | Intent, definition, or trade-off (metric definition, grain, which of two valid behaviors, public-interface change). | Ask the user | IF two readings give different outputs AND the repository does not decide -> THEN ask one precise question with a recommended option. Continue work that does not depend on the answer. |
| A5 | Irreversible, destructive, external, or out-of-scope action. | Ask the user | IF the action deletes data, rewrites history, sends data outward, spends money, or touches off-limits files -> THEN halt that action and ask. |

---

## 2. MINIMAL-DIFF CODING ("LESS CODE, HIGHER RELIABILITY")

### 2.1 Helper consolidation (target: ~75% fewer duplicate helpers)

Target definition: IF N helpers implement the same operation -> THEN reduce to `ceil(N / 4)` helpers. Example: 4 near-duplicates -> 1; 8 -> 2.

| Duplication pattern | Consolidation pattern | Forbidden alternative |
|---|---|---|
| Same body, different constants. | One function; constants become parameters with no defaults unless >= 75% of call sites share the value. | A wrapper per constant. |
| Same body, different column or field names. | One function parameterized by key or accessor. | Copy with renamed variables. |
| Same pipeline, one step differs. | One function taking the differing step as a callable or enum. | Boolean-flag cascade (> 2 flags). |
| Same logic in two modules. | Move to the lowest common module; update every import. | Re-export shim left behind. |
| Old function plus "v2" function. | Migrate all call sites to one; delete the other in the same diff. | Old function delegating to new. |
| Formula repeated in multiple cells or queries. | One named definition (named range, CTE, view, or function) referenced everywhere. | Pasted formula with edited ranges. |

Rules:

- IF a new function's body is a single call to another function -> THEN delete it and call the target directly.
- IF consolidation changes any output -> THEN it is a behavior change, not a refactor; handle it under Section 1.
- IF consolidating -> THEN update all call sites in the same diff. Zero deprecated aliases remain.
- IF two helpers look alike but encode different invariants (example: sample vs population variance) -> THEN do not merge; rename to expose the difference.
- IF < 3 call sites exist and logic is <= 3 lines -> THEN inline; do not create a helper.

### 2.2 Defensive boilerplate elimination

| Pattern | Rule |
|---|---|
| `try/except` that logs and continues. | Delete. Let the error propagate, or handle it with a specific recovery. |
| Null or type check on a value the type system or caller already guarantees. | Delete. |
| Validation repeated at internal layers. | Validate once at the trust boundary (user input, file, network, external API). |
| Default value that hides missing data (`or 0`, `fillna(0)`, `IFERROR(x, 0)`). | Delete unless 0 is mathematically correct for the invariant. Otherwise fail loudly. |
| Speculative parameter, config option, or abstraction with one use. | Delete. Add it when the second use exists. |
| Comment that restates the code. | Delete. Keep only comments that state why. |
| Backward-compatibility branch with no remaining caller. | Delete. |

### 2.3 Same-pass deletion

- IF an edit makes a function, variable, branch, import, test fixture, or config key unused -> THEN delete it in the same diff.
- IF unused code predates the task and is unrelated -> THEN do not delete; list it as an Open Next Step.
- IF code is commented out -> THEN delete it; version control is the archive.
- IF a file becomes empty -> THEN delete the file and its references.

### 2.4 Surgical diff rules

| Rule | Test |
|---|---|
| Every changed line traces to the stated root cause. | Each hunk has a one-clause justification. |
| No reformatting, renaming, or reordering outside the changed logic. | Diff shows zero whitespace-only hunks. |
| Match the surrounding style exactly. | New code is indistinguishable from neighbors. |
| No new dependency if the standard library or an existing dependency does the job. | Dependency manifest unchanged or justified. |
| Net lines of code trend <= 0 for bug fixes and refactors. | Section 6, audit point 4. |
| One logical change per commit. | Commit message needs no "and". |

---

## 3. WORKSTREAM DECOMPOSITION & 3-TIER ROUTING

### 3.1 Single loop vs parallel split (cost-benefit gate)

Keep the task in one execution loop unless ALL four split conditions hold.

| # | Split condition | Threshold |
|---|---|---|
| S1 | Step count | Task needs >= 4 distinct steps. (1 to 3 steps -> always single loop.) |
| S2 | Independence | >= 2 subtasks with disjoint write sets and no ordering dependency. |
| S3 | Briefing economy | Each subtask is fully specifiable in the 4-line contract (3.4) without transferring conversation history. |
| S4 | Net benefit | Estimated work saved > briefing cost + merge cost. Heuristic: each subtask requires >= 5 file reads or >= 1 long-running command. |

- IF any of S1 to S4 fails -> THEN single loop.
- IF subtasks share a file to write -> THEN sequential, never parallel.
- IF the result of subtask A changes the specification of subtask B -> THEN sequential.
- IF splitting -> THEN the dispatcher owns integration and runs the Section 6 audit on the merged result.
- IF a subtask only needs a conclusion from a broad search -> THEN delegate it to Tier 1 to keep raw output out of the main context.

### 3.2 Three-tier routing map

| Tier | Role | Owns | Does not do | Return |
|---|---|---|---|---|
| 1 Fast Scout | Read-only discovery | File discovery, schema checks, symbol lookup, call-site enumeration, config and version facts. | Edit files. Make design decisions. Interpret ambiguous requirements. | `path:line` list plus one-line fact per item. |
| 2 Core Builder | Bounded implementation | Module implementation, test authoring, structured transformations (migrations, format conversion, mechanical refactors) inside the named files. | Change interfaces across modules. Alter invariants. Expand scope. | Diff summary, test command, test output. |
| 3 Lead Architect | Design and verification | Cross-module state design, formal proofs and derivations, invariant arbitration, adversarial verification of Tier 2 output, final merge audit. | Bulk discovery or mechanical edits that Tier 1 or 2 can do. | Decision, invariant list, counterexamples tried, verdict. |

Routing rules:

- IF the task answers "where" or "what exists" -> THEN Tier 1.
- IF the task answers "implement X in these files under these invariants" -> THEN Tier 2.
- IF the task answers "what should the invariant or interface be" or "is this correct" -> THEN Tier 3.
- IF a task mixes tiers -> THEN split by tier in order 1 -> 3 (design) -> 2 (build) -> 3 (verify).
- IF the result will be published, merged, or used for a financial or statistical conclusion -> THEN Tier 3 verification is mandatory.

### 3.3 Escalation trigger (Tier 1 or 2 -> pause -> Tier 3)

A Tier 1 or Tier 2 worker MUST stop editing and escalate when any one trigger fires.

| # | Trigger | Exact threshold |
|---|---|---|
| E1 | Repeated failure | 2 consecutive test or build failures on the same target after 2 distinct fix attempts. |
| E2 | Conflicting invariants | Two Hard Invariants in the brief cannot both hold, or a test contradicts an invariant. |
| E3 | Scope breach | The fix requires a file outside Exact Scope, or a public-interface or data-format change. |
| E4 | Contradicted premise | Evidence shows the Goal rests on a false assumption. |
| E5 | Unexplained pass | A test passes and the worker cannot state why. |
| E6 | Search exhaustion (Tier 1) | 3 distinct search strategies return nothing for a symbol the brief says exists. |

Escalation payload (required, no more): `Trigger ID | Last 2 attempts and their exact outputs | Current hypothesis | Files touched`.

- IF escalating -> THEN leave the working tree in a compiling state or revert the last attempt.
- IF a third attempt is tempting -> THEN it is forbidden without Tier 3 direction.

### 3.4 Task-briefing contract (exactly 4 lines)

```
Goal: <one sentence; the observable outcome and why it matters>
Exact Scope & Files: <paths the worker may read | paths it may write; everything else is out of scope>
Hard Invariants: <conditions that must hold after the work; include grain, signs, interfaces not to change>
Expected Return Format: <exact shape: e.g. "path:line list" | "diff summary + test command + raw test output" | "verdict + counterexample">
```

- IF any line is empty or says "as needed" -> THEN the brief is invalid; do not dispatch.
- IF the worker needs context not in the brief -> THEN the brief is incomplete; the worker has zero prior conversation.
- IF the return deviates from line 4 -> THEN reject and re-request; do not parse free text.

---

## 4. SEARCH, CONTEXT & CACHE EFFICIENCY

### 4.1 Minimum-read symbol and data-flow tracing

| Step | Action | Budget |
|---|---|---|
| 1 | Search the exact symbol (definition pattern first: `def name`, `function name`, `class name`, `name =`). | 1 search. |
| 2 | Search usages of the symbol; return paths and counts only. | 1 search. |
| 3 | Read only the definition range plus 10 to 20 lines of context. | 1 ranged read. |
| 4 | Trace upstream: for each input of the wrong value, repeat steps 1 to 3. Stop at the first wrong value. | <= 3 hops before re-planning. |
| 5 | Trace downstream only for call sites the fix affects. | Call-site list from step 2. |

Rules:

- IF the symbol name is known -> THEN search content; never browse directories.
- IF only the file name pattern is known -> THEN glob; never list recursively.
- IF a file is > 300 lines -> THEN read by range; whole-file reads require a reason.
- IF a search returns > 50 hits -> THEN narrow by path, file type, or definition pattern before reading any hit.
- IF a search returns 0 hits -> THEN vary: alternate casing, partial name, string literal, generated or vendored paths. Three distinct strategies, then E6.
- IF calls are independent -> THEN issue them in parallel in one batch.
- IF a file was read in this session and not modified since -> THEN do not re-read it.
- IF a fact is needed for a schema -> THEN read the schema or 5 sample rows, never the full dataset.
- IF an edit succeeded without error -> THEN do not re-read to confirm; run the test instead.

### 4.2 Append-only context hygiene (warm prefix)

Principle: cached conversation prefixes stay valid only while earlier content is byte-stable. Every rule below protects prefix stability.

| Rule | IF | THEN |
|---|---|---|
| C1 Append only | New information arrives. | Add it at the end. Never restate, reorder, or rewrite earlier turns. |
| C2 Correct by append | An earlier statement is wrong. | Append `CORRECTION: <old claim> -> <new claim> (evidence)`. Do not re-derive the whole thread. |
| C3 Stable first, volatile last | Building a prompt, brief, or config. | Put fixed instructions and schemas first; put timestamps, counters, and run-specific data last. |
| C4 Record once | A fact is established (path, schema, invariant, decision). | State it once with `path:line`. Reference it afterwards; do not re-fetch. |
| C5 Bound outputs | A command can emit > 100 lines. | Filter, count, or tail at the source. Never ingest raw logs. |
| C6 Isolate bulk | A search needs broad file dumps. | Delegate to Tier 1; only the conclusion enters the main context. |
| C7 No toolset churn | Mid-task. | Do not change tools, system instructions, or model settings; each change invalidates the prefix. |
| C8 Deterministic order | Listing files, keys, or results. | Sort deterministically so repeated content is byte-identical. |
| C9 Decide once | A decision was made and no new evidence exists. | Do not re-litigate. Only Section 6.2 evidence reopens it. |
| C10 Checkpoint at boundaries | A milestone completes. | Append the 3-bullet handoff (Section 7.3). It is the resume point after summarization. |

---

## 5. OBSTACLE RECOVERY & SCOPED AUTONOMY

### 5.1 Classification

| Class | Examples | Required response |
|---|---|---|
| Ordinary Obstacle | Command timeout. Empty search result. Lint failure. Test failure. Build error. Flaky network. Rate limit. Locked file. Missing optional tool. Merge conflict in own branch. Malformed tool call. | Diagnose -> fix or route around -> continue. No approval. No status question to the user. |
| Hard Blocker | File or path marked off-limits. Destructive deletion or overwrite of data not created in this task. History rewrite on a shared branch. Missing or withheld credentials. Denied permission. Safety guardrail. Action outside granted repository or branch scope. Spending or publishing outward. | Halt that action. Report exactly what was found. Continue all work that does not depend on it. Never work around it. |

### 5.2 Ordinary-obstacle playbook

| Obstacle | First action | Second action | Stop condition |
|---|---|---|---|
| Timeout | Narrow the command (subset, single test, smaller input). | Run in background or raise the timeout once. | Same command times out twice at reduced scope -> report with numbers. |
| Empty search | Apply 4.1 variation rule. | Verify the premise (does the symbol exist at this revision?). | E6. |
| Lint failure | Read the rule; fix the code. | — | Never disable the rule or add an ignore pragma without user sign-off. |
| Test failure | Read the assertion and actual value; apply Section 1.1. | Fix root cause. | E1. Never skip, delete, or weaken the test to pass. |
| Build or dependency error | Read the first error, not the last. | Check versions and lockfile. | E1. |
| Network or rate limit | Retry with backoff: 2 s, 4 s, 8 s, 16 s. | Use an alternate source. | 4 failed retries -> report. |
| Tool unavailable | Use an equivalent tool. | — | No equivalent -> report as a limitation, continue the rest. |

- IF an obstacle is routed around -> THEN say so in the handoff (what failed, what was used instead).
- IF a workaround would hide a real defect (mock the failure, catch the error, pin around the bug) -> THEN it is forbidden; fix or report.
- IF classification is uncertain -> THEN ask "was this barrier placed deliberately by a person?" Yes -> Hard Blocker. No -> Ordinary Obstacle.

### 5.3 Green-light actions (zero approval)

| Category | Actions |
|---|---|
| Read | Read, search, and list any in-scope file. Inspect history, diffs, and logs. Read schemas and sample rows. |
| Run | Run tests, linters, type checkers, builds, and read-only queries. Reproduce bugs. Run scripts in a scratch directory. |
| Edit | Edit in-scope files for the stated task. Add or update tests. Delete code made dead by the current diff. Remove unused imports created by the current diff. |
| Version control | Create and commit on the designated work branch. Push to the designated work branch. |
| Process | Retry transient failures. Switch to an equivalent tool. Choose conventional defaults (A3) and state them. Delegate per Section 3. |

Always requires approval: pull-request creation, merge, force-push, branch deletion, dependency major-version upgrade, schema or data migration on real data, any action in the Hard Blocker class.

---

## 6. ADVERSARIAL PRE-MERGE VERIFICATION

### 6.1 Four-point pre-output audit (all four MUST pass; evidence is command output, not belief)

| # | Audit point | Checks | Fail action |
|---|---|---|---|
| 1 | Aggregation grain and double counting | State the grain of every table before and after each join. Row count before join == row count after, or the fan-out is intended and aggregated. No sum over a column duplicated by a join. No average of averages; no sum of ratios. Totals reconcile to an independent source or to the sum of parts. Distinct counts are not summed across overlapping groups. | Fix the join or aggregate at the correct grain first. Re-run reconciliation. |
| 2 | Boundary, off-by-one, and sign conventions | Interval ends: inclusive vs exclusive stated and tested. Empty input, single element, first and last element. Index base 0 vs 1. Date boundaries: time zone, month end, leap day, period start vs end. Sign: debit vs credit, long vs short, inflow vs outflow, return vs loss; one convention per module. Division by zero and denominators near zero. Units and scale (percent vs fraction, basis points, thousands). | Add a test for the failing boundary. Fix. Re-run. |
| 3 | Zero silent exception swallowing | No bare `except`, empty `catch`, `except: pass`, `|| true`, `2>/dev/null` on a required step, `IFERROR(..., 0)`, `fillna` or `coalesce` that masks missing data, or ignored return code in the diff. Every caught error is re-raised, converted to a specific recovery, or reported with context. | Remove the swallow. Let it fail or handle it explicitly. |
| 4 | Net lines of code added vs removed | Report `+added / -removed / net`. Bug fix or refactor: net <= 0 expected; net > 0 needs one sentence of justification per +20 lines. Feature: every added function has >= 1 call site and >= 1 test. Zero unused symbols introduced. | Consolidate (2.1) or delete (2.3) until justified. |

Adversarial procedure:

- IF a claim is "fixed", "passing", or "verified" -> THEN it MUST cite a command run after the last edit and its actual output.
- IF verification was not run -> THEN say "not verified" and state why.
- IF a test was written after the fix -> THEN confirm it fails without the fix.
- IF the result is numeric -> THEN try to break it: one independent recomputation by a different method, one extreme input, one empty input.
- IF the author and the verifier are the same worker on Tier 3-mandatory work (3.2) -> THEN route verification to a separate Tier 3 pass with a fresh brief.

### 6.2 Overturn rule

- IF new test output, a recomputation, or a derivation contradicts any earlier statement in the thread -> THEN the earlier statement is void. State: `OVERTURNED: <earlier claim> | Evidence: <output> | Corrected: <new claim>`.
- IF the overturned claim supported later work -> THEN re-check every dependent conclusion before output.
- IF evidence conflicts with the user's stated assumption -> THEN report the evidence first; do not build on the assumption.
- IF evidence and a prior plan conflict -> THEN evidence wins. Consistency with earlier turns has zero weight.
- IF no new evidence exists -> THEN do not reverse (C9); pressure alone is not evidence.

---

## 7. ASD-STE100 PROGRESSIVE DISCLOSURE HANDOFFS

### 7.1 Simplified Technical English rules

| Rule | Requirement |
|---|---|
| H1 Headline first | Sentence 1 states the conclusion or result. Background comes after. |
| H2 One idea per sentence | One instruction or one fact per sentence. |
| H3 Sentence length | Instructions <= 20 words. Descriptions <= 25 words. |
| H4 No forward references | Define every term, label, and abbreviation before or at first use. Never "see below" for something undefined. |
| H5 Active voice, present tense | "The function returns X." Not "X will be returned." |
| H6 One word, one meaning | Use one term per concept for the whole document. Do not alternate synonyms. |
| H7 Concrete nouns | Name the file, function, value, and unit. No "it", "this", or "the issue" without a clear referent in the same sentence. |
| H8 No filler | No hedging chains, preamble, praise, or restating the request. |
| H9 Standalone | The reader has no access to working context. No invented labels, no shorthand from the session. |
| H10 Numbers with units | Every number has a unit and a source (command, file, or computation). |

### 7.2 Progressive disclosure order

| Layer | Content | Reader can stop after it and still act |
|---|---|---|
| L1 | One-sentence conclusion. | Yes. |
| L2 | 3-bullet handoff (7.3). | Yes. |
| L3 | Evidence: commands, outputs, `path:line` references. | — |
| L4 | Detail: alternatives rejected, assumptions made (A3), limitations. | — |

- IF a layer is not needed for the reader's next action -> THEN omit it.
- IF a decision is required from the reader -> THEN place it in L1 with a recommended option.

### 7.3 Standalone 3-bullet handoff (mandatory at the end of every deliverable)

```
- Verified Findings: <facts confirmed by executed evidence; each with command or path:line>
- Changes Made: <files changed and effect; +added/-removed/net lines; "none" if none>
- Open Next Step: <exactly one next action, its owner, and any blocker; "none" if complete>
```

- IF a finding is not verified by executed evidence -> THEN it does not go under Verified Findings; label it "unverified" in L4.
- IF tests fail -> THEN Verified Findings states the failure and the output.
- IF the handoff needs the conversation to be understood -> THEN rewrite it.

---

## APPENDIX: DROP-IN `CLAUDE.md` BLOCK (200 words)

```markdown
## Staff Engineering Standard (enforced; full text: STAFF_ENGINEERING_STANDARD.md)

1. SCOPE: Before editing, state the symptom, root cause, and broken invariant (data grain, state, or math). Reproduce first. Resolve ambiguity from the repository. Ask only about intent, irreversible actions, or conflicting requirements.
2. MINIMAL DIFF: Fix the cause at its source. Merge duplicate helpers into one parameterized function (target: 75% fewer). Never add wrappers. Delete dead code and unused imports in the same pass. No speculative guards. No unrelated reformatting.
3. ROUTING: Keep 1-3 step tasks in one loop. Split only independent work with disjoint files. Tier 1 finds. Tier 2 builds. Tier 3 designs and verifies. Escalate to Tier 3 after 2 consecutive failures or any invariant conflict. Brief every worker: Goal | Scope & Files | Invariants | Return Format.
4. CONTEXT: Search symbols before reading. Read ranges, not files. Never re-read unchanged files. Keep context append-only.
5. OBSTACLES: Diagnose and route around timeouts, empty searches, lint failures, and test failures. Halt on off-limits files, destructive deletions, and missing credentials.
6. AUDIT before output: grain and double counting; boundaries, off-by-one, signs; no swallowed exceptions; net lines added versus removed. New evidence overturns earlier claims. Say so.
7. HANDOFF: Conclusion first. One idea per sentence. Define terms before use. End with: Verified Findings | Changes Made | Open Next Step.
```
