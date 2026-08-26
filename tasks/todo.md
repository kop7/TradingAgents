# Documentation plan: Single analysis and Paper trading

- [x] Inspect project rules, lessons, and current CLI/workflow structure.
- [x] Trace Single analysis from workflow selection through reports and memory.
- [x] Trace Paper trading from watchlist input through virtual execution and persistence.
- [x] Write a Croatian step-by-step guide in `docs/`.
- [x] Verify every documented behavior against implementation and tests.
- [x] Review the final diff and record verification results below.

## Review

- Added `docs/README.md` as the entry point and comparison.
- Added separate end-to-end guides for Single analysis and Paper trading.
- Cross-checked workflow, agent order, rating execution, persistence, duplicate handling, report paths, Docker mounts, and current CLI limitations against source and existing tests.
- Verified local Markdown links, heading structure, and absence of trailing whitespace; `git diff --check` is clean.
- Targeted tests could not be executed on the host because Python `pytest` is not installed (`python3 -m pytest` reports `No module named pytest`).
