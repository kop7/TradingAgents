# Paper trading: računi, početni kapital i bulk tickeri

## 1. Ažuriranje aplikacije i migracije

Primjeri koriste `dkc` kao tvoj alias za `docker compose`.

```bash
dkc -f docker-compose.override.yml --profile ollama build tradingagents tradingagents-ollama
dkc -f docker-compose.override.yml run --rm tradingagents db migrate
```

MySQL se konfigurira u `.env` preko `DB_CONNECTION=mysql`, `DB_HOST`, `DB_PORT`,
`DB_DATABASE`, `DB_USERNAME` i `DB_PASSWORD`.

## 2. Kreiranje računa i početnog kapitala

Napravi račun `uranium` s 1.000 USD virtualnog kapitala:

```bash
tradingagents paper account-create --name uranium --cash 1000
```

Docker:

```bash
dkc -f docker-compose.override.yml run --rm tradingagents paper account-create --name uranium --cash 1000
dkc -f docker-compose.override.yml run --rm tradingagents paper account-list
dkc -f docker-compose.override.yml run --rm tradingagents paper account-show --account uranium
```

`--cash` određuje početni kapital novog računa. Ako račun već postoji, naredba
prikaže postojeći saldo: ne resetira ga i ne dodaje ponovno početni kapital.

Pri svakom pokretanju Paper tradinga CLI prikazuje aktivne račune i njihove
saldo iznose. Razmaknicom označi jedan ili više računa, a Enterom potvrdi.
Odabir je obavezan i kad postoji samo jedan račun. `TRADINGAGENTS_PAPER_ACCOUNT`
ne preskače ovaj odabir.

```bash
dkc -f docker-compose.override.yml --profile ollama run --rm tradingagents-ollama
```

Datum, tickere i postavke analize biraš jednom. Odabrani računi obrađuju se redom,
svaki sa svojim kapitalom, strategijom, analizama i nalozima. Ako jedan račun
ne može završiti obradu, CLI pokuša ostale i na kraju ispiše koji nisu uspjeli.
Pauzirani i zatvoreni računi nisu ponuđeni. Ako nema aktivnih računa, CLI ispiše
naredbu za kreiranje računa i završi.

Račun dijeli kapital među svim tickerima. Iznos početnog kapitala nije iznos
svake kupnje; iznosi kupnje i ograničenja portfelja dolaze iz strategije računa.

## 3. Bulk dodavanje tickera

```bash
tradingagents paper symbols add-bulk UEC CCJ DNN UEC
tradingagents paper symbols add-bulk "UEC, CCJ, DNN, NXE"
tradingagents paper symbols add-bulk --file tickers.txt
```

Datoteka treba biti UTF-8 tekst bez zaglavlja, s tickerima odvojenima zarezom,
razmakom ili novim redom. Primjer sadržaja:

```text
UEC, CCJ
DNN
NXE
UEC
```

Docker unos iz argumenata:

```bash
dkc -f docker-compose.override.yml run --rm tradingagents paper symbols add-bulk "UEC,CCJ,DNN,NXE,UEC"
```

Docker unos iz lokalne datoteke:

```bash
dkc -f docker-compose.override.yml run --rm -v "$PWD/tickers.txt:/tmp/tickers.txt:ro" tradingagents paper symbols add-bulk --file /tmp/tickers.txt
```

Naredba normalizira tickere i preskače duplikate iz unosa i one koji već postoje
u bazi. Ispisuje broj dodanih i preskočenih zapisa. Postojećim tickerima ne mijenja
status ni oznaku za Paper trading. Neispravan ticker zaustavlja cijeli unos prije
spremanja. `paper symbols add` podržava isti način unosa kao `add-bulk`.

Pregled i uključivanje/isključivanje:

```bash
tradingagents paper symbols list
tradingagents paper symbols disable UEC
tradingagents paper symbols enable UEC
tradingagents paper symbols pause CCJ
tradingagents paper symbols resume CCJ
```

## 4. Pokretanje i preskakanje obrađenih tickera

```bash
dkc -f docker-compose.override.yml --profile ollama run --rm tradingagents-ollama
```

Odaberi **Paper trading — use tickers from database**. Učitavaju se aktivni tickeri
kojima je uključen Paper trading. Opcija **analyze a watchlist** traži ručni unos.

Uspješna analiza preskače se pri ponovnom pokretanju **istog računa, datuma i
watchliste**. Ako su svi tickeri uspješno obrađeni, nova analiza i dupli nalozi
ne stvaraju se. Ako je obrada prekinuta ili dio tickera nije uspio, uspješne
analize ostaju spremljene, a neuspješne se pokušavaju ponovno.

Za novi datum ticker se ponovno analizira jer se tržišni podaci mijenjaju.
Drugi račun ima zaseban dnevni run. Postojeći dnevni run zahtijeva istu watchlistu;
promjenu popisa koristi na novom datumu. Raniji nalozi i vrednovanje portfelja
obrađuju se i kada nema novih analiza.
