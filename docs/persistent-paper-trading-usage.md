# Persistent Paper trading — pokretanje i namjena

## Čemu služi

Ovaj modul je forward-test za TradingAgents odluke. Virtualni račun, cash, svaka
odluka, order, fill, pozicija i dnevna vrijednost spremaju se u novu SQLite bazu.
Ne šalje prave naloge brokeru.

## 1. Konfiguracija

Kopiraj `.env.example` u `.env`, unesi API ključ za odabrani LLM i po potrebi
postavi:

```dotenv
TRADINGAGENTS_PAPER_DB_PATH=./db/paper_trading_v2.sqlite
TRADINGAGENTS_PAPER_ACCOUNT=uranium-test
TRADINGAGENTS_PAPER_INITIAL_CASH=1000
TRADINGAGENTS_PAPER_BUY_NOTIONAL=20
TRADINGAGENTS_PAPER_OVERWEIGHT_NOTIONAL=10
TRADINGAGENTS_PAPER_MAX_POSITION_PCT=0.20
TRADINGAGENTS_PAPER_CASH_RESERVE_PCT=0.10
TRADINGAGENTS_PAPER_SLIPPAGE_BPS=5
TRADINGAGENTS_PAPER_BENCHMARK=URA
```

Strategijska pravila kopiraju se u account kod stvaranja. Kasnija promjena `.env`
ne mijenja pravila već pokrenutog eksperimenta; za druga pravila napravi drugi
account.

## 2. Izrada računa

Ovaj korak je opcionalan jer ga prvi Paper run može napraviti automatski.

```bash
tradingagents paper account-create --name uranium-test --cash 1000 --benchmark URA
```

Docker:

```bash
docker compose run --rm tradingagents paper account-create \
  --name uranium-test --cash 1000 --benchmark URA
```

Ako account već postoji, naredba ga samo prikaže i ne dodaje novih `$1,000`.

## 3. Prvi dnevni run

```bash
docker compose run --rm tradingagents
```

Odaberi `Paper trading`, unesi watchlistu i datum. Prvi run analizira tickere i u
bazu sprema odluke te `PENDING` naloge. Ne izvršava ih istim Closeom; zato će cash
neposredno nakon prvog runa još biti nepromijenjen.

## 4. Idući dnevni run

Pokreni isti postupak s kasnijim datumom. Na početku runa sustav:

1. učita account i saldo iz baze;
2. pronađe ranije `PENDING` naloge;
3. izvrši ih po prvom tržišnom Open-u nakon odluke;
4. zapiše fill, promjenu casha i poziciju;
5. tek zatim analizira novu dnevnu watchlistu.

Ako je `CCJ Buy $20` izvršen, account više nema `$1,000` casha nego približno
`$980`, uz moguću malu razliku zbog slippagea.

## 5. Pregled računa

```bash
docker compose run --rm tradingagents paper account-list
docker compose run --rm tradingagents paper account-show --account uranium-test
docker compose run --rm tradingagents paper trades --account uranium-test
docker compose run --rm tradingagents paper stats --account uranium-test
```

Razdoblje se može ograničiti:

```bash
docker compose run --rm tradingagents paper stats \
  --account uranium-test --from 2026-01-01 --to 2026-03-31
```

## 6. CSV i JSON export

```bash
docker compose run --rm tradingagents paper export --account uranium-test
```

Rezultat je u `exports/<account>_<timestamp>/`:

```text
account_summary.json
cash_ledger.csv
daily_portfolio.csv
daily_positions.csv
decisions.csv
orders.csv
trades.csv
ticker_summary.csv
```

Docker Compose mapira `db/`, `reports/` i `exports/` na host, pa podaci prežive
gašenje jednokratnog containera.

## 7. Izravni SQL

```bash
sqlite3 -header -column db/paper_trading_v2.sqlite
```

Zatim koristi upite iz [paper-trading-sql-queries.md](paper-trading-sql-queries.md).

## 8. Pravila za valjan eksperiment

- koristi zaseban account za svaku verziju strategije;
- ne mijenjaj početni kapital usred eksperimenta;
- pokreći istu watchlistu i dosljedan dnevni termin;
- ne zaključuj iz nekoliko trgovina; gledaj dulje razdoblje i benchmark;
- backupiraj `db/paper_trading_v2.sqlite` prije većih promjena.

