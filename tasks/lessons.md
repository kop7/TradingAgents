# Lessons

## Paper trading scope

- When the user asks how Paper trading works, distinguish the current executor from the complete evaluation system they actually want.
- A useful long-running paper-trading system needs more than persistent cash and positions: it also needs portfolio-aware allocation, an auditable cash ledger, daily valuation snapshots, reproducible execution timing, and statistics over a selected period.
- State explicitly which requested capabilities already exist and which require implementation, instead of presenting the current partial implementation as the finished target.
- When the user authorizes a completely new database, prefer a clean versioned schema at a new path and leave the legacy database untouched instead of spending complexity on an unnecessary migration.

- A recoverable external failure in a long-running Paper Trading batch must not
  escape as a CLI traceback. Persist the failed/resumable run, avoid creating
  orders without valid decisions, and give the operator an actionable retry
  message.
