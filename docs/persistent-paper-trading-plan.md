# Plan: trajni Paper trading račun i statistika kroz X dana

## 1. Cilj

Cilj je napraviti virtualni račun koji se ponaša kao stvarni račun unutar SQLite baze:

- račun se kreira jednom s početnim iznosom, primjerice `$1,000`;
- svaki novi run učitava isti cash i postojeće pozicije iz baze;
- `BUY` stvarno smanjuje virtualni cash u bazi;
- `SELL` vraća virtualni novac na isti račun;
- aplikacija se može ugasiti i ponovno pokrenuti bez gubitka stanja;
- svaka analiza, odluka, narudžba, kupnja, prodaja i promjena casha ostaje zabilježena;
- svaki dan sprema se vrijednost cijelog portfelja;
- nakon 30, 60 ili X dana može se izračunati je li strategija zaradila, izgubila i pobijedila benchmark.

Ovo je **stvarna promjena virtualnog salda u bazi**, ali nije povezivanje bankovnog ili brokerskog računa niti trgovanje pravim novcem.

## 2. Što već postoji, a što nedostaje

Postojeći `PaperPortfolio` već:

- stvara račun s početnim cashom;
- učitava postojeći cash iz `db/portfolio.sqlite`;
- kod kupnje smanjuje cash;
- kod prodaje povećava cash;
- vodi količinu, prosječnu cijenu i realized P&L;
- sprječava dvostruko izvršenje istog tickera i datuma.

Za pouzdanu višednevnu evaluaciju još nedostaje:

- imenovani račun vezan uz jedan eksperiment;
- audit zapis svake promjene casha;
- razdvojeni zapisi analize, odluke, ordera i stvarnog virtualnog fill-a;
- analiza cijele watchliste prije raspodjele kapitala;
- portfolio-aware alokacija koja vidi cash i sve pozicije;
- pošteno pravilo vremena izvršenja bez look-aheada;
- dnevno vrednovanje svih otvorenih pozicija;
- dnevna equity krivulja i benchmark;
- statistika po portfelju, tickeru i zatvorenoj poziciji;
- siguran nastavak prekinutog runa;
- neinteraktivna dnevna naredba pogodna za scheduler.

## 3. Glavna promjena workflowa

Trenutačni tok radi ovo:

```text
analiziraj CCJ → odmah potroši cash
analiziraj UEC → odmah potroši preostali cash
analiziraj DNN → odmah potroši preostali cash
```

Zbog toga redoslijed watchliste odlučuje tko prvi dobiva novac.

Preporučeni tok je:

```text
1. učitaj account, cash i sve pozicije
2. osvježi vrijednost svih otvorenih pozicija
3. analiziraj sve tickere bez trgovanja
4. spremi sve završne odluke
5. Portfolio Allocator vidi cijelu listu i stanje računa
6. napravi jedan zajednički plan prodaja i kupnji
7. spremi pending ordere za sljedeću tržišnu sesiju
8. na toj sesiji prvo izvrši prodaje, zatim kupnje
9. spremi cash ledger, fillove, pozicije i dnevni snapshot
```

Time agent više ne troši novac samo zato što je njegov ticker prvi u watchlisti.

## 4. Jedan account predstavlja jedan eksperiment

Preporuka je da svaki test ima zaseban imenovani račun:

```text
Account: uranium-fixed-20-v1
Initial cash: $1,000
Currency: USD
Benchmark: URA
Duration: 30 trading sessions
Watchlist: CCJ, UEC, DNN, NXE, UUUU, URG, EU, UROY, LEU, AEC, ISOU
Strategy version: uranium-fixed-20-v1
```

Pravila računa zamrzavaju se na početku testa. Ne treba usred 30-dnevnog testa mijenjati veličinu ordera, benchmark ili position limit jer se tada uspoređuju dvije različite strategije.

Za početni MVP preporučene su postavke:

```text
buy notional: $20
overweight notional: $10
max position: 20% total equityja
minimum cash reserve: 10% total equityja
fractional shares: uključene
short, margin i leverage: isključeni
fee: $0, ali polje postoji
slippage: 5 basis points, konfigurabilno
```

Iznosi moraju biti konfigurabilni. Fiksnih `$20` je dobar početni profil jer je lako provjeriti je li svaki dolar pravilno skinut s računa.

## 5. Dnevni ciklus od početka do kraja

### Korak 1: učitavanje računa

Run prima obvezni `account` i iz baze učitava:

- raspoloživi cash;
- sve otvorene pozicije;
- zadnji daily snapshot;
- watchlistu;
- strategiju i risk limite;
- otvorene naloge iz prethodnog dana;
- datum zadnjeg uspješno završenog runa.

Početni cash koristi se samo pri kreiranju računa. Običan run ga nikad ne smije ponovno postaviti.

### Korak 2: izvršenje ranije pripremljenih naloga

Nalozi generirani nakon zatvaranja dana D izvršavaju se na prvoj sljedećoj burzovnoj sesiji.

Prije promjene računa sustav mora imati valjanu cijenu za svaki order koji utječe na zajedničku alokaciju. Mrežni dohvat cijena radi se prije otvaranja DB transakcije.

### Korak 3: mark-to-market svih pozicija

Sustav dohvaća novu cijenu za **svaku otvorenu poziciju**, ne samo za ticker koji se trenutno analizira.

```text
market value = quantity × aktualna closing cijena
total equity = cash + zbroj market valuea
```

Ako važna otvorena pozicija nema valjanu cijenu, allocator se ne smije praviti da je equity pouzdan. Run ostaje u statusu koji se može retryati.

### Korak 4: analiza cijele watchliste

Svaki ticker prolazi postojeći multi-agent pipeline, ali u ovoj fazi cash se ne mijenja.

Za svaki ticker sprema se:

- `Buy`, `Overweight`, `Hold`, `Underweight` ili `Sell`;
- cijeli Portfolio Manager report;
- opcionalni conviction/opportunity score;
- price target i time horizon;
- data cutoff i datum odluke;
- model i konfiguracija;
- status analize i eventualna greška;
- putanja i hash spremljenog reporta.

Uspješno završena analiza ne šalje se ponovno LLM-u pri resumeu istog runa.

### Korak 5: zajednički portfolio plan

Tek kad su sve analize u završnom statusu, allocator dobiva:

- cash;
- total equity;
- sve otvorene pozicije;
- sve nove odluke;
- limit po tickeru;
- cash rezervu;
- sizing pravilo;
- verziju strategije.

Neuspjela analiza ne smije otvoriti novu poziciju. Ako već postoji pozicija u tom tickeru, fallback je `Hold`, uz jasno zapisanu grešku.

### Korak 6: prvo plan prodaja

Pravila:

| Odluka | Plan |
|---|---|
| `Sell` | prodaj 100% postojeće količine |
| `Underweight` | prodaj 50% postojeće količine |
| `Hold` | ne mijenjaj poziciju |

Prodaje se računaju prve jer oslobađaju cash za kasnije kupnje.

### Korak 7: zatim plan kupnji

Za fiksni `$20` profil:

```text
Buy request = $20
Overweight request = $10

dozvoljeni iznos = minimum od:
- traženog iznosa
- slobodnog prostora do position limita
- casha iznad obvezne rezerve
```

Primjer:

```text
Cash prije:       $100
CCJ decision:     Buy
Izvršeni notional: $20
Cash poslije:      $80
CCJ quantity:      $20 / execution price
Cash ledger:       -$20
```

Ako je dozvoljeni iznos manji od konfiguriranog minimalnog ordera, order dobiva `NOOP` ili `REJECTED` i razlog, primjerice:

- `INSUFFICIENT_CASH`;
- `POSITION_AT_LIMIT`;
- `CASH_RESERVE_LIMIT`;
- `NO_VALID_PRICE`;
- `NO_OPEN_POSITION`.

Ako nema dovoljno casha za sve kandidate:

1. `Buy` ima prednost pred `Overweight`;
2. viši strukturirani conviction ima prednost;
3. ticker služi samo kao stabilni zadnji tie-break;
4. ista lista odluka mora dati istu alokaciju bez obzira na redoslijed watchliste.

Za prvu verziju može se izbjeći LLM confidence i raspoloživi cash proporcionalno podijeliti svim `Buy` kandidatima, zatim `Overweight` kandidatima. To je jednostavnije i manje osjetljivo na proizvoljnu samoprocjenu modela.

### Korak 8: spremanje ordera i atomsko izvršenje na sljedećoj sesiji

Novi orderi najprije se spremaju kao `PENDING` sa zakazanom prvom sljedećom tržišnom sesijom. U ovom trenutku još ne mijenjaju cash ni poziciju.

Kada ta sesija stigne, Korak 2 učitava pending ordere, dohvaća izvršne cijene i radi lokalno virtualno izvršenje u kratkoj SQLite transakciji:

```text
BEGIN IMMEDIATE
  → provjeri account i run revision
  → izvrši sve prihvatljive SELL naloge
  → potvrdi stvarni raspoloživi cash
  → izvrši BUY naloge
  → upiši fillove
  → upiši cash-ledger stavke
  → ažuriraj pozicije
  → povećaj account revision
COMMIT
```

Ako lokalni korak ne uspije, radi se rollback. Ne smije postojati fill bez promjene casha niti promjena casha bez fill-a.

Vanjski LLM ili market-data pozivi nikad se ne rade dok je DB zaključan.

### Korak 9: dnevni snapshot

Na kraju svake sesije, nakon izvršenja ranije zakazanih ordera i vrednovanja pozicija, spremaju se:

- cash;
- svaka otvorena pozicija;
- closing cijena svake pozicije;
- market value;
- total equity;
- realized i unrealized P&L;
- net deposits/withdrawals;
- benchmark vrijednost;
- dnevni i kumulativni rezultat.

Snapshot mora biti jedinstven po `account + valuation date`. Ponovni run istog dana ažurira ili vraća isti logički snapshot bez dupliciranja naloga i fillova.

## 6. Pošteno vrijeme izvršenja

Za stvarnu provjeru kvalitete preporučeno pravilo je:

```text
nakon zatvaranja dana D:
  analiza koristi samo podatke dostupne do D closea
  odluka i order spremaju se u bazu

prva sljedeća tržišna sesija:
  order se puni po open cijeni + konfigurirani slippage
```

Ne treba analizirati close dana D i zatim tvrditi da je order izvršen po istom closeu. U stvarnom vremenu ta konačna cijena nije bila poznata prije donošenja odluke.

Vikend i praznik znače prvu sljedeću valjanu tržišnu sesiju, ne sljedeći kalendarski dan.

MVP treba biti **forward paper test** od dana pokretanja. Povijesni backtest s današnjim news i sentiment izvorima nije pošten jer ti izvori nisu point-in-time.

## 7. Ciljna baza

### `accounts`

Identitet računa, naziv, valuta, status, strategija i revision. Cash se ne resetira pri pokretanju.

### `cash_ledger`

Append-only izvor istine za svaki virtualni dolar:

```text
INITIAL_FUNDING  +1000
BUY                -20
SELL               +24
FEE                 -1
DEPOSIT            +100
WITHDRAWAL          -50
```

Saldo računa dobiva se zbrojem ledgera. Aplikacija može imati view `account_balances` za brzo učitavanje salda.

Ledger stavke se ne mijenjaju i ne brišu. Ispravak je nova eksplicitna `ADJUSTMENT` stavka.

### `analysis_runs`

Jedan zapis za jedan dnevni ciklus: account, decision date, watchlista, zamrznuta konfiguracija, strategija, status, početak, kraj i greška.

Predloženi statusi:

```text
CREATED → VALUATING → ANALYZING → PLANNED
        → EXECUTING → SNAPSHOTTED → COMPLETED
```

Dodatni statusi: `PARTIAL_ANALYSIS`, `FAILED`, `CANCELLED`.

### `decisions`

Jedan rezultat analize po tickeru i runu, neovisno o tome je li order izvršen.

### `orders`

Što je allocator pokušao napraviti: side, requested notional/quantity, zakazana sesija, status i razlog odbijanja.

### `fills`

Samo stvarno izvedene virtualne kupnje i prodaje: količina, raw cijena, effective cijena, gross notional, fee, slippage, realized P&L i vrijeme izvršenja.

`Hold` i odbijeni order nisu fillovi.

### `positions`

Trenutačna projekcija po `account + ticker`: quantity, average cost, last price i datum cijene.

### `portfolio_daily_snapshots`

Jedna završna vrijednost računa po danu.

### `position_daily_snapshots`

Sve pozicije koje čine portfolio snapshot toga dana.

### `price_snapshots`

Cijena korištena za odluku, fill ili valuation, zajedno s izvorom i timestampom.

### `schema_migrations`

Verzija i checksum svake migracije baze.

## 8. Preciznost novca i količine

Nove novčane zapise ne treba spremati kao `REAL`.

Preporuka:

- Python izračuni koriste `Decimal`;
- novac i cijene spremaju se kao integer micro-dollars;
- količine se spremaju kao integer nano-units;
- zaokruživanje je eksplicitno i jednako u aplikaciji i testovima.

Time se nakon stotina transakcija cash neće razlikovati zbog float pogrešaka.

Obvezni invarianti:

```text
cash >= 0
quantity >= 0
BUY cash change = -(notional + fee)
SELL cash change = +(notional - fee)
cash = zbroj cash-ledger stavki
equity = cash + market value svih pozicija
```

## 9. Idempotency i nastavak prekinutog runa

Potrebni jedinstveni ključevi:

- run: `account + strategy version + decision date`;
- decision: `run + ticker`;
- order: trajni `client_order_key`;
- fill: trajni `fill_key`;
- ledger: `account + idempotency_key`;
- daily snapshot: `account + valuation date`.

Ponovno pokretanje:

- pronalazi postojeći run;
- preskače već završene analize;
- ne stvara drugi order, fill ni ledger zapis;
- retrya samo nedovršene korake;
- završava istim rezultatom kao jedan neprekinuti run.

Nedostajuća završna ocjena mora biti greška analize, a ne tihi `Hold`. Stvarni `Hold` mora biti eksplicitna spremljena odluka.

## 10. Nova v2 baza

Na zahtjev korisnika v2 koristi potpuno novu bazu:

```text
db/paper_trading_v2.sqlite
```

Postojeći `db/portfolio.sqlite` ostaje netaknut kao legacy zapis. Stari cash, odluke i pozicije ne prenose se u novi eksperiment i zato ne mogu iskriviti novu statistiku.

Nova baza i dalje koristi `PRAGMA user_version` i `schema_migrations` kako bi buduće promjene v2 sheme bile kontrolirane. Equity krivulja počinje od prvog funding zapisa novog accounta.

## 11. CLI koji treba izgraditi

```bash
tradingagents paper account create \
  --name uranium-fixed-20-v1 \
  --cash 1000 \
  --currency USD

tradingagents paper account show \
  --account uranium-fixed-20-v1

tradingagents paper run \
  --account uranium-fixed-20-v1 \
  --watchlist "CCJ,UEC,DNN,NXE,UUUU,URG,EU,UROY,LEU,AEC,ISOU"

tradingagents paper resume --run-id <RUN_ID>

tradingagents paper positions --account uranium-fixed-20-v1

tradingagents paper trades \
  --account uranium-fixed-20-v1 \
  --from 2026-09-01 \
  --to 2026-10-01

tradingagents paper stats \
  --account uranium-fixed-20-v1 \
  --from 2026-09-01 \
  --to 2026-10-01 \
  --benchmark URA

tradingagents paper export \
  --account uranium-fixed-20-v1 \
  --output ./exports/uranium-fixed-20-v1
```

`paper run` mora imati neinteraktivni način rada. Account, watchlista, strategija, modeli i ostale postavke tada dolaze iz spremljenog profila ili argumenata, pa se ista naredba može pokretati schedulerom.

## 12. Statistika nakon X dana

### Stanje portfelja

- početni kapital;
- trenutačni cash;
- market value;
- total equity;
- net deposits i withdrawals;
- realized P&L;
- unrealized P&L;
- ukupan neto P&L;
- ukupni i dnevni return.

### Rizik i kvaliteta

- equity curve;
- maksimalni drawdown;
- volatilnost dnevnih prinosa;
- najbolji i najgori dan;
- Sharpe i Sortino, uz upozorenje za mali uzorak;
- prosječna cash rezerva i tržišna izloženost;
- turnover;
- ukupni fees i procijenjeni slippage.

### Usporedba

- benchmark return;
- alpha;
- relative return;
- opcionalna usporedba sa `SPY` uz primarni uranium benchmark.

Za uranium eksperiment preporučeni primarni benchmark je `URA`. Benchmark se odabire na početku i ne mijenja tijekom testa.

Benchmark simulacija počinje s istim početnim kapitalom i prvim dopuštenim execution datumom kao strategija. Ako se kasnije radi deposit ili withdrawal, isti vanjski cash flow mora se primijeniti i na benchmark ili se prinos mora računati time-weighted metodom.

Osnovne formule:

```text
net P&L = final equity - initial funding - net deposits
portfolio return = final strategy value / početna usporediva vrijednost - 1
benchmark return = final benchmark value / početna benchmark vrijednost - 1
alpha = portfolio return - benchmark return
relative return = (1 + portfolio return) / (1 + benchmark return) - 1
```

### Po tickeru

- ukupno kupljeno;
- ukupno prodano;
- trenutačna količina i cost basis;
- trenutna market value;
- realized, unrealized i total P&L;
- broj kupnji i prodaja;
- broj dana u poziciji;
- maksimalno angažirani kapital;
- doprinos ukupnom rezultatu;
- najbolji i najgori ticker.

### Po zatvorenom ciklusu pozicije

- win rate;
- prosječan dobitak;
- prosječan gubitak;
- profit factor;
- expectancy;
- prosječno trajanje dobitne i gubitne pozicije.

Win rate se računa kada ticker ide od količine nula, preko otvorene pozicije, ponovno na nulu. Djelomična prodaja nije sama po sebi završeni trade ciklus.

Za manje od 20 dnevnih prinosa Sharpe i slične annualizirane metrike treba označiti kao nedovoljno pouzdane. Za kraće testove primarno gledati total return, drawdown i benchmark razliku.

## 13. Export podataka

Minimalni export:

```text
account_summary.json
trades.csv
cash_ledger.csv
daily_portfolio.csv
daily_positions.csv
ticker_summary.csv
decisions.csv
orders.csv
```

Svaki trade red mora sadržavati barem:

```text
account, run, decision_at, execution_at, ticker, rating,
side, quantity, raw_price, effective_price, gross_notional,
fee, cash_before, cash_after, realized_pnl, status
```

CSV zbrojevi moraju biti jednaki DB i ekranskom reportu.

## 14. Faze implementacije

### Faza 1: zaključati pravila eksperimenta

- potvrditi `$20` fixed sizing;
- potvrditi cash rezervu i max position;
- potvrditi D+1 open execution;
- odabrati benchmark;
- zamrznuti strategy version.

**Rezultat:** jednoznačna pravila koja se mogu testirati.

### Faza 2: baza v2 i account repository

- dodati migrations;
- dodati imenovane račune;
- dodati immutable cash ledger;
- koristiti precizan novac i količine;
- stvoriti novu `paper_trading_v2.sqlite` bez diranja legacy baze.

**Rezultat:** račun preživljava restart i svaki dolar ima objašnjenje.

### Faza 3: runs, decisions, orders i fills

- odvojiti LLM odluku od pokušaja ordera i stvarnog filla;
- dodati statuse i idempotency;
- omogućiti resume bez ponovnog trošenja LLM poziva.

**Rezultat:** potpuna audit povijest svakog dnevnog runa.

### Faza 4: analyze-all-then-allocate

- najprije završiti sve analize;
- allocatoru dati cash, pozicije i sve odluke;
- prodaje planirati prije kupnji;
- ukloniti ovisnost o redoslijedu watchliste.

**Rezultat:** kapital se raspoređuje na razini cijelog portfelja.

### Faza 5: executor bez look-aheada

- spremiti pending ordere na dan D;
- izvršiti ih na prvoj sljedećoj tržišnoj sesiji;
- dodati fee/slippage;
- atomski ažurirati fill, ledger i poziciju.

**Rezultat:** poštena i ponovljiva virtualna izvršenja.

### Faza 6: dnevni mark-to-market i snapshotovi

- osvježiti cijene svih otvorenih pozicija;
- spremiti account i position snapshotove;
- pratiti benchmark na iste datume.

**Rezultat:** pouzdana equity krivulja.

### Faza 7: statistika i export

- napraviti `status`, `positions`, `trades`, `stats` i `export` naredbe;
- izračunati osnovne i per-ticker metrike;
- dodati CSV/JSON izvještaje.

**Rezultat:** nakon X dana može se jasno ocijeniti strategija.

### Faza 8: automatizacija i hardening

- neinteraktivni profil;
- scheduler;
- lock protiv dva istovremena runa;
- retry privremenih market/LLM grešaka;
- backup baze;
- trajni Docker mount za reports i exports.

**Rezultat:** sustav može samostalno raditi svaki trgovinski dan.

## 15. Obvezni testovi i acceptance kriteriji

### Glavni novčani scenarij

```text
1. Kreiraj account sa $100.
2. BUY $20 po cijeni $10.
3. Baza mora pokazati cash $80, quantity 2 i ledger -$20.
4. Ugasi i ponovno pokreni aplikaciju.
5. Mora ponovno učitati cash $80 i quantity 2.
6. SELL cijelu poziciju po cijeni $12.
7. Baza mora pokazati cash $104, quantity 0 i realized P&L +$4.
8. Ponovi isti run.
9. Cash, pozicija, fill i ledger ne smiju se drugi put promijeniti.
```

### Dodatni obvezni scenariji

1. Dva accounta nikad ne dijele cash, pozicije ili trades.
2. BUY smanjuje cash točno za notional i fee.
3. SELL povećava cash točno za proceeds umanjen za fee.
4. Namjerno izazvana DB greška rollbacka fill, ledger i poziciju.
5. Cash nikad ne može pasti ispod nule.
6. Pozicija nikad ne može postati negativna.
7. Signal dana D ne može se izvršiti po closeu dana D.
8. Vikend i praznik biraju sljedeću stvarnu sesiju.
9. Stara ili nedostupna cijena ne mijenja account.
10. SELL/Underweight planira se prije novih kupnji.
11. Promjena redoslijeda watchliste ne mijenja alokaciju.
12. Prekid nakon dijela analiza može se nastaviti bez duplikata.
13. Ponovni executor ne duplicira order, fill ni ledger.
14. Svaka otvorena pozicija dobiva dnevni price i snapshot.
15. `cash + market value = total equity`.
16. Poznati fixture daje očekivani realized i unrealized P&L.
17. Poznata equity serija daje točan maksimalni drawdown.
18. Benchmark i portfelj koriste iste valuation datume.
19. CSV, DB i ekranski report daju iste zbrojeve.
20. Inicijalizacija v2 ne mijenja hash ni sadržaj postojeće `portfolio.sqlite` baze.

## 16. Predložena organizacija koda

Postojeći `tradingagents/paper_trading.py` ne treba nastaviti širiti u jednu veliku datoteku. Predložena podjela je:

```text
tradingagents/paper/
├── database.py       # konekcije, PRAGMA postavke i transakcije
├── migrations.py     # schema version, backup i v1 → v2 migracija
├── repository.py     # accounts, runs, decisions, orders i upiti
├── money.py          # Decimal konverzije i integer units
├── allocator.py      # portfolio plan bez ovisnosti o redoslijedu watchliste
├── executor.py       # fills, ledger i positions u atomskoj transakciji
├── valuation.py      # price snapshots i dnevni mark-to-market
├── statistics.py     # portfolio, benchmark i per-ticker metrike
└── exports.py        # CSV/JSON izlazi

cli/paper.py           # paper account/run/resume/stats/export naredbe
```

Postojeći `PaperPortfolio` treba privremeno ostati kao compatibility adapter dok se CLI i testovi ne prebace na novu strukturu. Tako migracija može ići u manjim, provjerljivim koracima.

Novi testovi trebaju biti razdvojeni po odgovornosti:

```text
tests/test_paper_migrations.py
tests/test_paper_accounts.py
tests/test_paper_ledger.py
tests/test_paper_allocator.py
tests/test_paper_executor.py
tests/test_paper_valuation.py
tests/test_paper_statistics.py
tests/test_paper_cli.py
tests/test_paper_resume.py
```

Market prices i LLM odluke u testovima moraju dolaziti iz determinističkih fixturea, bez mreže.

## 17. Definicija gotovog MVP-a

MVP je gotov kada možemo napraviti ovaj dokaz:

```text
kreiraj account → pokreni više dnevnih runova → ugasi aplikaciju
→ ponovno je pokreni → nastavi s istim cashom i pozicijama
→ izvezi sve kupnje/prodaje → prikaži dnevnu equity krivulju
→ usporedi rezultat s benchmarkom za isti period
```

Prva uporabna verzija treba obuhvatiti faze 1–7. Scheduler iz faze 8 može doći odmah nakon što je ručni `paper run` dokazano idempotentan i financijski točan.

## 18. Što nije dio ovog plana

- povezivanje pravog brokera;
- pravi novac;
- short selling;
- margin i leverage;
- opcije i kompleksni derivati;
- porezni obračun;
- intraday order book simulacija;
- povijesni backtest s današnjim news/sentiment podacima.

Te funkcije ne treba dodavati prije nego što osnovni long-only virtualni račun i njegove statistike budu potpuno provjereni.
