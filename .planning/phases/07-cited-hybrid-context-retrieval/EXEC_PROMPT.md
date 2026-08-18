You are executing a development milestone as part of GSS Orchestrator.
Superpowers TDD skill is active — invoke it via the Skills tool: invoke skill superpowers:test-driven-development

━━ MISSION ━━
Execute ALL unchecked [ ] tasks in PLAN.md using strict RED/GREEN/REFACTOR TDD.
Completed [x] tasks are done — do not redo them.
PLAN.md has already been refined by the Superpowers Brainstorming gate — read it carefully.

━━ GSTACK DECISIONS (authoritative) ━━
none

━━ BRAINSTORM DESIGN DOC (confirmed approach) ━━
none — read PLAN.md implementation hints directly

━━ SHARED CONTEXT ━━
none

━━ PLAN.md (refined with implementation details) ━━
# Phase 7: Cited Hybrid Context Retrieval

- [ ] Task 1: Create indexers for symbol, file, and source-span metadata with stable relative-path and line info on a ready version.
- [ ] Task 2: Implement context query combining exact symbol resolution, Postgres lexical/trigram search, and capped Joern graph expansion with deterministic ranking/deduplication.
- [ ] Task 3: Enforce budgets (item, byte, token, node, time) and mark truncation. Include citations (version digest, path, inclusive lines, symbol, selection reason) for each item.
- [ ] Task 4: Secure context operations to reject raw CPGQL on public endpoints while maintaining internal/admin access.
- [ ] Task 5: Add tests for cited context retrieval.

━━ TDD PROTOCOL ━━
Per task: RED (failing test) → GREEN (minimal impl) → REFACTOR → commit → mark [x]
Use BRAINSTORM DESIGN DOC and GSTACK DECISIONS as implementation guide during RED phase.

━━ AMBIGUITY HANDLING ━━
Design questions were resolved by the brainstorming gate before this execution started.
If BRAINSTORM_DOC + DECISIONS together answer the question → decide and proceed.
Only block if a scenario is genuinely uncovered by both documents:
  - Collect ALL remaining questions into: .planning/phases/07-cited-hybrid-context-retrieval/OPEN_QUESTIONS.md
  - Format: Q: <question> | Options: A)... B)... C)...
  - Output: <promise>PHASE_BLOCKED:QUESTIONS</promise>
  - Stop — do not guess.

━━ COMPLETION SIGNALS ━━
All tasks [x] and tests pass: <promise>PHASE_COMPLETE</promise>
Need GStack decision: <promise>PHASE_BLOCKED:<question with options></promise>
Technical blocker: <promise>PHASE_BLOCKED:TECH:<description></promise>

━━ ITERATION AWARENESS ━━
Max iterations: 15. Read PLAN.md from disk each iteration to see current [x] state.
