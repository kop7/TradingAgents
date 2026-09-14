# Izvještaji analize: sadržaj, značenje i spremanje u bazu

## Migracija i pokretanje

Shema v4 dodaje tablicu `analysis_reports`, relacije i indekse. Postojeći računi,
tickere, odluke, nalozi, izvršenja i saldo ne mijenjaju se. Ponovljena migracija
ne duplicira tablicu ni zapise.

```bash
dkc -f docker-compose.override.yml --profile ollama build tradingagents tradingagents-ollama
dkc -f docker-compose.override.yml run --rm tradingagents db migrate
```

Za lokalnu instalaciju koristi `tradingagents db migrate`. MySQL koristi `DB_*`
postavke iz `.env`; SQLite je podržan i automatski nadograđuje lokalnu shemu.
Kod MySQL-a migraciju izvrši prije analize, uključujući Single analysis.

## Kako su izvještaji povezani

Svaki generirani Markdown dokument ima vlastiti zapis:

| Kolona | Značenje |
| --- | --- |
| `id` | ID izvještaja |
| `instrument_id` | Strani ključ na ticker u `instruments` |
| `run_id` | Paper trading run u `analysis_runs`; preko njega je dostupan račun |
| `execution_key` | `paper:<run_id>` ili jedinstveni `single:<uuid>` |
| `report_type` | Relativni naziv Markdown dokumenta naveden u nastavku |
| `content_markdown` | Cijeli tekst, uključujući naslove, tablice i formatiranje |
| `analysis_date` | Datum za koji je analiza izvršena |
| `created_at` | UTC vrijeme prvog spremanja ovog zapisa u bazu |
| `updated_at` | UTC vrijeme posljednjeg spremanja |
| `content_hash` | SHA-256 sadržaja u UTF-8 |

Single analysis ima NULL `run_id`: ne stvara virtualni račun. Sve njegove sekcije
dijele isti `execution_key`. Paper trading veza čuva odvojenost računa čak i kad
analiziraju isti ticker i datum. Jedinstvenost je po tickeru, izvršenju i vrsti
izvještaja. Ponovno spremanje istog izvještaja ažurira tekst i hash uz očuvanje
`created_at`; to nije povijest svih revizija. Novo izvršenje ima zasebne zapise.

Spremanje je integrirano u završetak CLI analize za oba načina. Generirani paket
sprema se transakcijski prije završne potvrde analize. Prazne ili neodabrane sekcije
ne stvaraju prazne zapise. Markdown datoteke nastavljaju se generirati. Ovo nije
spremanje nakon svakog agentskog koraka: prekid prije završnog stanja ne garantira
izvještaje u ovoj tablici. Programatski `write_report_tree` i dalje je samo writer
datoteka; za vlastitu API integraciju pozovi `render_reports` i `repo.save_reports`.

## 1. Market Analyst — `1_analysts/market.md`

Analiza kretanja cijene, trenda i dostupnih tehničkih pokazatelja. Služi za
razumijevanje tržišnog konteksta i tehničkih argumenata. Provjeri datum podataka,
trend i razloge zaključka. Tehnički signal sam po sebi nije nalog ni obećanje
budućeg kretanja. Sadržaj ovisi o dostupnim alatima i podacima.

## 2. Sentiment Analyst — `1_analysts/sentiment.md`

Procjenjuje raspoloženje iz dostupnih društvenih i drugih sentiment izvora.
Može sadržavati smjer, ocjenu i pouzdanost. Koristan je za uočavanje optimizma,
straha ili neslaganja s cijenom. Niska pokrivenost, pristranost objava i nedostatak
podataka ograničavaju zaključak; pozitivan sentiment nije isto što i povoljan ulaz.

## 3. News Analyst — `1_analysts/news.md`

Sažima relevantne vijesti i moguće katalizatore. Čitaj datume objave i događaja,
izvore i procjenu utjecaja. Pomaže objasniti promjenu cijene ili povećanu
neizvjesnost. Vijest može već biti uračunata u cijenu; razlikuj činjenice od
interpretacije agenta i poštuj datum analize.

## 4. Fundamentals Analyst — `1_analysts/fundamentals.md`

Razmatra dostupne financijske podatke, poslovanje, profitabilnost, dug i valuaciju.
Koristan je za dugoročniji kontekst nasuprot kratkoročnom kretanju cijene.
Provjeri izvještajno razdoblje, valutu i pokrivenost podataka. Ne očekuj iste
metrike za dionice, ETF-ove, futures i kripto; kod nekih instrumenata ova sekcija
nije odabrana ili se namjerno izostavlja.

## 5. Bull Researcher — `2_research/bull.md`

Povijest optimistične strane istraživačke debate: argumenti za rast i odgovori
na negativne argumente. Koristi se za razumijevanje pozitivne investicijske teze.
To je namjerno jedna strana debate, ne neovisna konačna preporuka.

## 6. Bear Researcher — `2_research/bear.md`

Povijest skeptične strane debate: rizici, slabosti i argumenti protiv ulaganja.
Pomaže provjeriti što bi moglo poništiti pozitivnu tezu. Nije automatski SELL
nalog; usporedi dokaze s Bull izvještajem.

## 7. Research Manager — `2_research/manager.md`

Zaključak istraživačke debate i objedinjena investicijska teza. Objašnjava koje
argumente prihvaća i zašto. Ovo je ulaz za daljnji plan trgovanja; još nije
završna odluka nakon analize rizika.

## 8. Trader — `3_trading/trader.md`

Predloženi investicijski/trgovački plan temeljen na prethodnim izvještajima.
Čitaj predloženi smjer, obrazloženje i uvjete plana. Tekstualna preporuka ne
određuje izravno izvršenu količinu: Paper allocator primjenjuje pravila računa,
raspoloživi kapital, ograničenja pozicija i finalnu ocjenu.

## 9. Aggressive Risk — `4_risk/aggressive.md`

Argumenti sudionika debate koji više naglašava priliku i toleranciju rizika.
Služi za razumijevanje potencijala i razloga za snažniju izloženost. Ne znači
da je račun prebačen na agresivnu strategiju niti mijenja njegova ograničenja.

## 10. Conservative Risk — `4_risk/conservative.md`

Opreznija procjena plana: mogući gubici, nesigurnosti i razlozi za manju
izloženost ili odustajanje. Korisna je kao provjera pretpostavki. Nije izračun
zajamčenog maksimalnog gubitka ni zamjena za stvarna ograničenja rizika.

## 11. Neutral Risk — `4_risk/neutral.md`

Uravnotežuje agresivne i konzervativne argumente te razmatra kompromise.
Čitaj gdje se strane slažu, gdje ostaje neizvjesnost i koje uvjete predlaže.
Neutralan ton ne znači nužno HOLD preporuku.

## 12. Portfolio Manager — `5_portfolio/decision.md`

Finalna odluka nakon debate o riziku. Za Paper trading predstavlja izvor ocjene
BUY, OVERWEIGHT, HOLD, UNDERWEIGHT ili SELL. Prednost ima `final_trade_decision`,
a ako ga nema koristi se zaključak risk managera. Sažeta odluka ostaje i u
`decisions.raw_decision_text`; `analysis_reports` čuva Markdown izvještaj.
Finalna odluka nije dokaz da je nalog izvršen: za to provjeri `orders` i `fills`.

## 13. Objedinjeni izvještaj — `complete_report.md`

Sadrži zaglavlje s tickerom i vremenom generiranja te sve dostupne prethodne
sekcije. Koristan je za pregled jedne cijele analize i izvoz bez spajanja sekcija.
Zato namjerno ponavlja sadržaj pojedinačnih zapisa. Datum generiranja teksta i
`analysis_date` nisu nužno isti. Ne sadrži buduće izvršenje naloga ni kasniji P&L.

## SQL: pregled po tickeru, datumu i računu

```sql
SELECT ar.id, i.symbol, ar.analysis_date, ar.report_type,
       a.name AS account_name, ar.execution_key, ar.created_at, ar.updated_at
FROM analysis_reports ar
JOIN instruments i ON i.id = ar.instrument_id
LEFT JOIN analysis_runs r ON r.id = ar.run_id
LEFT JOIN accounts a ON a.id = r.account_id
WHERE i.symbol = 'UEC'
ORDER BY ar.analysis_date DESC, ar.execution_key, ar.report_type;
```

Za određeni račun dodaj `AND a.name = 'uranium'` iza uvjeta za ticker.
Single analysis će imati NULL `account_name`; filtriraj ga s `ar.run_id IS NULL`.

```sql
SELECT ar.content_markdown
FROM analysis_reports ar JOIN instruments i ON i.id = ar.instrument_id
WHERE i.symbol = 'UEC' AND ar.report_type = 'complete_report.md'
ORDER BY ar.created_at DESC, ar.id DESC LIMIT 1;
```

Za cijeli konkretan paket filtriraj `execution_key` i ticker. Sam datum ne
razlikuje više analiza istog dana ili različite račune.

## Uvoz starih datoteka

Migracija ne čita datoteke. Zasebna naredba uvozi poznate Markdown sekcije iz
direktorija na koje upućuje `decisions.report_path`:

```bash
tradingagents db import-reports
```

Docker mora imati pristup istim datotekama, primjerice:

```bash
dkc -f docker-compose.override.yml run --rm -v "$PWD/reports:/home/appuser/app/reports" tradingagents db import-reports
```

Uvoz preskače već postojeće izvještaje i ispisuje broj dodanih i broj odluka bez
dostupnih datoteka. `created_at` je vrijeme uvoza, ne izmišljeni povijesni datum.
Stari Single analysis izvještaji nemaju vezu u `decisions`, pa ova naredba njih
ne uvozi. Datoteke iz obrisanih kontejnera nije moguće vratiti samom migracijom.
