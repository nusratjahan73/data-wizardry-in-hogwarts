# How I built this project

This is the walkthrough I would want if I were starting again tomorrow with nothing but the idea. It goes in the order I actually worked, explains why each step came where it did, and says what every file in the repository is for.

I have written it so that someone with the idea and no other materials could rebuild the whole thing. Where a decision could reasonably have gone the other way, I say what I chose and why, rather than presenting it as the only option.

## Part 1. Before I wrote any code

### 1.1 The one question

I started by writing down a single sentence, because a project with one question can be finished and a project with a theme cannot:

*How large a wizarding category buy should a Canadian book and lifestyle*

*retailer commit for the 2026 holiday season, given that the new series*

*premieres on 25 December 2026?*

Everything in the repository exists to answer that. The premiere date is what makes it interesting: 25 December is *after* the gift buying window closes. A retailer has to commit stock months earlier, and the surge in interest arrives when the shelves are already cleared. So the real question is not only *how much* but *when*, and that turned out to be the finding worth having.

I put the question at the top of the README before writing a line of code. Every time I was tempted to add an analysis, I checked it against that sentence. Most temptations failed the check.

### 1.2 The constraint that shaped everything

I set one hard rule at the start:

*Every data source must work with no API key, no account, and no paid tier.*

This was not a limitation I discovered part way through. It was a design decision, and it drove every source choice that follows. The benefit is that anyone can clone the repository and reproduce the entire dataset from nothing. There is no "you need to get a key from X first" step, and no result depends on credentials I hold and a reader does not.

It did cost something, and I record that honestly rather than hiding it. Retail prices for the toy line and a fan text corpus both sit behind free API keys, so six analyses that would have needed them are replaced with a credential free equivalent. Each replacement is labelled as one everywhere it appears. I did not scrape around either source; both publish an API and ask that automated access go through it, and the moment I scraped, every claim in the ethics document would have become false.

### 1.3 The decisions I made before collecting anything

Five choices, all made up front, all of which would have been expensive to change later:

**Canadian dollars throughout.** The client is Canadian. Box office is published in US dollars, so I convert at a single stated rate rather than a historic series, because a historic series mixes inflation and currency movement in one column and the reader cannot tell which is which.

**Config, never constants.** Every date, threshold, rate and assumption lives in `config.yaml`. No script contains a magic number. This is what makes the sensitivity analysis possible at all: I can change the pass through assumption in one place and rerun.

**Filename order is run order.** Scripts are numbered `01` to `60`. Anyone can see the pipeline by listing the folder, and there is no separate orchestration file that can fall out of date with reality. The one exception is the web export (24) and the infographic (28), which read tables made by later scripts, so I run those two again at the end.

**Raw data is never edited in place.** Collected files land in `data/raw/` and are treated as read only. Cleaning writes to `data/cleaned/`, joining writes to `data/processed/`. If cleaning has a bug, I fix it and rerun; I never have to collect again.

**Every finding carries its uncertainty.** A result without a stated weakness is a result I do not yet understand. This is a formatting rule enforced by the helper that writes findings, not a good intention.

## Part 2. The empty folder

### 2.1 Environment first

```
python -m venv .venv
.venv\Scripts\activate
```

I built on Python 3.14.2 on Windows 11. I installed packages as I needed them rather than guessing a list up front, then froze the result at the end by reading versions back from `pip` rather than typing them from memory. That is why `requirements.txt` matches the environment that actually produced the outputs.

Three packages that a stack like this would normally include are left out on purpose. `pyspark` installs cleanly but needs a Java runtime, and there is no JVM on my machine, so the out of core comparison uses Dask instead. `plotly` is not needed, because every figure is matplotlib, and `nltk` is not needed, because `vaderSentiment` scores tone on its own. I record that in `requirements.txt` itself rather than leaving a reader to wonder.

### 2.2 The folder tree

I created the whole tree before writing code, so that nothing ever had to guess where to put a file:

```
data/raw/          collected exactly as the source returned it, read only
data/cleaned/      one tidy table per source, types fixed, columns renamed
data/processed/    joined, ready for analysis tables
data/external/     hand entered CSVs that no script can regenerate
src/collect/       01-09  talk to the outside world
src/clean/         10-19  reshape what came back
src/analysis/      20-29  descriptive analysis and exports
src/models/        30-39  anything fitted and evaluated
src/retail/        40-49  turns analysis into a buying recommendation
src/bigdata/       50-59  the scaling comparison
src/report/        60-69  builds the Word deliverables
src/utils/         shared helpers, imported by everything above
outputs/tables/    every number any document or chart cites
outputs/models/    fitted model artefacts
images/figures/    the charts
dashboard/         the Power BI project
web/               the one page HTML summary
docs/              generated Markdown and the Word documents
logs/              run history and the data issues register
tests/             the checks that run against the outputs
```

### 2.3 Git, and what never goes in it

```
git init
```

I wrote `.gitignore` before the first commit, not after. The rule I followed is that the repository ships **the code that rebuilds the data, not the data**: `data/raw`, `data/cleaned` and `data/processed` are all ignored. `data/external` is tracked, because it is hand entered and no script can regenerate it.

Credentials are excluded by pattern rather than by name: `.env` and any `.env.*`, plus `*.key`, `*.pem`, `credentials.json` and `praw.ini`. I track `.env.example`, which lists key *names* with empty values so a reader knows what would be needed, and never a value.

## Part 3. The scaffolding I built before the first collector

This is the part I would most strongly recommend to anyone starting again. I spent the first working session on five helper modules that do nothing visible, and every script afterwards was shorter and more consistent because of them.

**`src/utils/config.py`**: the single point of access to `config.yaml` and to `.env`. Every script reads settings through it. Its most important design choice is that `secret()` returns `None` when a key is absent rather than raising: that is what lets a collector log the missing key by name, write an entry to the issues register, and skip its source cleanly instead of crashing the build.

**`src/utils/http.py`**: one polite HTTP client that every outbound request in the project goes through. It sets a `User-Agent` naming the project, spaces calls to the per source rate limit from config, honours a `Retry-After` header when the server sends one, and retries with backoff. Because there is exactly one client, the terms of use table in the ethics document describes actual behaviour rather than intentions. During collection the Wikimedia server asked for a pause three times and the client waited the requested 5, 49 and 53 seconds rather than hammering it.

**`src/utils/io.py`**: saving, loading and stamping files. Every write goes through it, which is how the folder layout stays enforced in code rather than by discipline. It also writes a `.meta.json` sidecar next to each output recording what produced it and when, and it creates parent folders on demand, so no script ever fails because a directory is missing.

**`src/utils/logging_setup.py`**: shared logging, the `RunTimer` context manager that records every script's rows in, rows out and duration to `logs/run_history.csv`, and `log_data_issue()`, which appends to a register in `logs/data_issues.md`. That register is the single most useful thing I built. Any time a source disagreed with expectation, the script wrote it down and carried on. Nothing was silently swallowed and nothing was invented to fill a gap.

It also holds `write_finding()`, which every analysis script calls to append to `docs/findings.md` in a fixed shape: claim, evidence, uncertainty. Because the shape is enforced by the helper, no finding can reach the document without its weakness stated.

**`src/utils/plotting.py`**: one palette and one chart style for the whole project, so seventeen figures made over several days look like one person made them. Changing the project's colour scheme is a change to this one file.

Two more helpers came later, when I needed them:

**`src/utils/markdown_to_docx.py`**: converts Markdown to a styled Word document, matching the same palette.

**`src/utils/pbi_visuals.py`**: builders for Power BI report visuals, kept separate from the generator that assembles the project file.

## Part 4. Collecting the data

Nine scripts, `01` to `09`. Six talk to a source, two record why a source was not used, one validates the hand entered tables.

| Script | What it does |
|---|---|
| `01_potterdb.py` | PotterDB REST API, no key. 6,140 records across six endpoints: books, characters, chapters, spells, potions, movies. |
| `02_hpapi.py` | HP API, no key. 514 records; better attribute completeness on the main cast, so it cross checks PotterDB. |
| `03_pageviews.py` | Wikimedia pageviews REST API, no key. 144,035 article days across 37 articles, daily from 2015-07-01. This became the primary attention series. |
| `04_trends.py` | Google Trends via `trendspy`. 40 pulls: one full range monthly series plus eight overlapping four year windows for weekly detail. |
| `05_statcan.py` | Statistics Canada web data service. Three tables, 222,799 rows: retail trade 1991-2026 and CPI 1914-2026. |
| `06_rebrickable.py` | Rebrickable bulk catalogue dumps from the public CDN. 265 branded sets, 2001-2026, and the full parts inventory. |
| `07_brickset.py` | Records that no key was available and writes the issue. Runs clean, collects nothing. |
| `08_reddit.py` | Same. Contains the privacy controls in full so they are reviewable even though they never ran. |
| `09_external_check.py` | Validates the two hand entered CSVs: types, ranges, no missing sources. |

### 4.1 The two hand entered tables

Some data is too small to be worth an API and too specific to exist in one. `data/external/films.csv` holds eleven films with budget, box office, opening weekend and critic and audience scores. `data/external/parks.csv` holds 66 park years of attendance.

I hand entered both, with a source and a date on every row, and `09_external_check.py` validates them. `data/external/films_notes.md` records where each column came from and its limitations.

**Why not take film money from PotterDB, which has it?** Because I checked it against published figures and it could not be trusted for money: Philosopher's Stone is listed at "$1.018 million" when the correct figure is 966.6 *million*, and Deathly Hallows Part 2 at "$1,342 billion" where the comma is a decimal point. Three of those errors would survive a careless parse and quietly corrupt the return on investment analysis. So film money comes from The Numbers, Box Office Mojo and Rotten Tomatoes, and I keep PotterDB's own figures alongside under a `potterdb_` prefix so I can *show* the discrepancy rather than assert it.

This is the general lesson: check any source against a second one before trusting it, especially for numbers that look like units.

### 4.2 The two collection problems worth knowing about

**Google Trends silently changes granularity.** I wanted weekly data since 2004. Google chooses granularity from the width of the request and gives the caller no say. A request spanning 2004 to 2026 returns *monthly* points, with no error and no warning. The fix is to collect twice: one full range monthly pull for the long history, and eight overlapping four year windows for weekly detail, then rescale the windows onto one series using the year each neighbouring pair shares.

The rescaling itself has a trap. My first attempt took the median of the per week ratios in the overlap, which collapsed to zero on sparse terms where most overlapping weeks are zero on one side. The fix is a ratio of sums across the whole overlap, which is stable when individual weeks are noisy or empty.

**Statistics Canada renumbered the category.** The historic retail table is archived and ends in December 2022; the active table continues from there. That much is documented. What is not obvious is that the archived table is coded to NAICS 2017 and the active one to NAICS 2022, and the 2022 revision renumbered the exact category this project is about from **451** to **459A**.

Concatenating on the code alone leaves the focus category with no history before 2017, *silently*, because total retail trade looks fine, its code never having changed. I caught it only because 35 years of history became 4. The fix is a crosswalk in `config.yaml` mapping old codes to new, plus an overlap check that measures how well each mapped pair agrees. 459A agrees with 451 to within 1.3% across 72 overlapping months, which is what justifies joining them.

## Part 5. Cleaning and joining

Ten scripts, `10` to `19`. Each takes one raw source and produces one tidy table: consistent types, snake_case columns, dates as dates, no duplicates.

| Script | What it produces |
|---|---|
| `10_clean_potterdb.py` | books, characters, chapters, spells, potions tables |
| `11_clean_hpapi.py` | the HP API character table, aligned to the same schema |
| `12_clean_pageviews.py` | daily and weekly pageviews per article |
| `13_clean_trends.py` | the stitched weekly series and the monthly series |
| `14_clean_statcan.py` | retail monthly with the NAICS crosswalk applied, and CPI |
| `15_clean_toys.py` | the set catalogue and theme tables |
| `16_clean_reddit.py` | would clean fan text; hard fails if a raw file contains a username |
| `17_clean_external.py` | films and parks, with currency conversion and CPI deflation |
| `18_build_processed.py` | joins everything into five ready for analysis tables |
| `19_data_dictionary.py` | reads every processed table and writes `docs/data_dictionary.md` |

`18_build_processed.py` is the hinge of the project. It produces the five tables every analysis reads:

- **`attention_weekly.csv`**: the composite attention series, weekly
- **`retail_monthly.csv`**: Canadian category and total retail, monthly, real and nominal
- **`characters.csv`**: characters with their attention series joined on
- **`films.csv`**: the eleven films, cleaned and deflated
- **`products.csv`**: the branded set catalogue Two things I got wrong here and had to fix:

**The composite series cut my history from 577 weeks to 176.** I had included the new TV series' own Wikipedia article in the composite, and that article only exists from 2023. Any composite is limited by its shortest member. I excluded it from the composite and tracked it separately, which recovered the full history *and* gave me a cleaner signal for the announcement events.

**A duplicate key.** `attention_weekly` had two rows per week because the primary key omitted the article group. Caught by a test that asserts uniqueness, not by reading the data.

`19_data_dictionary.py` is worth building. It reads every processed table and its sidecar and writes the data dictionary automatically, so the documentation of columns can never drift from the columns that actually exist.

## Part 6. Analysis

Ten scripts, `20` to `29`.

| Script | What it answers |
|---|---|
| `20_seasonality.py` | STL decomposition of attention and of category retail. **The core finding.** |
| `21_event_study.py` | What a dated franchise event does to attention, and for how long |
| `22_character_network.py` | Whether character attention moves together in a meaningful structure |
| `23_star_schema.py` | Builds the dimensional model the dashboard reads |
| `24_web_export.py` | Writes `web/js/data.js` so the HTML page cites real numbers |
| `25_narrative_tone.py` | VADER tone across chapter summaries, and character presence |
| `26_product_segmentation.py` | k-means over 14,950 sets on construction features |
| `27_product_line_evolution.py` | How the product line scales to the release calendar |
| `28_infographic.py` | The single page infographic |
| `29_build_powerbi_project.py` | Generates the openable Power BI `.pbip` project |

### 6.1 The finding the whole project rests on

`20_seasonality.py` runs an STL decomposition on both series and compares their seasonal indices. The category peaks hard in December and collapses in January. Franchise attention barely moves all year. It spans only a few index points.

That gap is the entire argument. December's peak is made by the gift calendar, not by interest in the franchise. January is when shelves are cleared while attention does not fall, and January is exactly when the premiere pushes attention sharply up. So the recommendation is not only a quantity, it is a *timing*: hold back a substantial share of the buy for a January position.

I excluded 2020 and 2021 from the seasonality work. Canadian retail in April 2020 is a data point about closed shops, not about seasonality. That exclusion is a judgement, it lives in config, and every affected finding names it.

### 6.2 Two results that came back negative, and stayed in

**The character network was meaningless at first.** I used a fixed correlation threshold for edges and got a graph with density 1.0, with every character connected to every other, which measures nothing. The cause is that every character article shares the franchise trend, so on raw levels every pair correlates above 0.9.

Two fixes: take week on week differences before correlating, so the shared trend is removed, and set the edge threshold from the data (75th percentile of observed correlations) rather than picking a number. Also Spearman rather than Pearson, because several weeks in this data are enormous and would dominate a Pearson coefficient.

The network is still weakly informative, and I report it as a negative result rather than dressing it up.

**The interest to sales elasticity could not be measured.** More on this below; it is the project's central honest failure.

## Part 7. Models

Three scripts, `30` to `32`.

**`30_interest_forecast.py`** compares five approaches on a held out final 52 weeks. The split is by *time*, never at random: a random split on a time series lets the model see the future, and the score it produces is meaningless.

| Model | MAPE | vs baseline |
|---|---|---|
| Prophet | 13.1% | 0.39 |
| SARIMA | 26.9% | 0.70 |
| Holt-Winters | 36.6% | 0.86 |
| drift naive | 38.3% | 0.90 |
| seasonal naive (baseline) | 40.6% | 1.00 |

Every model is reported against the seasonal naive baseline. A model that cannot beat "the same week last year" is not worth deploying, and saying so is more useful than a number with no reference point. Prophet beats it comfortably, at roughly a third of the baseline's error.

**`31_interest_to_sales.py`** is the one that failed, and the failure is the most important thing in the project. It regresses Canadian category retail on franchise attention, with Newey-West standard errors because monthly retail is autocorrelated and ordinary errors would make the coefficient look more precise than it is.

The elasticity came back at **0.051 with a confidence interval spanning zero** (p = 0.071). That is not evidence of no effect. NAICS 459A contains every bookshop, hobby shop and sporting goods retailer in Canada, so a single franchise inside it sits below the noise floor. The instrument is too coarse.

I had a choice: present a not significant coefficient as if it were a measurement, or declare the conversion as an assumption and be explicit about it. I chose the second. `retail.attention_pass_through` is set to 0.35 in config and labelled as **the largest single uncertainty in the project**, and the recommendation is reported across a range of it. Across 0.15 to 0.70 the central season runs from $1.99m to $2.53m, a spread of $0.54m against a gap of $0.66m between my low and high demand scenarios. Anyone reviewing this work should start there.

**`32_spell_classifier.py`** classifies spells into categories from their effect descriptions, using TF-IDF over character n-grams and logistic regression. It beats the majority class baseline on macro F1 and *loses* to it on accuracy (51% against 57%), which is what happens when classes are imbalanced and a model spreads its predictions across all of them. I report both numbers rather than the flattering one.

## Part 8. The recommendation

**`40_retail_recommendation.py`** turns everything above into a number a buyer can act on.

The premiere response is *imposed*, not fitted. No model can learn the effect of an event that has never happened in this series, so the forecast supplies the counterfactual, which is what attention would do with no premiere, and three scenarios add an event response taken from multiples I measured on real franchise events in `21_event_study.py`. The scenarios are three readings of evidence, **not confidence intervals**, and I never describe them as such.

The split between the pre Christmas and January positions comes from a newsvendor calculation. The critical ratio compares the cost of understocking against the cost of overstocking: a lost sale costs 0.48 per retail dollar, a marked down one 0.04. That implies a 93% service level, which nearly agrees with the 95% default and is derived rather than assumed.

The output:

|  |  |
|---|---|
| Recommended buy | **$2,486,052** at retail, Nov 2026 to Mar 2027 |
| Units | 73,119 at a blended $34 |
| Held for January | **60%** |
| Defensible range | $1,938,234 to $2,602,889 |
| Service level used | 93%, derived from the cost of each error |
| Imported order by | 2026-08-27 |

That last row is a finding in its own right. Three of the six order by dates had already passed as of the analysis date. That is a fact about timing, not a defect in the analysis, but it constrains what the retailer can now act on, and it is the kind of thing an analysis that only reported a quantity would have missed.

One bug worth recording: my first December split put the *entire* month after the premiere, because monthly boundaries do not know that 25 December is near the end. `retail.december_share_before_premiere` is 0.85, and it exists because of that.

## Part 9. Scale, dashboard, web and documents

**`50_engine_comparison.py`** compares pandas against Dask on the parts inventory (1.56m rows, replicated 1× to 8× up to 12.5m), measuring wall time and peak memory with `tracemalloc`.

pandas won at every size. I report that plainly: the point at which pandas becomes impractical was never reached on this data and this machine. The honest conclusion from a scaling comparison is sometimes "you do not need the bigger tool yet", and writing that is more useful than manufacturing a crossover.

**`29_build_powerbi_project.py`** generates a real, openable Power BI project in the `.pbip` text format: a TMSL model definition, Power Query M expressions, and 30 visuals across 6 pages, all written as code from `dashboard/model/*.csv`. Generating it rather than clicking it means the dashboard cannot drift from the data. Three things I learned the hard way: `Measures` is a reserved table name in Power BI and silently breaks the file (mine is `Key Measures`, with a guard and a test), pages generated without visuals open blank rather than erroring, and map visuals are disabled by default in many tenants, so geography is a bar chart.

**`24_web_export.py` and `web/`** produce a one page HTML summary. Every number on the page is written in by `web/js/page.js` from `web/js/data.js`, which is generated. Nothing is typed by hand, so the page cannot contradict the analysis. Styling is in three CSS files by concern; there is no inline style or script anywhere.

**`60_build_report.py`** builds the Word deliverables, and it enforces a distinction worth copying:

- **Generated documents** hold *results*: `findings.md`, `data_dictionary.md`, `build_log.md`. Code writes them, they live as Markdown so `git diff` can show changes line by line, and this script converts each to Word. Editing the `.docx` is a mistake; the next run overwrites it.
- **Authored documents** hold *reasoning*: the methods note, the ethics note, the open questions and this walkthrough. No script can produce the judgement in them, so I write them by hand. I first kept them as Word only, and they drifted every time the project changed. Now they live as Markdown too, and this script turns them into Word on every run, so I only ever edit Markdown.

The reason for the split: a results document a person can edit will eventually disagree with the data, and a reasoning document a script can overwrite will eventually lose the reasoning.

## Part 10. What every file is for

### Top level

| File | Purpose |
|---|---|
| `README.md` | The front door. The question, the answer, how to run it, and what each folder holds. |
| `config.yaml` | Every date, threshold, rate and assumption. No script contains a magic number. |
| `requirements.txt` | Pinned versions read back from `pip`, plus a note on the packages deliberately left out. |
| `.env.example` | Credential *names* with empty values, so a reader knows what would be needed. Never a value. |
| `.gitignore` | Excludes collected data and credentials by pattern. |
| `ruff.toml` | Lint configuration. |

### src/utils/: shared helpers

| File | Purpose |
|---|---|
| `config.py` | Reads `config.yaml` and `.env`. `secret()` returns `None` rather than raising, so a missing key skips a source instead of crashing the build. |
| `http.py` | The one HTTP client: identified, rate limited, retried, honours `Retry-After`. |
| `io.py` | All reads and writes. Enforces the folder layout, writes `.meta.json` sidecars, creates folders on demand. |
| `logging_setup.py` | Logging, `RunTimer` (rows in, rows out, duration, written to `logs/run_history.csv`), and `log_data_issue()`, which writes to `logs/data_issues.md`. |
| `plotting.py` | One palette and one chart style for all 17 figures. |
| `markdown_to_docx.py` | Turns Markdown into styled Word, same palette. |
| `pbi_visuals.py` | Power BI visual builders, separate from the project generator. |
| `__init__.py` | `bootstrap()`: puts the repo root on `sys.path` so a script run directly behaves like an imported module. |

### Data folders

| Folder | Contents | Tracked? |
|---|---|---|
| `data/raw/` | Exactly what the source returned. Read only. | No |
| `data/cleaned/` | One tidy table per source. | No |
| `data/processed/` | The five joined, ready for analysis tables. | No |
| `data/external/` | `films.csv`, `parks.csv`, `films_notes.md`: hand entered, unregenerable. | **Yes** |

### Outputs

| Folder | Contents |
|---|---|
| `outputs/tables/` | 29 CSVs, each with a `.meta.json` sidecar. Every number any document, chart or page cites. |
| `outputs/models/` | Fitted model artefacts. |
| `images/figures/` | 17 charts. |
| `images/infographic/` | The single page infographic. |
| `dashboard/model/` | The star schema: 5 dimensions, 5 fact tables, `relationships.csv`. |
| `dashboard/` | The generated `.pbip` Power BI project, and `DataWizardry.pbix`, my saved copy of it with the colour theme applied. |
| `web/` | `index.html`, three CSS files, `chart.js`, `page.js`, generated `data.js`. |

### Documents

| File | Kind | Written by |
|---|---|---|
| `docs/findings.md` | Generated | Every analysis script, via `write_finding()` |
| `docs/data_dictionary.md` | Generated | `19_data_dictionary.py` |
| `docs/build_log.md` | Generated | Modules as they complete |
| `docs/methods.md` | Authored | Me |
| `docs/ethics.md` | Authored | Me |
| `docs/open_questions.md` | Authored | Me |
| `docs/build_walkthrough.md` | Authored | Me |
| `docs/word/*.docx` | Generated | `60_build_report.py`, one Word copy of every Markdown document above |
| `docs/word/Data_Wizardry_Report.docx` | Combined | `60_build_report.py`, merging six of them in reading order |
| `logs/run_history.csv` | Generated | `RunTimer` on every script |
| `logs/data_issues.md` | Generated | `log_data_issue()` wherever a source disagreed with expectation |

### Tests

| File | Checks |
|---|---|
| `tests/test_processed.py` | 11 checks: no table is empty, every primary key is unique, no date is in the future, no money column is negative, the attention series really is weekly, retail covers at least fifteen years, the focus category has history (this is the NAICS crosswalk regression test), the film table is internally consistent, every table has a metadata sidecar, and no processed table ever gains a column named `author`, `username` or `email`. |
| `tests/test_powerbi_project.py` | 11 checks on the generated `.pbip`: every file is valid JSON, no table uses a name Power BI reserves, measures live on exactly one table and reference tables that exist, relationships reference real columns, partition sources point at files that exist, all six pages are defined, pages actually contain visuals, every visual field exists in the model, every projection resolves to a select, and no visual falls off the canvas. |

## Part 11. Rebuilding it from nothing

```
python -m pip install -r requirements.txt
for f in src/collect/*.py src/clean/*.py src/analysis/*.py src/models/*.py src/retail/*.py src/bigdata/*.py; do python "$f"; done
python src/analysis/24_web_export.py
python src/analysis/28_infographic.py
python src/report/60_build_report.py
```

Collection takes about 20 minutes, almost all of it deliberate rate limit waiting. The rest of the build takes about 3 minutes. Deleting `data/` entirely and rerunning rebuilds every cleaned and processed table, apart from the two hand entered files in `data/external`, which no script can regenerate.

```
python -m pytest tests/ -q
python -m ruff check src/ tests/
```

## Part 12. What I would tell myself at the start

**Build the helpers first.** The five modules in `src/utils/` took a session and saved far more than that. Everything downstream is shorter, and the ethics document can describe real behaviour because there is exactly one HTTP client.

**Write the issues register on day one.** `log_data_issue()` meant that every time a source surprised me I could write it down and keep going. Without it I would have either stopped to fix things in the wrong order, or forgotten them.

**Check every source against a second one.** PotterDB's film money was wrong by a factor of a thousand in one row and by a misplaced decimal in another. Both would have survived a careless parse.

**Suspect any join on a code.** The NAICS renumbering cost me 35 years of history and produced no error at all. Now I check row counts and date ranges *before and after* every join, as a habit.

**Keep the negative results.** The elasticity that could not be measured, the character network that had to be rebuilt, the classifier that loses on accuracy, the Dask comparison where pandas won: these are the parts of the project that a reader can actually trust, because they show what happens when the data does not cooperate. A project where everything worked is a project where nobody looked hard enough.

**Separate what code writes from what a person writes.** Results drift if a person can edit them; reasoning is lost if a script can overwrite it. Deciding which is which, early, prevented a whole class of problem.
