# Build log

One entry for each module I finished. The scripts add the entries themselves.

## Module 1. The Library: data collection and preparation

- **When:** 2026-09-02 07:04 UTC
- **Produced:** I wrote nine collection scripts (01 to 09) and ten cleaning scripts (10 to 19). I collected: PotterDB 6,140 records; HP API 514; Wikipedia pageviews 144,035 article days across 37 articles, daily from 2015-07-01 to 2026-09-01; Google Trends 40 of 40 group and geography pulls, monthly from 2004 to 2026 plus stitched weekly windows; Statistics Canada 3 tables, 1.37m rows; Rebrickable 4 bulk tables, 265 branded sets. I hand entered films.csv (11 films, 4 sources) and parks.csv (66 park years). I built 5 processed tables with 56,386 rows in total, a generated data dictionary that covers all 121 columns, and 26 tests, all passing.
- **Skipped:** Brickset prices (I had no API key) and the Reddit corpus (I had no credentials). Both scripts are written and they skip cleanly. See docs/open_questions.md item 7. This blocks modules 3.1, 3.4, 4, 5.3 and 7 until I have the keys.

## Module 5.1. Potions: interest forecast (stage 5, rough version complete)

- **When:** 2026-09-02 07:25 UTC
- **Produced:** I built a composite weekly attention index from four franchise Wikipedia articles, 577 weeks (2015-08 to 2026-08). I compared five models on a 52 week holdout that is split by time. Prophet was best at 13.1% MAPE, then SARIMA 26.9%, Holt-Winters 36.6% and drift naive 38.3%, against a seasonal naive baseline of 40.6%. All four fitted models beat the baseline. I wrote three demand scenarios to outputs/tables/demand_scenarios.csv with peak multiples of 1.33x, 2.07x and 3.23x. I measured every multiple on the composite itself.
- **Skipped:** I skipped nothing in 5.1. Modules 5.2 (interest to sales), 5.3 (price model, blocked until I have a Brickset key) and 5.4 (sentiment classifier, blocked until I have Reddit credentials) are not started yet. Module 6 retail is my next step.

## Modules 5.2 and 6. The bridge and Gringotts (stages 5 and 6 complete)

- **When:** 2026-09-02 23:47 UTC
- **Produced:** 5.2 interest to sales: a log log OLS at lags 0 to 3 with Newey-West errors. It controls for total Canadian retail and month dummies. The elasticity is 0.051 at the best lag (2 months) but it is not significant (p=0.071). It adds only +0.003 to adjusted R squared over a baseline of 0.929 that uses the controls alone. I report this as a negative result. 6 Gringotts: a monthly demand profile for Nov 2026 to Mar 2027, an order schedule by product type, a newsvendor service level, the January reserve trade off across eight proportions, and a sensitivity table on the pass through assumption. My recommendation: a CAD 2,486,052 retail buy, with 50 to 60 per cent held for January.
- **Skipped:** I skipped nothing. Modules 3.1, 3.2, 3.4, 4, 5.3, 5.4 and 7 are still to do. Of those, 3.1, 3.4, 4, 5.3, 5.4 and 7 are blocked by the two missing API keys.

## Module 3.2. The Library: character network (stage 7 gate met)

- **When:** 2026-09-02 23:56 UTC
- **Produced:** A network that shows how attention moves together across the 16 main cast members, over 582 complete weeks. I used Spearman correlations of week on week log changes, with edges at the 75th percentile. I computed degree, betweenness and eigenvector centrality. The findings file now holds six findings, which meets the stage 7 gate.
- **Skipped:** The network has no community structure. All 120 pairs correlate between 0.44 and 0.74 with no gap. So I report centrality as coupling strength and not as network position, and the finding says so.

## Module 8. The Ministry: ethics, security and trust (stage 11)

- **When:** 2026-09-03 00:00 UTC
- **Produced:** docs/ethics.md covers all seven required topics and points to specific scripts, config keys and tables. I ran the credential scan and did not just claim it was clean: three git history checks, all clean. I wrote docs/methods.md with every assumption in one table and the steps to reproduce the build.
- **Skipped:** Topic 5 (brand risk) cannot be answered with evidence because I collected no sentiment data. I state it as a risk I could not measure. I did not fill the gap with impressions.

## Module 2. The Great Hall: dashboard model (stage 9, partial)

- **When:** 2026-09-03 00:03 UTC
- **Produced:** A star schema generated from the processed tables: 5 dimensions, 5 facts, 19,530 rows, plus a relationships table, all in dashboard/model/. dashboard/model_notes.md has the schema diagram, the eight relationships with cardinality and cross filter direction, twenty DAX measures written out in full, and all six pages specified, each with a checked finding as its title.
- **Skipped:** The .pbix file and the six page screenshots. Power BI Desktop is a GUI application. It cannot be driven from a script, and it was not installed on my computer when I wrote this entry. So my third goal for the dashboard is not met. I wrote out the rebuild steps so that anyone with Power BI can finish it.

## Web deliverable. The data story as a page (my rules for web pages)

- **When:** 2026-09-03 00:10 UTC
- **Produced:** web/index.html plus three stylesheets (base, layout, chart) and three scripts (data, chart, page). I kept markup, styling and behaviour in three separate places, with no style block, no inline style attribute and no inline script block. I checked this in the browser: 0 of each. The three charts are drawn as inline SVG with no charting library. Every number is generated by 24_web_export.py from outputs/tables, so nothing on the page is typed by hand.
- **Skipped:** Nothing. I checked the rendering over a local HTTP server and there were no console errors.

## Module 9 and README (stage 12, communication)

- **When:** 2026-09-03 00:12 UTC
- **Produced:** infographic/asset_pack.md with the headline, the calendar strip, four figure choices, the palette, and a complete table that traces each number to its source, so every figure on the design can be checked. I wrote README.md last, as I had planned, with the finding in the first lines and a full account of what is not done.
- **Skipped:** The Canva working file and the PDF export. Canva is a browser application that cannot be driven from a script. Everything I would decide in front of it is already decided in the asset pack, and the same story is already built and checked as a web page.

## Rescope. All nine modules now build without any credential

- **When:** 2026-09-03 06:08 UTC
- **Produced:** I rebuilt modules 3.1, 3.4, 4, 5.3, 5.4 and 7 on data I can get without a key: narrative tone over chapter summaries, product line scaling, k-means product archetypes over 14,950 sets, a set size regression, a text classifier for spell categories, and a pandas vs Dask comparison over 1.56m rows of part inventory scaled to 12.5m. The module 9 infographic is now generated as PNG and PDF from outputs/tables. Nine findings. 24 scripts run from start to finish with nobody watching.
- **Skipped:** The .pbix file and its screenshots, and the Canva working file. Both need desktop software. I label every substitute module as a substitute in its docstring, in its finding and in the README.

## Final review. Docs in my own words and a last check of every number

- **When:** 2026-10-17 05:00 UTC
- **Produced:** I rewrote every comment, docstring and document in my own words and took the hyphens out of the prose. The project now has eleven findings in docs/findings.md, two more than the nine in the entry above. I checked every number in the README against outputs/tables and the collection logs. The counts there come from the last collection run on 3 September: 222,799 Statistics Canada rows and 1.66m Rebrickable rows across 5 tables, so they differ from the first entry in this log. I opened the Power BI project in Power BI Desktop 2.150 and saved my own .pbix, which is now in the repository as dashboard/DataWizardry.pbix. I removed infographic/asset_pack.md on purpose, because a list kept by hand goes stale, and 28_infographic.py now reads every number from outputs/tables. I dropped nltk from requirements.txt, because only vaderSentiment is used. I moved the methods note, the ethics note, the open questions and the build walkthrough from Word into Markdown in docs/, because as Word only files they kept describing the old project. 60_build_report.py now builds every Word file from Markdown on each run.
- **Skipped:** Nothing new. The gaps listed above still stand: no fan text, no retail prices and no number on brand risk.
