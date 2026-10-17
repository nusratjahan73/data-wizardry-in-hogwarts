# Methods and assumptions

What I did, why I did it that way, and every assumption in one place. I have written it for someone who wants to disagree with a specific choice of mine rather than with the project as a whole.

Companion documents: `findings.md` for results, `ethics.md` for governance, `data_dictionary.md` for every column, `open_questions.md` for decisions that are still open, and `build_log.md` for what each module produced.

## 1. Environment

Python 3.14.2 on Windows 11. I pinned every package version in `requirements.txt` to the one I actually installed and exercised, read back from `pip` rather than typed from memory.

I left out three packages from my first plan. `pyspark` installs cleanly but requires a Java runtime, and there is no JVM on my build machine. My plan allowed "PySpark or Dask", so I planned module 7 around Dask. I also dropped `plotly`, because every figure is matplotlib and the dashboard is Power BI, and `nltk`, because the `vaderSentiment` package does the tone scoring on its own. I expected `prophet` to be unavailable on Python 3.14; it turned out to work, so I use it.

I seed randomness from `project.random_seed` in config, and every script that needs a seed reads it from there.

## 2. Corrections to my first assumptions

I found four things in my first plan to be wrong when I checked them against the live sources. I record each here because each would have cost me time or silently corrupted a result.

**PotterDB has no flat `chapters` endpoint.** `/v1/chapters` returns 404. Chapters hang off each book at `/v1/books/<slug>/chapters`, so I collect them that way. My early note that chapter records carry no character list was correct, which is why I build the module 3.2 network from attention instead.

**Google Trends returns monthly data for long windows.** I planned to use weekly search interest since 2004. Google chooses granularity from the width of the request and gives the caller no say: a request spanning 2004 to 2026 returned 273 monthly points. So I collect the series twice, as a full range monthly pull for the long history and as eight overlapping four year windows for weekly detail, which I then rescale onto one series using their shared year.

**The archived StatCan table uses a different classification.** I knew from the start that table 20-10-0008 is archived. It ends in December 2022. The larger problem is underneath: the archived table is coded to NAICS 2017 and the active table to NAICS 2022, and the 2022 revision renumbered the category this project is about from 451 to 459A. Concatenating on the code alone leaves the focus category with no history before 2017, silently, while total retail trade looks fine because its code never changed. I wrote a crosswalk in config mapping the old codes to the new ones, and my overlap check then measures how well each mapped pair agrees. 459A agrees with 451 to within 1.3% across 72 overlapping months.

**PotterDB's film financials cannot be trusted.** Philosopher's Stone is listed at "$1.018 million" and Deathly Hallows Part 2 at "$1,342 billion"; Prisoner of Azkaban repeats the Chamber of Secrets release date. Three of these would survive a careless parse. So I hand entered film money from The Numbers, Box Office Mojo and Rotten Tomatoes, keeping PotterDB's own figures alongside under a `potterdb_` prefix so I can show the discrepancy rather than assert it. Full comparison in `data/external/films_notes.md`.

## 3. Data sources and substitutions

I attempted eight sources; six produced data.

| Source | Status | What it gave |
|---|---|---|
| PotterDB | Collected | 6,140 records across six endpoints |
| HP API | Collected | 514 records, better attribute completeness on the main cast |
| Wikipedia pageviews | Collected | 144,035 article days, daily 2015-07-01 to 2026-09-01, 37 articles |
| Google Trends | Collected | 40 of 40 pulls; monthly 2004-2026 plus stitched weekly windows |
| Statistics Canada | Collected | 3 tables, 222,799 rows, retail 1991-2026 and CPI 1914-2026 |
| Rebrickable | Collected | 265 branded sets, 2001-2026, via keyless bulk dumps |
| Brickset | **Not collected** | No API key. This is the only retail price source. |
| Reddit | **Not collected** | No credentials. This is the only fan text source. |

I hand entered 11 films and 66 park years, sourcing and dating every row, and validated both with `09_external_check.py`.

### What the two missing sources cost

Six analyses could not run the way I first planned them: 3.1, 3.4, 4, 5.3, 5.4 and 7. I did not scrape around either source, and my reasoning is in `ethics.md` section 1. Instead I replaced each one with an analysis I could run on the data I had. Section 3b lists every replacement.

### Attention series substitution

My fallback plan was for pageviews to become the primary attention series if search interest failed, with the analysis start moving from 2004 to 2015. Search interest did not fail, but I use pageviews as the primary series anyway, for a different reason: pageviews are actual counts on a stable definition, while I had to stitch the weekly Trends series across eight independently normalised windows. I retain Trends as an independent second series and for the Canadian and regional cuts, which pageviews cannot provide.

The practical effect is that my analysis window is 2015 onward for anything resting on the attention series, and 1991 onward for anything resting on retail.

## 3b. Where the analysis substitutes for what I first planned

I could not run six analyses as planned, because they need fan text or retail prices that no credential free source provides. I replaced each rather than skipping it, and I label each replacement as one wherever it appears.

| What I first planned | Needs | What I did instead |
|---|---|---|
| 3.1 Sentiment over time on fan reviews | Reddit corpus | VADER tone over chapter summaries plus character presence in book one, which is what season one adapts |
| 3.4 Licensing premium, price per piece | Brickset prices | How the line scales to the release calendar; reported as a confounded null |
| 4 Audience segmentation from posting behaviour | Reddit corpus | Product archetypes: k-means over 14,950 sets on construction features |
| 5.3 Price model | Brickset prices | Set size model, same specification with size as the target |
| 5.4 Sentiment classifier | Labelled sentiment text | Spell category classifier, real labels, same evaluation |
| 7 Big data on a text corpus | Large text corpus | pandas against Dask on 1.56m rows of part inventory, replicated to 12.5m |

Two of these deserve a note beyond the table.

**Module 4 is not audience segmentation and no amount of method fixes that.** Segmenting people needs data about people. I do not attempt the generation comparison I had also planned.

**Module 7 processes tables, not text.** I tried to build a large Wikipedia article corpus instead and abandoned it when the API began returning HTTP 429 with Retry-After of 36 to 53 seconds on nearly every request, which put the run at roughly ten hours. I deleted that collector rather than leave it in the repository unable to run, and I recorded the attempt in `logs/data_issues.md`.

## 4. Money

**Currency.** Canadian dollars throughout, because the client is Canadian.

**Conversion.** Box office is published in US dollars and I convert it at a single stated rate of 1.37, held in `USD_TO_CAD` in `17_clean_external.py`. I use a single rate rather than a historic series deliberately: a historic series would mix two distinct effects, inflation and currency movement, inside one column, and the reader could not tell which was which.

**Inflation adjustment.** I deflate historic money by the Statistics Canada all-items CPI (18-10-0004-01) to the latest available month. I always keep both columns: `_usd` is nominal in dollars of its own year, `_cad_real` is adjusted.

**The caveat that matters.** Deflating US box office by Canadian CPI measures what those takings would be worth to a Canadian buyer today. It is not the US real box office and must not be described as such.

## 5. Modelling choices

**I split time series by time, never at random.** My forecast holds out the final 52 weeks and never fits on them.

**I report every model against a baseline.** For the forecast that baseline is a seasonal naive; for the interest to sales regression it is the same specification with the attention term removed.

**Logs, not levels.** I fit attention on a log scale so that seasonal swing scales with the level, which is how attention behaves: a busy year has bigger Decembers.

**Spearman, not Pearson, for the character network.** Several weeks in this data are enormous, and a Pearson coefficient would be dominated by them.

**Week on week differences before correlating.** Every character article shares the franchise trend. On raw levels every pair correlates above 0.9 and the network measures nothing but that trend.

**Newey-West standard errors on the retail regression.** Monthly retail is autocorrelated; ordinary errors would make the attention coefficient look more precise than it is.

**I treat the eleven film rows as descriptive only.** That is a rule I set at the start and I keep to it throughout. I fit no predictive model to them.

**I exclude pandemic months rather than adjusting them.** March 2020 to June 2021 for the elasticity, and calendar years 2020 and 2021 for seasonality and park attendance. Canadian retail in April 2020 is a data point about closed shops. The exclusion is my judgement, it sits in the code and config, and every affected finding names it.

**I impose the premiere response rather than fitting it.** No model can learn the effect of an event that has never happened in this series. My statistical forecast supplies the counterfactual; my three scenarios add an event response taken from multiples I measured on real franchise events. The scenarios are therefore three readings of evidence, **not confidence intervals**, and I never describe them as such.

## 6. Every assumption, in one table

I keep a machine readable copy at `outputs/tables/retail_assumptions.csv`, which module 6 generates so it cannot drift from what my code used.

| Assumption | Value | Where it lives | Why |
|---|---|---|---|
| Reporting currency | CAD | `project.reporting_currency` | My default; client is Canadian |
| USD to CAD rate | 1.37 | `17_clean_external.py` | Single stated rate, not a historic series |
| Annual category baseline | $4,200,000 | `retail.category_baseline_sales_cad` | I had no retailer's internal sales |
| Attention to sales pass through | 0.35 | `retail.attention_pass_through` | Module 5.2 could not measure it. Largest single uncertainty in the project. |
| December share before the premiere | 0.85 | `retail.december_share_before_premiere` | The premiere is on the 25th; a monthly profile cannot split it without this |
| Gross margin rate | 0.42 | `retail.gross_margin_rate` | Licensed product |
| Markdown rate | 0.40 | `retail.markdown_rate` | Clearing unsold seasonal stock |
| Annual holding cost | 0.25 | `retail.holding_cost_rate_annual` | Capital, space, shrink |
| Goodwill multiplier on a lost sale | 1.15 | `retail.lost_sale_goodwill_multiplier` | Customer who came for it and left without it |
| Service level target | 0.95 | `retail.service_level` | My default, to be confirmed with the retailer |
| Service level implied by costs | 0.93 | derived | Newsvendor critical ratio; nearly agrees with the default |
| Imported lead time | 120 days | `retail.lead_time_days.imported` | Sea freight plus port and DC handling |
| Domestic lead time | 45 days | `retail.lead_time_days.domestic` |  |
| Reprinted book lead time | 75 days | `retail.lead_time_days.reprinted_books` |  |
| Average unit retail | $34.00 | `retail.average_unit_retail_cad` | Blended across books, gift and toy lines |
| Store count | 190 | `retail.store_count` | Composite chain |
| Random seed | 42 | `project.random_seed` | Reproducibility |
| Edge threshold, character network | 75th percentile | `22_character_network.py` | I chose it from the data; a fixed value gave a complete graph |
| Forecast holdout | 52 weeks | `30_interest_forecast.py` | One full seasonal cycle |

### The assumption to argue with first

`attention_pass_through`. In module 5.2 I tried to measure it and got an elasticity of 0.051 with a confidence interval spanning zero (p = 0.071), because NAICS 459A contains every bookshop and hobby shop in Canada and one franchise inside it sits below the noise floor. Rather than present a not significant coefficient as a measurement, I declare the conversion as an assumption and report the recommendation across a range of it in `outputs/tables/retail_sensitivity.csv`. Across the range 0.15 to 0.70 the central season runs from $1.99m to $2.53m, a spread of $0.54m against a gap of $0.66m between my low and high demand scenarios.

If you are reviewing this work, start here.

## 7. Reproducing the build

I number the scripts so that filename order is run order. The one exception is that 24_web_export.py and 28_infographic.py read tables made by the models and retail scripts, so I run those two again at the end, and the report script goes last.

```
python -m pip install -r requirements.txt
for f in src/collect/*.py src/clean/*.py src/analysis/*.py src/models/*.py src/retail/*.py src/bigdata/*.py; do python "$f"; done
python src/analysis/24_web_export.py
python src/analysis/28_infographic.py
python src/report/60_build_report.py
```

Collection takes about 20 minutes, almost all of it deliberate rate limit waiting; the rest of the build takes about 3 minutes. Deleting `data/` entirely and rerunning rebuilds every cleaned and processed table, apart from the two hand entered files in `data/external`, which no script can regenerate.

```
python -m pytest tests/ -q
python -m ruff check src/ tests/
```

## 8. Known weaknesses

I rank these by how much they threaten my recommendation.

1. **The pass through assumption is unmeasured.** Section 6 above.
1. **The category baseline is stated, not observed.** I had no retailer's internal sales, so the absolute size of my recommendation is only as good as that figure. The *shape* of the recommendation, meaning the January split, the order dates and the relative scenario spread, does not depend on it.
1. **Brand risk is unquantified.** I collected no sentiment data, so the downside from public controversy is a known unknown. See `ethics.md` section 5.
1. **No streaming premiere exists in my event sample.** The four events I measured are three cinema releases and one trailer. A premiere releasing eight episodes weekly has no analogue in the data.
1. **English language attention standing in for Canadian demand.** This underweights Quebec, which matters for a Canadian retailer.
1. **Three of six order by dates have already passed** as of my analysis date of 2 September 2026, including imported product for the January position. That is a finding about timing, not a defect in the analysis, but it constrains what the retailer can now act on.
