# Persistent Paper trading — pokretanje i namjena

## Čemu služi

Ovaj modul je forward-test za TradingAgents odluke. Virtualni račun, cash, svaka
odluka, order, fill, pozicija i dnevna vrijednost spremaju se u novu SQLite bazu.
Ne šalje prave naloge brokeru.

## 1. Konfiguracija

### MySQL i migracije

Za MySQL 8.0.16 ili noviji u lokalni `.env` upiši:

```dotenv
DB_CONNECTION=mysql
DB_HOST=host.wmd-ssd3.com
DB_PORT=3306
DB_DATABASE=lara242
DB_USERNAME=lara242
DB_PASSWORD=unesi_lozinku
```

Instaliraj ažurirane ovisnosti i pokreni migracije:

```bash
python -m pip install -e ".[dev]"
tradingagents db migrate
```

Ako koristiš Docker:

```bash
docker compose build tradingagents
docker compose run --rm tradingagents db migrate
```

Baza navedena u `DB_DATABASE` mora već postojati. Korisnik treba prava za izradu
tablica, indeksa, veza, viewa i triggera te čitanje i pisanje podataka. Migracije
bilježe verziju u `schema_migrations`; ponavljanje naredbe ne briše podatke.
MySQL naredbe za Paper trading provjeravaju verziju sheme i traže pokretanje
migracija ako shema još nije spremna.

Ista MySQL baza koristi se za popis tickera, analize, račune, naloge i statistiku.
Lozinka ostaje u okruženju i ne sprema se u konfiguraciju analize.
Migracija izrađuje MySQL shemu; ne kopira postojeće podatke iz SQLite baze.

Za SQLite postavi `DB_CONNECTION=sqlite` i `TRADINGAGENTS_PAPER_DB_PATH`.
Naredba `tradingagents db migrate` podržava i SQLite. Ako `DB_CONNECTION` nije
postavljen, prisutan `DB_HOST` odabire MySQL; inače se koristi SQLite.

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

U oba Paper trading načina CLI traži odabir jednog ili više aktivnih računa.
Razmaknica označava račun, Enter potvrđuje odabir. Prikazuju se naziv i saldo.
Svaki odabrani račun obrađuje se zasebno, uz iste tickere i datum. Postavka
`TRADINGAGENTS_PAPER_ACCOUNT` ne zamjenjuje ovaj interaktivni odabir.

Tickere možeš unaprijed spremiti u zajednički popis u bazi:

```bash
tradingagents paper symbols add AAPL MSFT URA
tradingagents paper symbols list
tradingagents paper symbols pause AAPL
tradingagents paper symbols resume AAPL
tradingagents paper symbols disable MSFT
tradingagents paper symbols enable MSFT
```

U Dockeru koristi prefiks `docker compose run --rm tradingagents`, primjerice:

```bash
docker compose run --rm tradingagents paper symbols add AAPL MSFT URA
```

Odaberi **Paper trading — use tickers from database** za učitavanje tickera bez
ručnog unosa. Obrađuju se samo zapisi sa statusom `ACTIVE` i `paper_enabled = 1`.
Datum i postavke analize biraš jednom za cijeli popis. Prazan popis zaustavlja
pokretanje uz uputu za dodavanje tickera. Ova opcija ne zakazuje dnevna pokretanja.

Svaki ticker ima jedinstven zapis u tablici `instruments`, a njegove odluke u
`decisions` povezane su preko `instrument_id`. Spremanje odluke automatski dodaje
novi ticker; postojeći pauzirani ili isključeni ticker zadržava svoje postavke.
`pause`/`resume` mijenjaju status, a `disable`/`enable` oznaku za Paper trading.
Popis vrijedi za sve virtualne račune.

Prvo otvaranje postojeće SQLite baze automatski migrira shemu s v2 na v3, popunjava
tickere iz postojećih zapisa i povezuje stare odluke. Naziv datoteke baze ostaje
isti. Migrirani tickeri početno su aktivni i uključeni za Paper trading.

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
