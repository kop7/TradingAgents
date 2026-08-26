# Paper trading — korak po korak

## Što je Paper trading

Paper trading analizira watchlistu i nakon svakog tickera završnu ocjenu Portfolio Managera primjenjuje na **jedan zajednički, trajni, long-only virtualni račun**.

Ne postoji veza s brokerom. Nema pravih naloga ni pravog novca.

```text
Watchlista
  → analiza prvog tickera
  → virtualna odluka za prvi ticker
  → analiza drugog tickera
  → virtualna odluka za drugi ticker
  → ...
  → završni prikaz stanja portfelja
```

## 1. Odabir načina rada

Na početnom izborniku odaberi:

```text
Paper trading — analyze a watchlist and trade the virtual portfolio
```

Time se uključuje paper-trading korak poslije svake završene analize tickera.

## 2. Unos watchliste

Tickeri se mogu odvojiti zarezom, razmakom ili novim redom. Za uranium watchlistu primjer je:

```text
CCJ, UEC, DNN, NXE, UUUU, URG, EU, UROY, LEU, AEC, ISOU
```

CLI:

1. provjerava format svakog tickera;
2. normalizira ga, primjerice `btcusd → BTC-USD`;
3. uklanja duplikate;
4. čuva redoslijed prvog pojavljivanja.

Watchlista nema programski zadanu maksimalnu duljinu. Veća lista znači više uzastopnih analiza, LLM poziva, vremena i troška.

## 3. Zajedničke postavke biraju se jednom

Nakon watchliste CLI na prvom tickeru traži iste postavke kao Single analysis:

- datum analize;
- jezik izlaza;
- Analyst Team;
- research depth;
- LLM provider i endpoint;
- quick i deep model;
- thinking/reasoning postavke.

Te postavke zatim vrijede za cijelu watchlistu. Ne pita ih ponovno za svaki ticker.

Vrsta instrumenta ipak se ponovno određuje za svaki simbol. Ako batch sadrži crypto, Fundamentals Analyst se za taj crypto ticker automatski uklanja.

Poseban slučaj: ako je **prvi ticker crypto**, Fundamentals se ne nudi u početnom izboru analitičara. Zbog zajedničkih postavki tada ga neće imati ni kasniji stock tickeri u istom batchu. Ako je prvi ticker dionica, Fundamentals se može odabrati, ali će se svejedno ukloniti samo na crypto tickerima.

## 4. Tickeri se obrađuju redom, ne paralelno

Za svaki ticker CLI kopira zajedničke postavke i pokreće kompletnu analizu:

```text
Odabrani Analyst Team
  → Bull/Bear
  → Research Manager
  → Trader
  → Aggressive/Conservative/Neutral
  → Portfolio Manager
```

Tek kada je prvi ticker potpuno gotov i njegova virtualna odluka obrađena, počinje sljedeći.

To znači da redoslijed watchliste može utjecati na rezultat izvršenja. Raniji `Buy` može potrošiti cash koji kasnijem tickeru više nije dostupan.

## 5. Svaki ticker dobiva neovisnu analizu

Agenti za jedan ticker ne dobivaju cijelu watchlistu, rang-listu svih kandidata ni trenutačni cash i pozicije virtualnog računa u svoj prompt.

Zato se ne događa ovo:

```text
analiziraj svih 11 → rangiraj najbolje → optimalno podijeli $1,000
```

Stvarno ponašanje je:

```text
analiziraj CCJ → pokušaj primijeniti odluku
analiziraj UEC → pokušaj primijeniti odluku
analiziraj DNN → pokušaj primijeniti odluku
...
```

Drugim riječima, agenti se ne natječu svjesno za kapital. Zajednički cash i limit pozicije mehanički se primjenjuju tek nakon što Portfolio Manager već donese odluku.

## 6. Portfolio Manager daje jednu od pet ocjena

Nakon pune analize dobiva se:

```text
Buy / Overweight / Hold / Underweight / Sell
```

Paper-trading sloj iz teksta deterministički izvlači ocjenu. Najprije traži eksplicitni `Rating: ...`; ako ga ne pronađe, traži prvu poznatu riječ. Ako ne uspije pronaći nijednu ocjenu, fallback je `Hold`.

## 7. Određivanje virtualne cijene izvršenja

Sustav dohvaća zadnju verificiranu, prilagođenu closing cijenu na datum analize ili prije njega. Cijena se odbija ako je zadnji raspoloživi podatak više od deset kalendarskih dana stariji od zadanog datuma.

Ako nema valjane closing cijene ili je cijena manja ili jednaka nuli, virtualna transakcija se ne obrađuje. Izvještaj analize može svejedno biti spremljen.

Nema bid/ask spreada ni stvarnog brokera. Za današnji datum kod ne provjerava izričito je li tržište već zatvoreno, pa se ne treba oslanjati na njega kao na preciznu brokersku end-of-day simulaciju.

## 8. Učitavanje trajnog portfelja

Defaultna baza je:

```text
db/portfolio.sqlite
```

Prvi put se stvaraju:

- `account` — početni cash i trenutačni cash;
- `positions` — količina, prosječna ulazna cijena i zadnja zapisana cijena po tickeru;
- `trades` — povijest svake obrađene odluke.

Defaulti su:

```text
initial cash = $1,000
max position = 20% ukupnog equityja
```

Mogu se promijeniti u `.env`:

```text
TRADINGAGENTS_PAPER_INITIAL_CASH=1000
TRADINGAGENTS_PAPER_MAX_POSITION_PCT=0.20
TRADINGAGENTS_PAPER_DB_PATH=./db/portfolio.sqlite
```

Važno: `initial cash` se upisuje samo kada se stvara novi račun. Promjena varijable poslije ne mijenja već postojeći račun u istoj bazi. Za potpuno novi račun koristi novu putanju baze. Brisanje postojeće baze briše cash, pozicije i cijelu povijest.

## 9. Izračun equityja i limita

Prije odluke računa se:

```text
market value pozicije = količina × zadnja zapisana cijena
total equity = cash + zbroj market valuea svih pozicija
limit tickera = total equity × max_position_pct
```

Za defaultnih `$1,000` i limit `20%`, ciljani maksimalni market value jednog tickera je `$200`, dok god je equity `$1,000`.

Dionice i crypto mogu se kupiti u decimalnim količinama; sustav podržava fractional quantity.

## 10. Kako se svaka ocjena izvršava

| Ocjena | Virtualna akcija |
|---|---|
| `Buy` | Kupuje koliko treba da ticker dođe do limita od 20% equityja, ali ne više od dostupnog casha. |
| `Overweight` | Dodaje najviše 10% equityja, bez prelaska ukupnog limita od 20% i bez prekoračenja casha. |
| `Hold` | Ne mijenja poziciju ni cash. |
| `Underweight` | Prodaje polovicu trenutačne količine. |
| `Sell` | Prodaje cijelu trenutačnu količinu i zatvara poziciju. |

Detalji:

- `Buy` na već otvorenoj poziciji nadopunjava je samo do limita.
- `Buy` ili `Overweight` na poziciji koja je već na limitu postaje `HOLD` bez transakcije.
- `Buy` ili `Overweight` bez dostupnog casha također postaje `HOLD`.
- `Underweight` ili `Sell` bez otvorene pozicije postaje `HOLD`.
- Svaka odluka, uključujući `Hold` i neizvršivi `Sell`, zapisuje se u povijest.

## 11. Primjer s početnih $1,000

Pretpostavimo redom tri ocjene i nepromijenjen equity:

```text
CCJ → Buy
UEC → Overweight
DNN → Hold
```

Tada sloj za izvršenje cilja otprilike:

```text
CCJ:  $200 market value
UEC:  $100 market value
DNN:  nema pozicije
Cash: $700
```

Ako kasniji ticker dobije `Buy`, može dobiti do 20% tadašnjeg equityja dok ima casha. Nema zasebne cash rezerve koju sustav mora sačuvati.

## 12. Zaštita od dvostrukog izvršenja

Kombinacija:

```text
normalizirani ticker + datum analize
```

može se obraditi samo jednom. Ako ponovno pokreneš isti ticker za isti datum:

1. puna LLM analiza se i dalje izvrši;
2. paper sloj nakon analize pronađe postojeći zapis;
3. ne radi drugu transakciju;
4. prikaže da je odluka već obrađena.

To vrijedi i ako je prvi zapis bio `HOLD` ili pokušaj prodaje bez pozicije.

Isti ticker s **novim datumom** smatra se novom odlukom i može proizvesti novu virtualnu transakciju.

## 13. Ažuriranje pozicije i dobiti/gubitka

Kod kupnje se ažuriraju:

- ukupna količina;
- ponderirana prosječna ulazna cijena;
- zadnja cijena;
- preostali cash.

Kod prodaje se izračunava realized P&L:

```text
prodana količina × (prodajna cijena - prosječna ulazna cijena)
```

Snapshot također prikazuje unrealized P&L, total equity i total return.

Važno ograničenje: pri obradi tickera osvježava se zadnja cijena samo tog tickera ako već ima otvorenu poziciju. Ostale pozicije zadržavaju svoju posljednju zapisanu cijenu. Zbog toga prikaz equityja nije automatski live mark-to-market cijelog portfelja.

## 14. Što se sprema nakon svakog tickera

Svaki ticker dobiva isto stablo Markdown izvještaja kao Single analysis:

```text
reports/<TICKER>_<TIMESTAMP>/
├── 1_analysts/
├── 2_research/
├── 3_trading/
├── 4_risk/
├── 5_portfolio/
│   └── decision.md
├── complete_report.md
└── paper_portfolio.json
```

`paper_portfolio.json` je snapshot **cijelog zajedničkog računa nakon tog tickera**, a ne zaseban portfelj samo za taj ticker.

Trajno stanje računa ostaje u SQLite bazi. Sljedeći Paper trading run nastavlja s postojećim cashom, pozicijama i poviješću; ne kreće ponovno s `$1,000`.

## 15. Što se prikazuje nakon odluke

CLI prikazuje:

- izvučenu ocjenu;
- stranu transakcije `BUY`, `SELL` ili `HOLD`;
- količinu i cijenu;
- poruku što je napravljeno;
- cash, vrijednost pozicija, total equity, realized i unrealized P&L;
- tablicu svih otvorenih pozicija.

Paper batch ne pita nakon svakog tickera želiš li puni izvještaj na ekranu. Nakon zadnjeg tickera ispisuje koliko je tickera obrađeno i popis analiza koje su završile iznimkom.

Greška samo jednog tickera u glavnoj analizi ne zaustavlja ostatak watchliste. Međutim, greška isključivo u virtualnom izvršenju hvata se unutar tog tickera, pa batch ticker može računati kao obrađen iako paper trade nije uspio; treba pročitati poruku `Paper trade could not be processed`.

## 16. Što Paper trading trenutačno nema

Nema:

- pravih brokerskih naloga;
- short pozicija, margine ili leveragea;
- provizije, spread, slippage, poreze ili FX konverziju;
- hard limit broja otvorenih pozicija;
- obveznu cash rezervu;
- minimalnu veličinu ordera;
- stop-loss/take-profit naloge koje automatski prati;
- automatsko osvježavanje cijena svih otvorenih pozicija;
- rangiranje cijele watchliste prije alokacije;
- portfolio-aware prompt za agente;
- automatski rebalans cijelog portfelja;
- jedinstveni objedinjeni report koji uspoređuje sve tickere;
- scheduler ili automatsko dnevno pokretanje.

Trader može u tekstu predložiti stop-loss ili sizing, ali paper izvršenje koristi samo završnu ocjenu Portfolio Managera i svoja fiksna pravila.

## 17. Koliko se pozicija može otvoriti

Ne postoji postavka `max_positions`.

Limit od 20% znači da pet punih `Buy` pozicija može približno potrošiti početnih `$1,000`, ali to nije hard limit od pet tickera. Primjerice, više `Overweight` odluka može otvoriti više manjih pozicija, a promjene cijena, djelomične prodaje i raspoloživi cash dodatno mijenjaju rezultat.

## 18. Docker persistence

Trenutačni Compose trajno montira:

- `./db` s hosta na `/home/appuser/app/db`, pa `portfolio.sqlite` ostaje na hostu;
- named volume na `/home/appuser/.tradingagents`, pa radni logovi ostaju u Docker volumeu.

Završni `/home/appuser/app/reports` nije montiran. Kod `docker compose run --rm tradingagents` završni Markdown reportovi i `paper_portfolio.json` mogu nestati s uklonjenim kontejnerom.

Za trajno spremanje završnih reportova na host treba dodati:

```yaml
volumes:
  - ./reports:/home/appuser/app/reports
```

SQLite portfelj u `./db/portfolio.sqlite` ostaje trajan i bez tog dodatnog mounta.

## 19. Što će se dogoditi s uranium watchlistom

Za:

```text
CCJ, UEC, DNN, NXE, UUUU, URG, EU, UROY, LEU, AEC, ISOU
```

sustav će:

1. prikupiti zajedničke postavke jednom;
2. potpuno analizirati `CCJ`;
3. pokušati izvršiti njegovu završnu ocjenu na zajedničkom računu;
4. spremiti CCJ report i snapshot;
5. prijeći na `UEC` i ponoviti isti postupak;
6. nastaviti zadanim redom do `ISOU`;
7. između tickera zadržavati promijenjeni cash i pozicije u istoj bazi.

Neće unaprijed znati da je, primjerice, `NXE` bolji kandidat od `CCJ`. Ako raniji tickeri potroše cash, kasniji `Buy` može završiti bez virtualne kupnje. Nakon `ISOU` proces završava; novo pokretanje moraš pokrenuti ručno ili ga zasebno zakazati izvan ove aplikacije.
