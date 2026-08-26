# Single analysis — korak po korak

## Što je Single analysis

Single analysis radi kompletnu multi-agent analizu **jednog tickera** i završava izvještajem Portfolio Managera. Ne kupuje ni ne prodaje, ne koristi virtualni cash i ne mijenja `db/portfolio.sqlite`.

Kratki tok:

```text
Pokretanje
  → odabir Single analysis
  → unos tickera i zajedničkih postavki
  → analiza podataka
  → dvije rasprave i plan trgovanja
  → završna ocjena Portfolio Managera
  → spremanje izvještaja
```

## 1. Odabir načina rada

Na prvom izborniku odaberi:

```text
Single analysis — analyze one ticker without virtual trading
```

CLI tada uključuje `paper_trading=False`. Zbog toga se sav kod za virtualnu kupnju i prodaju preskače.

## 2. Unos tickera

Unosi se jedan ticker, primjerice:

```text
CCJ
```

Ticker se normalizira prije analize:

- mala slova pretvaraju se u velika;
- `BTCUSD` postaje `BTC-USD`;
- `XAUUSD` postaje `GC=F`;
- prazni unos postaje `SPY`;
- sufiks burze mora biti dio tickera kada je potreban, primjerice `0700.HK` ili `AZN.L`.

Aplikacija zatim automatski određuje radi li se o dionici ili cryptu. Za crypto se Fundamentals Analyst ne nudi.

## 3. Odabir datuma analize

Datum se unosi kao:

```text
YYYY-MM-DD
```

Budući datum nije dopušten. Tržišna analiza koristi podatke dostupne do tog datuma. Završni rezultat ipak može ovisiti o izvorima koji se mijenjaju, osobito vijestima i sentimentu.

## 4. Odabir jezika izvještaja

Odabrani jezik vrijedi za izvještaje i završne odluke. Hrvatski nije zasebna stavka u popisu, pa treba odabrati `Custom language` i upisati:

```text
Croatian
```

Isto se može unaprijed postaviti u `.env`:

```text
TRADINGAGENTS_OUTPUT_LANGUAGE=Croatian
```

Kad je varijabla postavljena, CLI preskače pitanje o jeziku.

## 5. Odabir Analyst Teama

Mora se odabrati najmanje jedan analitičar:

- **Market Analyst** — cijena, volumen, tehnički indikatori i verificirani market snapshot;
- **Sentiment Analyst** — Yahoo vijesti, StockTwits i Reddit sentiment;
- **News Analyst** — vijesti o tickeru, globalne vijesti, makro podaci i prediction markets;
- **Fundamentals Analyst** — fundamenti, bilanca, cash flow i račun dobiti i gubitka.

Bez obzira kojim ih redom označiš, izvršavaju se fiksnim redom:

```text
Market → Sentiment → News → Fundamentals
```

Neodabrani analitičar potpuno se preskače. Za crypto se Fundamentals automatski izostavlja.

## 6. Odabir dubine istraživanja

Dubina određuje koliko puta se agenti izmjenjuju u dvije kasnije rasprave:

| Dubina | Vrijednost | Bull/Bear govora | Risk govora |
|---|---:|---:|---:|
| Shallow | 1 | 2 | 3 |
| Medium | 3 | 6 | 9 |
| Deep | 5 | 10 | 15 |

Veća dubina obično znači više LLM poziva, dulje trajanje i veći trošak. Ne jamči bolju odluku.

Ako su postavljeni `TRADINGAGENTS_MAX_DEBATE_ROUNDS` ili `TRADINGAGENTS_MAX_RISK_ROUNDS`, njihove vrijednosti imaju prednost nad interaktivnim odabirom.

## 7. Odabir LLM providera i modela

CLI traži:

1. LLM provider i endpoint;
2. quick model;
3. deep model;
4. provider-specific thinking/reasoning postavku, ako postoji.

Quick model koriste Analyst Team, Bull, Bear, Trader i tri Risk analitičara. Deep model koriste Research Manager i Portfolio Manager.

Ako API ključ nedostaje, CLI ga može zatražiti i spremiti u `.env`. Postavke zadane kroz podržane `TRADINGAGENTS_*` varijable preskaču odgovarajuća pitanja.

## 8. Priprema analize

Nakon zadnjeg pitanja aplikacija:

1. sastavlja konfiguraciju runa;
2. stvara quick i deep LLM klijente;
3. registrira odabrane agente i njihove alate;
4. pokušava razriješiti stvarni identitet instrumenta iz tickera;
5. stvara početno stanje s tickerom, datumom, vrstom instrumenta i praznim izvještajima.

Ako dohvat identiteta tvrtke ne uspije, analiza se nastavlja s dostupnim tickerom.

## 9. Analyst Team prikuplja podatke

Odabrani analitičari rade jedan za drugim. Market, News i Fundamentals mogu više puta zatražiti alat, dobiti podatke i ponovno razmišljati prije završnog izvještaja.

```text
Analitičar
  → traži podatke
  → alat vraća podatke
  → analitičar ih obrađuje
  → po potrebi traži još podataka
  → završava svoj report
```

Market Analyst mora koristiti verificirani snapshot kao izvor istine za precizne OHLCV i cjenovne tvrdnje. Nedostupan vanjski izvor može vratiti placeholder ili, u važnom koraku, prekinuti run.

## 10. Bull i Bear raspravljaju

Nakon zadnjeg odabranog analitičara počinje research rasprava:

```text
Bull Researcher → Bear Researcher → ponavljanje prema dubini
```

- Bull gradi slučaj za ulaganje.
- Bear ističe rizike i odgovara na Bullove argumente.
- Oba koriste već izrađene analyst reporte; ne obavljaju novu tržišnu kupnju niti prodaju.

## 11. Research Manager stvara investicijski plan

Research Manager čita cijelu Bull/Bear raspravu i daje:

- preporuku `Buy`, `Overweight`, `Hold`, `Underweight` ili `Sell`;
- obrazloženje;
- konkretne strateške korake za Tradera.

To još nije završna odluka sustava.

## 12. Trader stvara transakcijski prijedlog

Trader pretvara Research Managerov plan u prijedlog:

- `Buy`, `Hold` ili `Sell`;
- kratko obrazloženje;
- opcionalni entry price;
- opcionalni stop-loss;
- opcionalni prijedlog veličine pozicije.

Trader nema brokerski priključak i ne izvršava order. Njegov izlaz je tekst koji ide Risk Management timu.

## 13. Risk Management raspravlja

Risk agenti rade ovim redom:

```text
Aggressive → Conservative → Neutral → ponavljanje prema dubini
```

- Aggressive naglašava upside i prihvaća veći rizik.
- Conservative naglašava zaštitu kapitala i downside.
- Neutral pokušava uravnotežiti obje strane.

Oni čitaju Traderov plan, prethodne reporte i dosadašnju risk raspravu. Ne dohvaćaju nove podatke i ne trguju.

## 14. Portfolio Manager daje završnu odluku

Portfolio Manager koristi deep model i spaja:

- plan Research Managera;
- prijedlog Tradera;
- cijelu Risk Management raspravu.

Završni izvještaj ima jednu od pet ocjena:

| Ocjena | Značenje unutar analize |
|---|---|
| `Buy` | jaka preporuka za ulaz ili povećanje pozicije |
| `Overweight` | povoljan pogled i postupno povećanje izloženosti |
| `Hold` | zadržavanje bez akcije |
| `Underweight` | smanjenje izloženosti |
| `Sell` | izlaz ili izbjegavanje ulaza |

U Single analysis načinu to ostaje **preporuka u izvještaju**. Ne postoji virtualna ni stvarna transakcija.

## 15. Što se prikazuje tijekom runa

Live ekran prikazuje:

- status agenata;
- nedavne poruke i pozive alata;
- zadnju ažuriranu sekciju izvještaja;
- broj LLM i tool poziva;
- tokene kada ih provider prijavi;
- proteklo vrijeme i vrijeme pojedinih analitičara.

Na kraju se svi streamani dijelovi spajaju u završno stanje.

## 16. Gdje se spremaju rezultati

Tijekom izvršavanja nastaju radni izvještaji i log:

```text
~/.tradingagents/logs/<TICKER>/<DATUM>/
├── message_tool.log
└── reports/
    ├── market_report.md
    ├── sentiment_report.md
    ├── news_report.md
    ├── fundamentals_report.md
    ├── investment_plan.md
    ├── trader_investment_plan.md
    └── final_trade_decision.md
```

Pišu se samo odabrane i stvarno nastale sekcije.

Po završetku se u direktoriju iz kojeg je CLI pokrenut stvara uređeno stablo:

```text
reports/<TICKER>_<TIMESTAMP>/
├── 1_analysts/
├── 2_research/
├── 3_trading/
├── 4_risk/
├── 5_portfolio/
│   └── decision.md
└── complete_report.md
```

CLI zatim pita želiš li prikazati puni izvještaj na ekranu. Enter prihvaća zadani odgovor `Y`.

## 17. Što Single analysis ne radi

- Ne koristi niti mijenja paper portfolio.
- Ne kupuje niti prodaje stvarnu imovinu.
- Ne uspoređuje ticker s drugim kandidatima za isti kapital.
- Ne jamči isti rezultat pri ponovljenom runu.
- Ne jamči da će svi vanjski izvori biti dostupni.

## Trenutačna ograničenja CLI implementacije

Ove razlike važne su ako se oslanjaš na persistence funkcije opisane drugdje u projektu:

1. Interaktivni CLI postavlja checkpoint opciju, ali trenutačno direktno streama kompajlirani graf bez spajanja SQLite checkpointera. Zbog toga se na `--checkpoint` ne treba oslanjati za resume ovog CLI toka.
2. Interaktivni CLI ne prolazi kroz programatsku `propagate()` putanju koja učitava i ažurira dugoročnu decision memory. CLI sprema Markdown izvještaje i `message_tool.log`, ali ne sprema decision memory ni `full_states_log_<date>.json` iz te programatske putanje.
3. Kod `docker compose run --rm tradingagents`, `~/.tradingagents` ostaje u Docker volumeu, ali završni `/home/appuser/app/reports` nije montiran na host u trenutačnom Composeu. Taj završni folder može nestati kada se privremeni kontejner ukloni.

Ako želiš da završni Docker izvještaji ostanu izravno u projektu, Compose servisu treba dodati bind mount:

```yaml
volumes:
  - ./reports:/home/appuser/app/reports
```
