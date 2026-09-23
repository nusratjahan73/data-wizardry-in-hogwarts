# Data Wizardry in Hogwarts

**Forecasting a Canadian retail buy before the December 2026 wizarding revival.**

---

## The finding

The premiere is on 25 December 2026 — the day gift buying stops.

Canadian book-and-hobby retail swings **99 index points** across the year,
peaking in December at 172 and collapsing to 86 in January. Franchise attention
swings only **25 points** and sits at 110 in that same January. December's peak
is made by the gift calendar, not by any surge of interest in the franchise.

So the category empties its shelves in the same weeks the show arrives. I find
that essentially all of the premiere-driven uplift lands from late December
onward, during clearance season, when the stock is normally already gone.

**My recommendation:** commit a **$2,486,052** retail buy for November 2026 to
March 2027, about 73,000 units, and hold **50–60%** of it for a January position
rather than committing it to the pre-Christmas window as this category normally
would. Sixty per cent maximises expected profit; fifty gives up $8,320 of that to
lift the worst case by $17,548. Defensible range: $1.94m to $2.60m.

**Imported product for the January position was due to be ordered by 27 August
2026.** That date has passed. Three of the six order-by dates are already behind.

The one number I would argue with first is my assumption converting attention
into sales, which I set at 0.35. I treat it as an assumption because I could not
measure it, and across its plausible range the buy moves from $1.99m to $2.53m,
a wider spread than the gap between my low and high demand scenarios.

---

## Start here

| If you want | Open |
| --- | --- |
| The one-page summary | [`images/infographic/data_wizardry_infographic.png`](images/infographic/data_wizardry_infographic.png) |
| The story, with charts | [`web/index.html`](web/index.html) — open it in a browser |
| A Word report of everything | [`docs/word/Data_Wizardry_Report.docx`](docs/word/) |
| The results | [`docs/findings.md`](docs/findings.md) — nine findings |
| How I did it, and every assumption | [`docs/word/methods.docx`](docs/word/) |
| Governance | [`docs/word/ethics.docx`](docs/word/) |
| Every column of every table | [`docs/data_dictionary.md`](docs/data_dictionary.md) |
| What went wrong during the build | [`logs/data_issues.md`](logs/data_issues.md) |
| Decisions reserved for a human | [`docs/word/open_questions.docx`](docs/word/) |

---

## What I built

I built all nine modules and every script runs unattended. Four of them answer a
different question from the one the brief specifies, because I could not obtain
the data the brief assumes. I label each as a substitute in its own docstring, in
its finding, and in the table below.

| Module | What it does | As specified? |
| --- | --- | --- |
| 1 — The Library (data) | Nine collectors, ten cleaners, five processed tables, 121-column data dictionary, 26 tests | Yes |
| 2 — The Great Hall (BI) | Star schema generated from the processed tables, 20 DAX measures, six pages specified | Model yes, `.pbix` no |
| 3.1 — Narrative tone | Season one tone and character presence | **Substitute** — no fan text |
| 3.2 — Character network | Attention co-movement across the main cast | Yes (negative result) |
| 3.3 — Seasonality | STL decomposition, attention against 35 years of retail | Yes |
| 3.3b — Event study | What four franchise events did to attention | Extra |
| 3.4 — Product line | How the line scales, and what drives set size | **Substitute** — no prices |
| 4 — The Houses | Product archetypes from 15,000 sets, k chosen on two measures | **Substitute** — products, not audiences |
| 5.1 — Forecast | Five models, held-out year, three scenarios | Yes |
| 5.2 — Interest→sales | The bridge, reported as a null | Yes |
| 5.3 — Set size model | Regression on size rather than price | **Substitute** — no prices |
| 5.4 — Text classifier | Spell category from description, cross-validated | **Substitute** — no labelled sentiment |
| 6 — Gringotts (retail) | Demand profile, order dates, newsvendor, reserve trade-off | Yes |
| 7 — The Chamber (big data) | pandas vs Dask on 1.56m real rows, scaled to 12.5m | **Substitute corpus** — tabular, not text |
| 8 — The Ministry (ethics) | Seven topics, credential scan run not asserted | Yes |
| 9 — Infographic | One page, generated so every number traces to a file | Generated, not Canva |

I record nine findings in [`docs/findings.md`](docs/findings.md). Three are
negative results and I report them as such: the character network has no
communities, the attention-to-sales elasticity is indistinguishable from zero,
and my text classifier loses to its own baseline on accuracy.

I collected the data on 2 and 3 September 2026: 144,035 article-days of Wikipedia pageviews,
1.37m rows from Statistics Canada, 1.74m rows from Rebrickable's full catalogue,
6,140 PotterDB records, 40 Google Trends pulls, and two hand-entered tables
covering 11 films and 66 park-years, every row of which I sourced and dated.

---

## What is not done, and why

Everything in the project runs without any credential. Three things are still
genuinely absent, and I have not hidden any of them elsewhere.

**No fan text, so nothing I built measures audiences or opinion.** Reddit needs
credentials I do not have. I answered adjacent questions in modules 3.1, 4 and
5.4 using data the project does own, and processed a tabular corpus rather than
a text one in module 7. Four of my analyses therefore describe *products and
attention* where the brief wanted *people and sentiment*. I consider that the
single biggest gap in the work.

**No retail prices, so I could not test the licensing premium.** Brickset needs a
key. I substitute size for price in modules 3.4 and 5.3. Nothing in this project
says anything about price or margin on the product line.

**I could not quantify brand risk.** It needs sentiment data. My recommended buy
carries that as an unquantified downside. See
[`docs/word/ethics.docx`](docs/word/) section 5.

Both sites publish an API and ask that automated access go through it. Brickset's
prices are on its public pages and Reddit exposes an unauthenticated JSON
endpoint, so I could have scraped either. I chose not to, and
[`docs/word/ethics.docx`](docs/word/) section 1 sets out that decision and its cost.

Adding the two free keys would restore the original versions of all six affected
analyses. I wrote those scripts and they skip cleanly today.

**The Power BI dashboard is generated as a project, not a `.pbix`.**
`src/analysis/29_build_powerbi_project.py` writes
[`dashboard/pbip/`](dashboard/pbip/) in Microsoft's open `.pbip` format, with
eleven tables, eight relationships and all twenty DAX measures already defined.
Power BI Desktop opens it and **File → Save As** produces the `.pbix`. A `.pbix`
itself cannot be written by a script: it wraps a compiled model only Power BI
Desktop can build.

Confirmed: it opens in Power BI Desktop 2.150 with all eleven tables, the twenty
measures and the six named pages. Click **Refresh now** on first open to load the
CSVs, then Save As. The six pages are named but empty, because generating visual
layouts that could not be tested risked a file that would not open at all. See
[`dashboard/model_notes.md`](dashboard/model_notes.md).

The infographic is **not** outstanding. It is generated by
`src/analysis/28_infographic.py` into
[`images/infographic/`](images/infographic/) as PNG and PDF, which is better than
a hand-built Canva version for one specific reason: every number on it is read
from `outputs/tables` at render time, so section 15's requirement that each
figure trace to a file holds by construction rather than by inspection.

## Four places the brief's assumptions were wrong

I found each by checking the live source, and each would have cost me time or
quietly corrupted a result.

1. **PotterDB has no flat `chapters` endpoint.** They hang off each book.
2. **Google Trends returns monthly data for long windows.** The weekly series had
   to be pulled in eight overlapping four-year windows and rescaled.
3. **The archived StatCan table uses NAICS 2017, the active one NAICS 2022.** The
   category this project is about was renumbered 451 → 459A, so joining on the
   code alone silently left it with no history before 2017. A crosswalk recovers
   35 years; the mapping agrees to within 1.3% across 72 overlapping months.
4. **PotterDB's film financials contain real errors** — Philosopher's Stone at
   "$1.018 million", a duplicated release date. I took film money from The Numbers,
   Box Office Mojo and Rotten Tomatoes instead.

I caught three mistakes of my own mid-build and recorded them in the commit
history rather than quietly fixing them: a composite series that cut usable history
from 577 weeks to 176, a unit error that made the high forecast scenario 50×
too large, and a demand split that put all of December on the wrong side of a
premiere that falls on the 25th.

---

## Running it

Python 3.11 or newer; built and verified on 3.14.2.

```bash
python -m pip install -r requirements.txt
```

```bash
for f in src/collect/*.py src/clean/*.py src/analysis/*.py src/models/*.py src/retail/*.py; do python "$f"; done
```

Scripts are numbered so filename order is run order. Collection takes about 20
minutes, almost all of it deliberate rate-limit waiting; the rest takes about 3
minutes.

```bash
python -m pytest tests/ -q
```

```bash
python -m ruff check src/ tests/
```

To view the data story, serve the `web` folder and open it:

```bash
python -m http.server 8000 --directory web
```

---

## Repository layout

```
data/           raw, cleaned and processed data, plus hand-entered external files
docs/           findings, methods, ethics, data dictionary, open questions, build log
src/            collect (01-09), clean (10-19), analysis (20-29), models (30-39), retail (40-49), utils
outputs/        tables and model artefacts
images/figures  every generated chart
dashboard/      star schema and the Power BI specification
web/            the data story: markup, css/, js/
tests/          acceptance tests on the processed tables
config.yaml     every date, path, threshold and parameter
logs/           run history and the data issues register
```

---

## Attribution and sources

**Nusrat Jahan** — Master of Business Analytics and AI, Ontario Tech University.

I credit every data source in [`docs/word/methods.docx`](docs/word/) and on every
figure. I store no copyrighted text from the novels or films anywhere in this
repository, per section 6 of the brief.

I used AI assistance (Claude) while building this project. This is the only place
that statement appears; the commit history records what changed and why, including
the mistakes I corrected along the way.
