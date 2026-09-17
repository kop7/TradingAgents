# Trading Cockpit — zaseban admin kontejner

Cockpit sadrži Overview, Analize, Izvještaje i Postavke računa. Pozicije i nalozi,
ticker detalj i usporedba računa ostaju sljedeća faza.

## Pokretanje

Postavi postojeće `DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME` i
`DB_PASSWORD` u lokalni `.env` ili okolinu. Kontejner dobiva samo navedene DB
postavke i `DB_CONNECTION=mysql`. Koristi udaljeni MySQL s postojećom shemom v4;
cockpit ne izvršava migracije. Pregled zahtijeva SELECT. Za spremanje postavki i
uplate DB korisnik dodatno treba UPDATE na `accounts` i INSERT na `cash_ledger`.
Prava DELETE ili promjene sheme nisu potrebna. Korisnik sa samo SELECT pravima
i dalje može pregledavati podatke, ali spremanje neće uspjeti.

```bash
docker compose -f docker-compose.admin.yml up -d --build admin
```

Otvori [localhost:8501](http://localhost:8501).
Ova Compose konfiguracija ima samo servis `admin`, vlastiti image i naziv projekta.
Ne pokreće analize, Ollamu ni lokalnu bazu i ne treba LLM ključeve.
Port je vezan samo na lokalno sučelje. Nema mountanja izvještaja ili baze.

Zaustavljanje samo admin dijela:

```bash
docker compose -f docker-compose.admin.yml down
```

Lokalno, izvan Dockera, u Python okolini projekta:

```bash
pip install -e ".[cockpit]"
tradingagents cockpit
```

## Korištenje i značenje podataka

- Odaberi račun i razdoblje. Single analysis je zaseban izbor bez računa.
- Overview prikazuje cash, equity i kumulativni realizirani/nerealizirani P&L
  zadnje spremljene valuacije u razdoblju. Ne prikazuje izmišljene nule ako
  valuacija nedostaje. Ticker i status filtri ne mijenjaju metrike cijelog računa.
- Graf prinosa i drawdown koristi postojeći `equity_curve`, uključujući korekciju
  za novčane tokove i raniju valuaciju kao početnu bazu kada postoji.
  Datumi cijena pozicija prikazuju se zasebno; starije cijene su označene.
  Cockpit ne dohvaća tržišne cijene niti osvježava valuacije.
- Dodatni grafovi prikazuju equity i kumulativne neto uplate, prinos portfelja
  naspram spremljenog benchmarka te odvojeni realizirani i nerealizirani P&L po
  tickeru. Benchmark bez početne vrijednosti nije dostupan; nedostajuće vrijednosti
  ne zamjenjuju se nulama. Realizirani P&L po tickeru obuhvaća izvršenja od početka
  razdoblja do prikazane valuacije, a nerealizirani je stanje pozicija na taj datum,
  uključujući pozicije kupljene prije razdoblja. Zato taj graf nije promjena ukupnog
  P&L-a tijekom razdoblja. Izvršenja poslije prikazane valuacije nisu uključena.
- Analize imaju filter datuma, točnog tickera i statusa runa, stranicu od 25
  zapisa, broj dovršenih/neuspješnih odluka i pregled grešaka. Traženi ticker bez
  odluke nije nužno neuspješan: run može još trajati ili biti prekinut.
- Izvještaji dolaze iz `analysis_reports`, za svih 13 vrsta koje sprema renderer.
  Biraju se prema tickeru, datumu, execution ključu i vrsti; tekst se učitava tek
  nakon odabira. Markdown je čitljiv i može se preuzeti. Nedostajuće vrste se ne
  generiraju. Single analysis nema status runa jer nema povezani paper run.
- Kratki cache traje 30 sekundi; Osvježi ga odmah prazni. Sve SQL vrijednosti
  vežu se parametrima, a pregled koristi READ ONLY transakcije. Pisanje se pokreće
  samo predajom obrasca na ekranu Postavke računa.

## Postavke računa i virtualne uplate

Odaberi paper račun pa **Postavke računa**. Ovaj ekran nije dostupan za Single
analysis. Datumski i ticker filtri ne utječu na izmjene računa.

- U obrascu Pravila kupnje promijeni BUY i OVERWEIGHT iznose, cash rezervu,
  maksimalni udio tickera i slippage. Postotke unosi kao `10` za 10%, a slippage
  u baznim bodovima (`5` znači 0,05%). Klikni **Spremi postavke**.
- Ostale strategijske postavke ostaju sačuvane. Istodobna izmjena računa odbija
  zastarjeli obrazac; klikni Osvježi i pregledaj nove vrijednosti prije ponovnog spremanja.
- Za primjenu pravila pokreni novi TradingAgents CLI proces. Već pokrenuti proces
  može imati ranije učitane postavke; prethodni izvještaji i nalozi se ne prepisuju.
- U obrascu Dodaj virtualni novac unesi pozitivan iznos i klikni **Uplati**.
  Dopuštena je decimalna točka ili zarez, bez separatora tisućica. Uplata dodaje
  novi `DEPOSIT` zapis u nepromjenjivi cash ledger i povećava reviziju računa.
- Nakon uspjeha obrazac pokazuje potvrdu; za dodatnu uplatu klikni **Nova uplata**.
  Ako veza pukne, ponovi isti zahtjev u istom obrascu: identifikator uplate
  sprečava dvostruko knjiženje. Nemoj otvarati novi tab radi ponavljanja nejasnog
  ishoda; prvo provjeri povijest uplata i saldo.
- Cash na ovom ekranu uključuje uplatu odmah nakon spremanja. Povijesne valuacije
  i grafovi ostaju nepromijenjeni do sljedeće redovne valuacije. Uplata se tada
  računa kao novčani tok, a ne zarada. Prikazuje se posljednjih 20 uplata.
- Zatvoreni računi i računi s nedovršenim runom ili PENDING nalozima ne mogu se
  mijenjati. Najprije dovrši obradu. Sve uplate su virtualne, bez brokera ili
  stvarnog prijenosa novca. Nova migracija nije potrebna.

Ako povezivanje ne uspije, provjeri mrežnu dostupnost udaljenog MySQL-a, DB
postavke i shemu v4. UI skriva detalje greške koji bi mogli sadržavati podatke
o vezi. Postojeće podatke i migracije održava glavni CLI.

Streamlit pokretanje i cache slijede službenu dokumentaciju:
[CLI](https://docs.streamlit.io/develop/api-reference/cli/run) i
[cache](https://docs.streamlit.io/develop/concepts/architecture/caching).
