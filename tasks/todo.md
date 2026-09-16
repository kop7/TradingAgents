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

---

# Persistent paper-account implementation plan

- [x] Compare the requested long-running evaluation goal with the current SQLite executor.
- [x] Identify missing account, allocation, audit, snapshot, and statistics behavior.
- [x] Define the recommended end-to-end daily workflow and money-management rules.
- [x] Define the target database schema and safe migration path.
- [x] Define performance metrics, CLI outputs, test strategy, and acceptance criteria.
- [x] Save the implementation plan in `docs/` and link it from the documentation index.
- [x] Review the plan for correctness, sequencing, and scope.

## Review

- Added `docs/persistent-paper-trading-plan.md` and linked it from `docs/README.md`.
- The plan uses one persistent account per experiment, an append-only cash ledger, analyze-all-then-allocate, SELL-before-BUY execution, D+1 open fills, daily portfolio/position snapshots, benchmark tracking, exports, and resumable idempotent runs.
- Included a safe v1 → v2 migration that preserves the existing database and retains legacy tables for audit.
- Included phased implementation, proposed module boundaries, deterministic tests, and explicit MVP acceptance criteria.
- Verified headings, local links, balanced code fences, trailing whitespace, and `git diff --check`.

---

# Persistent paper trading implementation

- [ ] Implement the clean v2 SQLite schema, accounts, cash ledger, and repository in a new database.
- [ ] Implement deterministic analyze-all allocation, pending orders, D+1 execution prices, and atomic fills.
- [ ] Integrate persistent accounts and batch allocation into the interactive Paper trading workflow.
- [ ] Add account/status/positions/trades/stats/export CLI commands.
- [ ] Implement daily portfolio and position valuation snapshots plus benchmark tracking.
- [ ] Add statistics and CSV/JSON exports.
- [ ] Add SQL query examples and an end-to-end operating guide in new Markdown files.
- [ ] Leave the existing `db/portfolio.sqlite` untouched and use `db/paper_trading_v2.sqlite` for v2.
- [ ] Run focused tests, smoke the CLI, review the final diff, and document verification.

## Review

Pending.
