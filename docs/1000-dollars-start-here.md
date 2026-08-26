# Imam $1.000 i želim da TradingAgents trguje — kreni odavde

Ovaj vodič pretpostavlja da želiš dati sustavu **$1.000 virtualnog novca** i
pratiti kroz više dana je li dobar ili loš. Ova implementacija ne pristupa banci
ni brokeru i ne može kupiti prave dionice.

## Što će se dogoditi s tvojih virtualnih $1.000

Sustav će u SQLite bazi napraviti account sa saldom `$1.000`. Kada odluči kupiti
nešto za `$20`, na idućem tržišnom Open-u virtualni saldo stvarno postaje približno
`$980`, a baza dobiva poziciju, fill i ledger zapis. Prodaja vraća virtualni novac
u isti account.

```text
$1.000 virtualnog casha
  → analiza uranium tickera
  → odluke i pending nalozi
  → izvršenje na idućem Open-u
  → cash + pozicije + dnevna statistika u bazi
```

## Korak 1 — otvori projekt

```bash
cd /home/mkop/PhpstormProjects/TradingAgents
```

## Korak 2 — pripremi `.env`

Ako `.env` još ne postoji:

```bash
cp .env.example .env
```

U `.env` upiši API ključ za LLM provider koji koristiš. Zatim provjeri ili dodaj:

```dotenv
TRADINGAGENTS_PAPER_DB_PATH=./db/paper_trading_v2.sqlite
TRADINGAGENTS_PAPER_ACCOUNT=uranium-1000
TRADINGAGENTS_PAPER_INITIAL_CASH=1000
TRADINGAGENTS_PAPER_BUY_NOTIONAL=20
TRADINGAGENTS_PAPER_OVERWEIGHT_NOTIONAL=10
TRADINGAGENTS_PAPER_MAX_POSITION_PCT=0.20
TRADINGAGENTS_PAPER_CASH_RESERVE_PCT=0.10
TRADINGAGENTS_PAPER_SLIPPAGE_BPS=5
TRADINGAGENTS_PAPER_BENCHMARK=URA
```

Važno: naziv `uranium-1000` označava jedan eksperiment. Nemoj kasnije isti
account koristiti za drukčija pravila.

## Korak 3 — napravi account s $1.000

Docker naredba:

```bash
docker compose run --rm tradingagents paper account-create \
  --name uranium-1000 --cash 1000 --benchmark URA
```

Ako aplikaciju pokrećeš lokalno:

```bash
tradingagents paper account-create \
  --name uranium-1000 --cash 1000 --benchmark URA
```

Očekivani rezultat je account `uranium-1000` s cashom `1,000.00 USD`. Ponovno
izvršavanje iste naredbe neće dodati još $1.000.

## Korak 4 — pokreni prvi Paper trading dan

```bash
docker compose run --rm tradingagents
```

U izborniku napravi ovo:

1. odaberi `Paper trading`;
2. kao watchlistu zalijepi:

   ```text
   CCJ, UEC, DNN, NXE, UUUU, URG, EU, UROY, LEU, AEC, ISOU
   ```

3. odaberi današnji ili željeni povijesni datum;
4. odaberi analitičare, research depth i LLM modele;
5. pusti da svih 11 analiza završi.

Na kraju ćeš dobiti tablicu odluka i naloga. Primjer:

```text
CCJ  Buy          PENDING  BUY   $20
UEC  Hold         NOOP
DNN  Overweight   PENDING  BUY   $10
NXE  Sell         NOOP            nema otvorene pozicije
```

Cash je nakon prvog runa još `$1.000`, jer novi nalozi čekaju prvi sljedeći
tržišni Open. To je namjerno i sprječava look-ahead rezultat.

## Korak 5 — provjeri što je zapisano

```bash
docker compose run --rm tradingagents paper account-show \
  --account uranium-1000
```

Za pending naloge koristi SQL iz
[paper-trading-sql-queries.md](paper-trading-sql-queries.md), odjeljak
`Pending, NOOP i odbijeni nalozi`.

## Korak 6 — pokreni idući dan

Na sljedeći tržišni dan ponovno pokreni:

```bash
docker compose run --rm tradingagents
```

Opet odaberi Paper trading, istu watchlistu i novi datum. Prije nove analize
sustav izvršava jučerašnje pending naloge na prvom dostupnom Open-u.

Ako je jučer planirao `CCJ Buy $20`, sada ćeš vidjeti približno:

```text
Filled BUY CCJ: 0.xxxxxx @ $xx.xxxx
Cash: približno $980
Open positions: CCJ
```

Točan cash može biti malo drukčiji jer fractional quantity i slippage mijenjaju
stvarni virtualni notional za nekoliko centi.

## Korak 7 — ponavljaj kroz više dana

Svaki tržišni dan napravi isti postupak:

```text
pokreni CLI
  → Paper trading
  → ista watchlista
  → novi datum
  → pričekaj završetak
```

Ne mora svaki dan trgovati. `Hold`, pravilo cash rezerve, limit pozicije ili
nedostatak valjane cijene mogu ostaviti portfolio bez promjene.

## Korak 8 — provjeri je li dobar ili loš

Brzi pregled:

```bash
docker compose run --rm tradingagents paper stats \
  --account uranium-1000
```

Sve transakcije:

```bash
docker compose run --rm tradingagents paper trades \
  --account uranium-1000
```

CSV i JSON za daljnju analizu:

```bash
docker compose run --rm tradingagents paper export \
  --account uranium-1000
```

Gledaj najmanje ove brojeve:

- `Total equity`: cash plus vrijednost svih pozicija;
- `Total P&L`: ukupna dobit ili gubitak;
- `Return`: rezultat accounta u postotku;
- `Max drawdown`: najveći pad od prethodnog vrha;
- `Benchmark return`: koliko je u istom razdoblju napravio `URA`;
- `Alpha`: rezultat accounta minus rezultat benchmarka;
- `By ticker`: koji simboli su donosili, a koji gubili novac.

## Korak 9 — gdje su podaci

```text
db/paper_trading_v2.sqlite   glavni i trajni zapis eksperimenta
reports/                     objašnjenja agenata i finalne odluke
exports/                     CSV/JSON statistika
```

Backup baze:

```bash
cp db/paper_trading_v2.sqlite db/paper_trading_v2.backup.sqlite
```

## Najkraća dnevna checklista

```text
[ ] Koristim account uranium-1000
[ ] Unio sam novi datum
[ ] Koristim istu watchlistu i ista pravila
[ ] Run je završio bez FAILED tickera
[ ] Provjerio sam pending/fill rezultate
[ ] Povremeno pokrenem paper stats i paper export
[ ] Ne tumačim virtualni rezultat kao financijski savjet
```

