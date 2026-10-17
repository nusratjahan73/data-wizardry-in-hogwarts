# Data Wizardry in Hogwarts

**Forecasting a Canadian retail buy before the wizarding franchise comes back in December 2026.**

This is a full data and AI project that I built in September 2026 from my own written plan. I used Python (pandas, statsmodels, Prophet, scikit-learn, VADER, NetworkX, Dask), Power BI and real public data from Wikipedia, Statistics Canada, Google Trends and Rebrickable.

---

## What I found

The new show premieres on 25 December 2026. That is the day gift buying stops.

Canadian book and hobby retail swings **99 index points** across the year. It peaks in December at 172, drops to 86 in January and bottoms out at 73 in February. Attention to the franchise swings only **25 points** and still sits at 110 in that same January. So the December peak comes from the gift calendar, not from people suddenly caring more about the franchise.

This means the category empties its shelves in the same weeks the show arrives. I found that almost all of the extra demand from the premiere lands from late December onward. That is clearance season, when the stock is normally already gone.

**My recommendation:** commit a **$2,486,052** retail buy for November 2026 to March 2027, about 73,000 units, and hold **50 to 60%** of it for January. Normally this category would put it all before Christmas. Holding sixty per cent gives the highest expected profit. Holding fifty gives up $8,320 of that profit to lift the worst case by $17,548. I can defend a range from $1.94m to $2.60m.

**Timing matters. Imported product for the January position had to be ordered by 27 August 2026.** When I finished the analysis in early September, three of the six order dates had already passed.

The number I would question first is my own assumption for turning attention into sales, which I set at 0.35. I call it an assumption because I could not measure it. Across its likely range my central season sales move from $1.99m to $2.53m. That spread of $0.54m is close to the $0.66m gap between my low and high demand scenarios.

---

## Start here

| If you want | Open |
| --- | --- |
| The one page summary | [`images/infographic/data_wizardry_infographic.png`](images/infographic/data_wizardry_infographic.png) |
| The story, with charts | [`web/index.html`](web/index.html), opened in a browser |
| A Word report of everything | [`docs/word/Data_Wizardry_Report.docx`](docs/word/) |
| The results | [`docs/findings.md`](docs/findings.md), eleven findings |
| How I did it, and every assumption | [`docs/methods.md`](docs/methods.md) |
| Data ethics and governance | [`docs/ethics.md`](docs/ethics.md) |
| Every column of every table | [`docs/data_dictionary.md`](docs/data_dictionary.md) |
| What went wrong while I was building | [`logs/data_issues.md`](logs/data_issues.md) |
| Questions that are still open | [`docs/open_questions.md`](docs/open_questions.md) |
| How I built it, step by step | [`docs/build_walkthrough.md`](docs/build_walkthrough.md) |

---

## What I built

I built all nine modules, and every script runs from start to finish by itself. Four of them answer a different question from the one I first planned, because I could not get the data I had counted on. I mark each of those as a substitute in the code, in its finding and in the table below.

| Module | What it does | As planned? |
| --- | --- | --- |
| 1. The Library (data) | Nine collectors, ten cleaners, five processed tables, a data dictionary with 121 columns, 26 tests | Yes |
| 2. The Great Hall (BI) | A star schema made from the processed tables, 20 DAX measures, six pages with 30 visuals | Yes, as a `.pbip` project |
| 3.1 Narrative tone | Tone and character presence in season one | **Substitute**, no fan text |
| 3.2 Character network | How attention moves together across the main cast | Yes (negative result) |
| 3.3 Seasonality | STL decomposition, attention against 35 years of retail | Yes |
| 3.3b Event study | What four franchise events did to attention | Extra |
| 3.4 Product line | How the product line grows, and what drives set size | **Substitute**, no prices |
| 4. The Houses | Product types from 15,000 sets, with k chosen on two measures | **Substitute**, products and not audiences |
| 5.1 Forecast | Five models, one held out year, three scenarios | Yes |
| 5.2 Interest to sales | The link between the two, reported as no effect found | Yes |
| 5.3 Set size model | Regression on size, because I had no prices | **Substitute**, no prices |
| 5.4 Text classifier | Spell category from its description, cross validated | **Substitute**, no labelled sentiment |
| 6. Gringotts (retail) | Demand profile, order dates, newsvendor model, how much to hold back | Yes |
| 7. The Chamber (big data) | pandas against Dask on 1.56m real rows, scaled up to 12.5m | **Substitute**, tables and not text |
| 8. The Ministry (ethics) | Seven topics, and a scan for leaked keys that I really ran | Yes |
| 9. Infographic | One page, made by code so every number traces to a file | Made by code, not in Canva |

I wrote down eleven findings in [`docs/findings.md`](docs/findings.md). Three of them are negative results and I report them that way. The character network has no communities. The effect of attention on sales cannot be told apart from zero. And my text classifier loses to its own baseline on accuracy.

I collected the data on 2 and 3 September 2026: 144,035 article days of Wikipedia pageviews, 222,799 rows from Statistics Canada, 1.66m rows from the full Rebrickable catalogue, 6,140 PotterDB records, 40 Google Trends pulls, and two tables I entered by hand that cover 11 films and 66 park years. Every row in those two tables has a source and a date.

---

## What is not done, and why

Everything in the project runs without any API key. Three things are still missing, and I have not hidden them anywhere.

**No fan text, so nothing I built measures audiences or opinion.** Reddit needs a login I do not have. In modules 3.1, 4 and 5.4 I answered nearby questions with data the project does have, and in module 7 I processed tables in place of text. So four of my analyses describe *products and attention* where I first wanted *people and sentiment*. I see this as the biggest gap in the work.

**No retail prices, so I could not test the licensing premium.** Brickset needs a key. In modules 3.4 and 5.3 I use set size in place of price. Nothing in this project says anything about price or margin on the product line.

**I could not put a number on brand risk.** That needs sentiment data. My recommended buy carries it as a downside without a number. See [`docs/ethics.md`](docs/ethics.md), part 5.

Both sites have an API and ask that automated access goes through it. Brickset shows its prices on public pages and Reddit has an open JSON endpoint, so I could have scraped either one. I chose not to. Part 1 of [`docs/ethics.md`](docs/ethics.md) explains that choice and what it cost me.

Adding the two free keys would bring back the first versions of all six affected analyses. I wrote those scripts, and today they skip cleanly.

**The Power BI dashboard is made as a project, not as a `.pbix` file.** `src/analysis/29_build_powerbi_project.py` writes [`dashboard/pbip/`](dashboard/pbip/) in Microsoft's open `.pbip` format, with eleven tables, eight relationships, all twenty DAX measures and six pages that hold 30 visuals. Power BI Desktop opens it, and **File, Save As** produces the `.pbix`. A script cannot write a `.pbix` directly, because it wraps a compiled model that only Power BI Desktop can build.

I checked that it opens in Power BI Desktop 2.150 with all eleven tables, the twenty measures and the six pages. Click **Refresh now** the first time to load the CSV files, then Save As. The script also places the visuals on each page: 9 on Overview, 4 on Return on investment, 4 on Reception, 3 on Geography, 6 on Product line and 4 on Timing. I saved my own copy as a `.pbix` with those 30 visuals and my colour theme in it: [`dashboard/DataWizardry.pbix`](dashboard/DataWizardry.pbix). It opens with the data already loaded. Both the `.pbix` and the project store full folder paths to the CSV files, so to refresh the data on your own computer, run the script once first. See [`dashboard/model_notes.md`](dashboard/model_notes.md).

The infographic is finished. `src/analysis/28_infographic.py` makes it in [`images/infographic/`](images/infographic/) as PNG and PDF. I prefer this to building it by hand in Canva for one reason: every number on it is read from `outputs/tables` at the moment it is drawn, so each figure can be traced back to a file.

## Four places where my plan was wrong

I found each one by checking the live source. Each would have cost me time or quietly damaged a result.

1. **PotterDB has no flat `chapters` endpoint.** The chapters hang off each book.
2. **Google Trends returns monthly data for long windows.** I had to pull the weekly series in eight overlapping four year windows and rescale them.
3. **The archived StatCan table uses NAICS 2017 and the active one uses NAICS 2022.** The category this project is about was renumbered from 451 to 459A, so joining on the code alone silently left it with no history before 2017. A crosswalk brings back 35 years, and the mapping agrees to within 1.3% across 72 overlapping months.
4. **The film money figures in PotterDB have real errors.** Philosopher's Stone is listed at "$1.018 million", and one release date is duplicated. I took film money from The Numbers, Box Office Mojo and Rotten Tomatoes.

I also caught and fixed three mistakes of my own while building. One was a composite series that cut usable history from 577 weeks to 176. One was a unit error that made the high forecast scenario 50 times too large. And one was a demand split that put all of December on the wrong side of a premiere that falls on the 25th.

---

## Running it

You need Python 3.11 or newer. I built and checked it on 3.14.2.

```bash
python -m pip install -r requirements.txt
```

```bash
for f in src/collect/*.py src/clean/*.py src/analysis/*.py src/models/*.py src/retail/*.py src/bigdata/*.py; do python "$f"; done
python src/analysis/24_web_export.py
python src/analysis/28_infographic.py
python src/report/60_build_report.py
```

The scripts are numbered, and file name order is run order, with one exception. The web export (24) and the infographic (28) read tables that the models and the retail script make later, so I run those two again at the end. The report script (60) goes last. Collection takes about 20 minutes, and almost all of that is waiting so I respect the rate limits. The rest takes about 3 minutes.

```bash
python -m pytest tests/ -q
```

```bash
python -m ruff check src/ tests/
```

To see the data story, serve the `web` folder and open it:

```bash
python -m http.server 8000 --directory web
```

---

## What is in each folder

```
data/           raw, cleaned and processed data, plus external files I entered by hand
docs/           every document as Markdown, with a Word copy of each in docs/word
src/            collect (01-09), clean (10-19), analysis (20-29), models (30-39), retail (40-49),
                bigdata (50-59), report (60-69), utils. The number in each file name is its run order
outputs/        tables and saved model results
images/figures  every chart the code makes
dashboard/      star schema and the Power BI project
web/            the data story: markup, css/, js/
tests/          tests on the processed tables
config.yaml     every date, path, threshold and setting
logs/           run history and the list of data issues
```

---

## About me and sources

**Nusrat Jahan**, Master of Business Analytics and AI, Ontario Tech University.

I credit every data source in [`docs/methods.md`](docs/methods.md) and on every figure. I do not store any copyrighted text from the novels or films anywhere in this repository.

I planned and directed this project and used AI coding tools to build it. I checked every result myself.
