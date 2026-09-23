# Build log

One entry per completed module, appended by the scripts themselves.

## Module 1 - The Library: data collection and preparation

- **When:** 2026-09-02 07:04 UTC
- **Produced:** Nine collection scripts (01-09) and ten cleaning scripts (10-19). Collected: PotterDB 6,140 records; HP API 514; Wikipedia pageviews 144,035 article-days across 37 articles, daily 2015-07-01 to 2026-09-01; Google Trends 40 of 40 group and geography pulls, monthly 2004-2026 plus stitched weekly windows; Statistics Canada 3 tables, 1.37m rows; Rebrickable 4 bulk tables, 265 branded sets. Hand entered films.csv (11 films, 4 sources) and parks.csv (66 park-years). Built 5 processed tables totalling 56,386 rows, a generated data dictionary covering all 121 columns, and 26 acceptance tests, all passing.
- **Skipped:** Brickset prices (no API key) and the Reddit corpus (no credentials). Both scripts are written and skip cleanly; see docs/open_questions.md item 7. This blocks modules 3.1, 3.4, 4, 5.3 and 7 until keys exist.

## Module 5.1 - Potions: interest forecast (stage 5, rough version complete)

- **When:** 2026-09-02 07:25 UTC
- **Produced:** Composite weekly attention index over four franchise Wikipedia articles, 577 weeks (2015-08 to 2026-08). Five models compared on a time-based 52-week holdout: Prophet best at 13.1% MAPE, then SARIMA 26.9%, Holt-Winters 36.6%, drift naive 38.3%, against a seasonal naive baseline of 40.6%. All four fitted models beat the baseline. Three demand scenarios written to outputs/tables/demand_scenarios.csv with peak multiples of 1.33x, 2.07x and 3.23x, every multiple measured on the composite itself.
- **Skipped:** Nothing skipped in 5.1. Modules 5.2 (interest-to-sales), 5.3 (price model, blocked on Brickset key) and 5.4 (sentiment classifier, blocked on Reddit credentials) not yet started. Module 6 retail is the next step.

## Modules 5.2 and 6 - the bridge and Gringotts (stages 5 and 6 complete)

- **When:** 2026-09-02 23:47 UTC
- **Produced:** 5.2 interest-to-sales: log-log OLS at lags 0-3 with Newey-West errors, controlling for total Canadian retail and month dummies. Elasticity 0.051 at the best lag (2 months) but not significant (p=0.071), adding only +0.003 to adjusted R-squared over a controls-only baseline of 0.929. Reported as a negative result. 6 Gringotts: monthly demand profile Nov 2026-Mar 2027, order schedule by product type, newsvendor service level, January reserve trade-off across eight proportions, and a sensitivity table on the pass-through assumption. Recommendation: CAD 2,486,052 retail buy, 50-60 per cent held for January.
- **Skipped:** Nothing skipped. Modules 3.1, 3.2, 3.4, 4, 5.3, 5.4 and 7 remain; 3.1, 3.4, 4, 5.3, 5.4 and 7 are blocked on the two missing API keys.

## Module 3.2 - The Library: character network (stage 7 gate met)

- **When:** 2026-09-02 23:56 UTC
- **Produced:** Attention co-movement network over the 16 main cast members, 582 complete weeks. Spearman correlations of week-on-week log changes, edges at the 75th percentile. Degree, betweenness and eigenvector centrality computed. Findings file now holds six findings, meeting the stage 7 gate.
- **Skipped:** The network has no community structure: all 120 pairs correlate between 0.44 and 0.74 with no gap, so centrality is reported as coupling strength rather than network position, and the finding says so.

## Module 8 - The Ministry: ethics, security and trust (stage 11)

- **When:** 2026-09-03 00:00 UTC
- **Produced:** docs/ethics.md covering all seven required topics with reference to specific scripts, config keys and tables. Credential scan run rather than asserted: three git history checks, all clean. docs/methods.md written with every assumption in one table and the build reproduction steps.
- **Skipped:** Section 5 (brand risk) cannot be answered with evidence because no sentiment data was collected. That is stated as an unquantified risk rather than filled with impressions.

## Module 2 - The Great Hall: dashboard model (stage 9, partial)

- **When:** 2026-09-03 00:03 UTC
- **Produced:** Star schema generated from the processed tables: 5 dimensions, 5 facts, 19,530 rows, plus a relationships table, all in dashboard/model/. dashboard/model_notes.md carries the schema diagram, the eight relationships with cardinality and cross-filter direction, twenty DAX measures written out in full, and all six pages specified with a verified finding as the title.
- **Skipped:** The .pbix file and the six page screenshots. Power BI Desktop is a GUI application that cannot be driven from a script and is not installed on the build machine. Section 8 acceptance criterion 3 is therefore not met; the rebuild steps are written out so a person with Power BI can close it.

## Web deliverable - the data story as a page (section 4 web rules)

- **When:** 2026-09-03 00:10 UTC
- **Produced:** web/index.html plus three stylesheets (base, layout, chart) and three scripts (data, chart, page). Markup, styling and behaviour kept in three separate places with no style block, no inline style attribute and no inline script block, verified in the browser: 0 of each. Three charts drawn as inline SVG with no charting library. Every number is generated by 24_web_export.py from outputs/tables, so nothing on the page is typed by hand.
- **Skipped:** Nothing. Rendering verified over a local HTTP server with no console errors.

## Module 9 and README (stage 12, communication)

- **When:** 2026-09-03 00:12 UTC
- **Produced:** infographic/asset_pack.md with the headline, calendar strip, four figure choices, the palette, and a complete number-to-source trace table so every figure on the design is checkable. README.md written last, per section 4, with the finding in the first lines and a full account of what is not done.
- **Skipped:** The Canva working file and the PDF export. Canva is a browser application that cannot be driven from a script. Everything that would be decided in front of it is decided in the asset pack, and the same story is already built and verified as a web page.

## Rescope - all nine modules now build without any credential

- **When:** 2026-09-03 06:08 UTC
- **Produced:** Modules 3.1, 3.4, 4, 5.3, 5.4 and 7 rebuilt on data obtainable without a key: narrative tone over chapter summaries, product line scaling, k-means product archetypes over 14,950 sets, a set-size regression, a spell-category text classifier, and a pandas vs Dask comparison over 1.56m rows of part inventory scaled to 12.5m. Module 9 infographic now generated as PNG and PDF from outputs/tables. Nine findings; 24 scripts run unattended end to end.
- **Skipped:** The .pbix file and its screenshots, and the Canva working file. Both need desktop software. Every substitute module is labelled as a substitute in its docstring, its finding and the README.

