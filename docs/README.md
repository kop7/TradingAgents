# Kako rade Single analysis i Paper trading

Ova dokumentacija opisuje **stvarno ponašanje trenutačne CLI implementacije** od pokretanja do završnog rezultata.

- [Single analysis — korak po korak](single-analysis.md)
- [Paper trading — korak po korak](paper-trading.md)
- [Pokretanje trajnog Paper trading računa](persistent-paper-trading-usage.md)
- [Imam $1.000 — točne početničke upute](1000-dollars-start-here.md)
- [SQL upiti za statistiku](paper-trading-sql-queries.md)
- [Plan trajnog Paper trading računa i statistike](persistent-paper-trading-plan.md)

## Najkraća razlika

| | Single analysis | Paper trading |
|---|---|---|
| Ulaz | Jedan ticker | Watchlista tickera |
| Analitički pipeline | Da | Da, zasebno za svaki ticker |
| Postavke modela i agenata | Biraju se jednom | Biraju se jednom i dijele kroz cijelu watchlistu |
| Završna ocjena | `Buy`, `Overweight`, `Hold`, `Underweight` ili `Sell` | Ista ocjena |
| Virtualna transakcija | Ne | Da, D+1 nakon zajedničke alokacije |
| Zajednički cash i pozicije | Ne koristi ih | Da, jedan trajni long-only račun |
| Pravi broker / pravi novac | Ne | Ne |

Oba načina koriste isti glavni slijed:

```text
Odabrani analitičari
  → Bull/Bear rasprava
  → Research Manager
  → Trader
  → Aggressive/Conservative/Neutral rasprava
  → Portfolio Manager
  → završna ocjena
```

Razlika nastaje poslije završnih ocjena: Single analysis sprema izvještaj i staje,
a Paper trading prvo prikupi sve odluke, napravi jedan zajednički plan i izvršava
ga na prvom kasnijem tržišnom Open-u.

## Pokretanje

Prije prvog pokretanja potrebno je imati `.env` s ključem za odabrani LLM provider. Aplikacija se može pokrenuti lokalno:

```bash
tradingagents
```

ili iz izvornog koda:

```bash
python -m cli.main
```

Docker varijanta je:

```bash
docker compose run --rm tradingagents
```

Za lokalni Ollama servis:

```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

Nakon pokretanja CLI prvo pita želiš li `Single analysis` ili `Paper trading`.

## Važno prije čitanja rezultata

- Sustav je istraživački alat, a ne financijski savjetnik.
- Paper trading ne šalje naloge brokeru i ne može potrošiti pravi novac.
- LLM izlaz nije potpuno deterministički. Isti ticker, datum i postavke mogu dati različitu odluku.
- Datum zaključava tržišni cjenovni prozor, ali izvori vijesti i sentimenta mogu se s vremenom promijeniti.
- Paper trading analizira tickere redom, ali cash mijenja tek nakon jedne zajedničke,
  determinističke alokacije za cijelu watchlistu.
