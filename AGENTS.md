# Repository Guide

## Project overview

TradingAgents is a Python research framework that uses LangChain/LangGraph agents
to analyze financial instruments. It offers single-instrument analysis and a
persistent, simulated paper-trading account through a Typer CLI. Paper trading
does not submit orders to a real broker.

## Code map

- `tradingagents/agents/`: analyst, researcher, trader, and risk-management agents;
  shared state, tools, prompts, and structured output schemas.
- `tradingagents/graph/`: graph construction, routing, execution, checkpoint resume,
  reflection, and signal processing.
- `tradingagents/dataflows/`: market-data vendors, routing in `interface.py`,
  symbol handling, caching, validation, and vendor errors.
- `tradingagents/llm_clients/`: provider factory, clients, API-key mappings, model
  catalog, and capability validation.
- `tradingagents/default_config.py`: defaults and environment-variable overrides.
- `tradingagents/paper/`: persistent account database, repository, allocation,
  execution, pricing, statistics, and exports. Also inspect
  `tradingagents/paper_trading.py` when changing shared paper-trading behavior.
- `cli/`: interactive workflows, configuration, paper-trading commands, and output.
- `tests/`: pytest regression suite and shared fixtures.
- `docs/`: workflow and paper-trading documentation, primarily in Croatian.

## Setup and commands

Python 3.10 or newer is required; CI tests Python 3.10–3.13. Run commands from the
repository root in an isolated Python environment.

```sh
python -m pip install -e ".[dev]"
python -m cli.main --help
python -m cli.main
python -m cli.main db migrate
python -m pytest -q
python -m ruff check .
```

For focused validation, run the relevant test module, for example:

```sh
python -m pytest -q tests/test_persistent_paper.py
```

CI also installs the package without development extras and verifies
`import tradingagents, cli.main`. Keep runtime dependencies declared in
`pyproject.toml`; `requirements.txt` installs the local package. Bedrock support
is an optional extra: `python -m pip install -e ".[dev,bedrock]"`.

## Implementation conventions

- Keep changes focused and preserve unrelated local edits.
- Follow nearby code and retain Python 3.10 compatibility. Ruff targets Python
  3.10 with a 100-character line length. Whole-repository formatting is explicitly
  deferred in `pyproject.toml`; avoid broad formatting churn.
- Extend existing configuration, provider, model, and vendor registries instead
  of duplicating mappings across entry points. Preserve lazy provider imports so
  importing the package does not require every optional SDK or API key.
- Keep graph state, structured output schemas, prompts, routing, and checkpoint
  compatibility consistent when changing agent behavior.
- Preserve analysis-date boundaries, stale-data checks, explicit no-data/error
  handling, and safe ticker-to-path conversion. Do not substitute invented market
  values for missing data or introduce future data into historical analyses.
- Preserve paper-trading invariants: deterministic shared-account allocation,
  idempotent repeated runs, append-only cash ledger, decimal money calculations,
  and execution at the first available market Open after the decision date.
- Update relevant user documentation when CLI behavior or configuration changes;
  retain the language of the document being edited.

## Validation and local state

- Add focused regression tests for behavior changes. Use mocks for LLM and vendor
  calls and temporary paths for databases, reports, checkpoints, and caches.
- `tests/conftest.py` supplies placeholder API keys and resets dataflow config;
  these fixtures do not themselves block network access. Explicitly mock external
  calls. Markers available are `unit`, `integration`, and `smoke`.
- Use pytest for automated validation. Root `test.py` and
  `scripts/smoke_structured_output.py` are manual scripts; inspect their external
  service requirements before running them.
- Run relevant tests and Ruff for code changes, broadening to the full suite when
  shared behavior changes. For documentation-only edits, check accuracy and
  `git diff --check`. Report what ran and any validation limitations.
- Never commit credentials or expose `.env` contents. Use `.env.example` and
  `.env.enterprise.example` to document configuration without secrets.
- MySQL paper storage uses `DB_CONNECTION=mysql` and `DB_HOST`, `DB_PORT`,
  `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD`. Run `tradingagents db migrate`
  explicitly for schema changes. Keep credentials out of analysis configs.
  MySQL integration tests use only `TEST_MYSQL_*` settings and disposable databases.
- CLI Markdown reports are stored in `analysis_reports` (schema v4) as well as
  files. `render_reports` is the shared renderer. Single analyses use an execution
  key without a paper account; paper reports link to `analysis_runs`. Historical
  file import is explicit via `tradingagents db import-reports`.
- Preserve existing local accounts and generated artifacts. The default SQLite paper
  account database is `db/paper_trading_v2.sqlite`; analysis logs, caches, and
  memory default under `~/.tradingagents`. Tests must use isolated storage rather
  than mutate these locations. Review staged files to exclude generated databases,
  exports, reports, caches, and local IDE settings.
