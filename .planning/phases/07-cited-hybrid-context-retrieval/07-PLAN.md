# Phase 7: Cited Hybrid Context Retrieval

- [x] Task 1: Create indexers for symbol, file, and source-span metadata with stable relative-path and line info on a ready version.
- [x] Task 2: Implement context query combining exact symbol resolution, Postgres lexical/trigram search, and capped Joern graph expansion with deterministic ranking/deduplication.
- [x] Task 3: Enforce budgets (item, byte, token, node, time) and mark truncation. Include citations (version digest, path, inclusive lines, symbol, selection reason) for each item.
- [x] Task 4: Secure context operations to reject raw CPGQL on public endpoints while maintaining internal/admin access.
- [x] Task 5: Add tests for cited context retrieval.
