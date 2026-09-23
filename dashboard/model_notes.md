# Module 2. The Great Hall: dashboard model notes

Everything needed to build the Power BI dashboard: the star schema, the
relationships, the DAX for every measure, and the six pages with the finding each
one carries.

**A Power BI project is generated.** Run
[`src/analysis/29_build_powerbi_project.py`](../src/analysis/29_build_powerbi_project.py)
and it writes [`pbip/DataWizardry.pbip`](pbip/), a Power BI project in Microsoft's
open `.pbip` format containing the eleven tables, the eight relationships and all
twenty measures below. Power BI Desktop opens it directly, and **File → Save As**
produces the `.pbix`.

A `.pbix` cannot be generated from a script: it is a ZIP around a compiled
Analysis Services model that only Power BI Desktop can produce. `.pbip` is the
text format that gets around that.

**Confirmed opening.** The project loads in Power BI Desktop 2.150 (25.12) with
all eleven tables, the twenty measures on `Key Measures`, and the six named
pages. Getting there took one round trip: the first version named the measures
table `Measures`, which Power BI reserves, and the whole file was rejected with
"Unsupported Table name". That is fixed, the generator now refuses to emit any
reserved name, and `tests/test_powerbi_project.py` fails if one appears.

The generator still cannot open its own output, because nothing here can drive a
GUI application. It validates JSON well-formedness, relationships that point at
columns which really exist, and M queries that point at files which are really on
disk, and no further. Anything beyond that has to be found by opening it.

### Applying the palette

The report ships with Power BI's default colours. To match the figures, the
infographic and the web page, import the theme once:

**View → Themes → Browse for themes →** `dashboard/DataWizardryTheme.json`

It sets dark turquoise as the primary series colour, deep blue as the second,
gold for callouts, and the text styles. The same values live in
`src/utils/plotting.py` and `web/css/base.css`; all three must move together, or
the three deliverables stop looking like one piece of work.

The theme is a separate file rather than embedded in the project because
embedding it means editing the report's resource packages, which cannot be
tested from here, and a malformed theme resource stops the whole report opening.
A one-click import is not worth that risk.

### Opening it

1. Open `pbip/DataWizardry.pbip` in Power BI Desktop.
2. On first open it warns that relationships need refreshing and that tables have
   no data. That is expected, not a fault: a project defines the model but stores
   no rows, so nothing has been read yet. Click **Refresh now**, which runs the M
   queries against `dashboard/model/*.csv`.
3. **File → Save As** produces the `.pbix`.

The six pages exist but are empty, so the last step is dropping visuals onto them
against a model where every measure is already defined. And the visual layout is not
generated: the six pages exist and are named, but they are empty, because the
report format for visuals is intricate, cannot be tested from here, and a corrupt
report that will not open would be worse than an empty one that does. Dropping
visuals onto pre-named pages against a model that already has every measure is
the quick part.

The M queries use absolute paths, so moving the repository means rerunning the
generator.

---

## The star schema

Five dimensions, five facts. Ten files in [`model/`](model/), regenerated from
`data/processed` whenever the analysis is rerun.

```
                    ┌─────────────┐
                    │  dim_date   │  456 rows, grain: month
                    └──────┬──────┘
                           │ date_key
     ┌──────────────┬──────┴───────┬──────────────┬─────────────────┐
     │              │              │              │                 │
┌────┴─────┐  ┌─────┴──────┐  ┌────┴─────┐  ┌─────┴──────┐  ┌───────┴────────┐
│fact_film │  │fact_atten- │  │fact_ret- │  │fact_prod-  │  │fact_park_      │
│_perform- │  │tion_month- │  │ail_month-│  │uct_release │  │attendance      │
│ance   11 │  │ly    9,624 │  │ly  9,015 │  │       265  │  │           66   │
└────┬─────┘  └─────┬──────┘  └──────────┘  └─────┬──────┘  └────────────────┘
     │ film_key     │ series                      │ theme_key
┌────┴─────┐  ┌─────┴─────────┐            ┌──────┴──────────┐
│ dim_film │  │ dim_character │            │dim_product_theme│
│    11    │  │      16       │            │       5         │
└──────────┘  └───────────────┘            └─────────────────┘

dim_country (61 rows) is unrelated in the model and filters the
Geography page through a measure, not a relationship. See the note below.
```

### Relationships to create

Machine-readable in [`model/relationships.csv`](model/relationships.csv).

| From | Column | To | Column | Cardinality | Cross filter |
| --- | --- | --- | --- | --- | --- |
| dim_date | date_key | fact_film_performance | date_key | 1:* | single |
| dim_date | date_key | fact_attention_monthly | date_key | 1:* | single |
| dim_date | date_key | fact_retail_monthly | date_key | 1:* | single |
| dim_date | date_key | fact_product_release | date_key | 1:* | single |
| dim_date | date_key | fact_park_attendance | date_key | 1:* | single |
| dim_film | film_key | fact_film_performance | film_key | 1:1 | both |
| dim_product_theme | theme_key | fact_product_release | theme_key | 1:* | single |
| dim_character | article | fact_attention_monthly | series | 1:* | single |

### Three modelling decisions worth defending

**One grain per fact table, and everything monthly.** The attention data is
naturally weekly and is rolled to monthly before it enters the model. Publishing
both a weekly and a monthly attention fact against one date dimension is the
standard way a star schema silently double counts, so only one grain exists.

**`dim_character` joins on `article`, not on a surrogate key.** The character
dimension is restricted to the sixteen main-cast members that have a mapped
Wikipedia article, and `article` is the only column that appears on both sides.
Introducing a surrogate key would add a lookup step without adding information at
this size. The join is one-to-many because `fact_attention_monthly` also contains
franchise, film and control series that no character matches; those rows simply
have no character context, which is correct.

**`dim_country` is deliberately unrelated.** The regional search interest data is
a single cross-sectional snapshot per keyword group, not a time series, so it has
no `date_key` and cannot join the rest of the model without inventing one. It
feeds the Geography page directly. Relating it would create an ambiguous path and
a filter that appears to work but is meaningless.

---

## DAX measures

Section 8 names five measures. All five are here, plus the supporting ones the
pages need. Paste into a single measure table.

### Film performance

```dax
Total Budget =
SUM ( fact_film_performance[budget_usd] )
```

```dax
Total Worldwide Gross =
SUM ( fact_film_performance[worldwide_gross_usd] )
```

```dax
Profit =
[Total Worldwide Gross] - [Total Budget]
```

```dax
Profit Margin =
DIVIDE ( [Profit], [Total Worldwide Gross] )
```

```dax
Return on Budget =
DIVIDE ( [Total Worldwide Gross], [Total Budget] )
```

`Profit` here is gross of marketing spend and of the exhibitor's share, so it
overstates true profit. Label it "gross profit" on every visual.

### Cumulative franchise revenue

```dax
Cumulative Franchise Revenue =
CALCULATE (
    [Total Worldwide Gross],
    FILTER (
        ALLSELECTED ( dim_date[date_key] ),
        dim_date[date_key] <= MAX ( dim_date[date_key] )
    )
)
```

`ALLSELECTED` rather than `ALL` so the running total respects the era slicer
instead of ignoring it, which is what a reader filtering to one era expects.

### Attention

```dax
Mean Weekly Attention =
AVERAGE ( fact_attention_monthly[mean_weekly_value] )
```

```dax
Attention YoY Change =
VAR CurrentValue = [Mean Weekly Attention]
VAR PriorValue =
    CALCULATE (
        [Mean Weekly Attention],
        DATEADD ( dim_date[month_start], -12, MONTH )
    )
RETURN
    DIVIDE ( CurrentValue - PriorValue, PriorValue )
```

```dax
Franchise Attention =
CALCULATE (
    [Mean Weekly Attention],
    fact_attention_monthly[source] = "wikipedia_pageviews",
    fact_attention_monthly[group] = "franchise"
)
```

### Retail and seasonality

```dax
Category Sales Real =
CALCULATE (
    SUM ( fact_retail_monthly[sales_thousands_cad_real] ),
    fact_retail_monthly[is_focus_category] = TRUE ()
)
```

```dax
Total Retail Sales Real =
CALCULATE (
    SUM ( fact_retail_monthly[sales_thousands_cad_real] ),
    fact_retail_monthly[is_total_retail] = TRUE ()
)
```

```dax
Seasonality Index =
VAR MonthlyValue = [Category Sales Real]
VAR AnnualAverage =
    CALCULATE (
        AVERAGEX ( VALUES ( dim_date[date_key] ), [Category Sales Real] ),
        ALLEXCEPT ( dim_date, dim_date[year] )
    )
RETURN
    DIVIDE ( MonthlyValue, AnnualAverage ) * 100
```

100 is an average month for that year. December reads about 172 on the focus
category, which is the number the whole timing argument rests on.

```dax
Category Share of Total Retail =
DIVIDE ( [Category Sales Real], [Total Retail Sales Real] )
```

### Product pricing

```dax
Total Pieces =
SUM ( fact_product_release[num_parts] )
```

```dax
Average Price Per Piece =
AVERAGE ( fact_product_release[price_per_piece_cad] )
```

```dax
Average Price Per Piece Real =
AVERAGE ( fact_product_release[price_per_piece_cad_real] )
```

Both price measures return blank until a Brickset API key is supplied and
`07_brickset.py` has run. That is correct behaviour, not a broken measure: the
Product line page should show an explicit "price source not collected" note
rather than a zero, because zero is a price and blank is an absence.

### Park attendance

```dax
Total Attendance =
SUM ( fact_park_attendance[attendance] )
```

```dax
Attendance Index vs Pre-Opening =
AVERAGE ( fact_park_attendance[attendance_index_vs_year_before_opening] )
```

---

## The six pages

Section 8 requires every page to carry a one-line title written as a finding
rather than a label. The titles below are the findings the analysis actually
produced; where a page's finding depends on data that was not collected, that is
stated rather than papered over.

### 1. Overview

**Title:** "Franchise attention has fallen 57 per cent since its 2023 peak, while
the new series' own article has risen a hundredfold."

Both halves are measured. The composite of the four franchise articles averaged
282,101 weekly views in 2023 and 121,570 in 2026; the show's own article went
from about 40 views a day through 2024 to roughly 5,000 from mid-2025. The old
franchise and the new series are moving in opposite directions, which is the
single most important thing a category buyer needs to understand about 2026.

Line chart of `Franchise Attention` by month across the full window, with
`Cumulative Franchise Revenue` on a secondary axis. Cards for total franchise
revenue, film count and the current attention level. The headline finding from
[`../docs/findings.md`](../docs/findings.md) stated in a text box on the page, not
in a tooltip.

### 2. Return on investment

**Title:** "Deathly Hallows Part 2 returned 10.5 times its assigned budget; The
Secrets of Dumbledore returned 2.0, and every Fantastic Beasts film did worse
than every Harry Potter film."

Scatter of `Total Budget` against `Total Worldwide Gross`, one point per film,
bubble size `Profit`, colour by `dim_film[era]`. Include a note on the page that
the Deathly Hallows budget split is a convention rather than a measurement, since
it flatters Part 2.

### 3. Reception

**Title:** "Audiences rated The Secrets of Dumbledore 37 points above critics;
Goblet of Fire is the only film critics liked markedly more than audiences."

The three largest gaps are Secrets of Dumbledore at -37, Crimes of Grindelwald at
-17 and Goblet of Fire at +14, where a negative gap means audiences scored it
higher. The pattern is worth a buyer's attention: the two weakest-reviewed films
in the franchise are also the two where the audience most disagreed with the
critics, which is a caution against reading critical reception as a demand
signal.

Scatter of `rt_critic_score` against `rt_audience_score` with a 45-degree
reference line, labelled per film. The page must carry the caveat that audience
scores were gathered over twenty-five years while critic scores were fixed at
release, so the gap is readable but not like-for-like.

### 4. Geography

**Title:** "Franchise search interest is near-saturated across Western markets:
Canada ranks 9th of 61 countries at 97, within two points of the leaders."

The compression at the top of this ranking is partly a Trends artefact, since the
index is scaled to the maximum within the request, so the honest reading is that
Canada is a first-tier market rather than that it is precisely ninth. The page
should say so.

Filled map from `dim_country`, Canada highlighted through
`dim_country[is_canada]`. Because this dimension is unrelated to the date table,
the page carries no date slicer, and a text note says the data is a snapshot
rather than a series.

### 5. Product line

**Title:** *Blocked.* Intended: "Price per piece on the branded line has risen
faster than inflation, which is the licensing premium a buyer pays."

Scatter of `Average Price Per Piece` by release year with a trend line and the
inflation-adjusted comparison. **This page cannot be completed** until a Brickset
key is supplied, because Rebrickable carries no retail price. Piece counts,
years, themes and minifigure counts are all present, so the page can be built and
will populate the moment the price source is collected.

### 6. Timing

**Title:** "The category peaks in December at 172 and collapses to 86 in January,
while franchise attention barely moves, so the premiere lands after the money has
been spent."

This is the page that carries the central argument. `Seasonality Index` by month
for the focus category and for total retail, with `Franchise Attention` overlaid
on a secondary axis, the premiere date marked, and the gift-buying window shaded.
The equivalent static figure is
[`../images/figures/seasonality_attention_vs_retail.png`](../images/figures/seasonality_attention_vs_retail.png).

---

## Slicers

Two, on every page, as section 8 requires.

- **Era** from `dim_date[era]`: `original` (2001-2011), `middle` (2012-2022),
  `revival` (2023-2027). Values come from `eras` in `config.yaml`, so changing
  the boundaries there and rerunning the star schema script updates the slicer.
- **Country** from `dim_country[country_name]`, affecting the Geography page.
  Because that dimension is unrelated, it cannot cross-filter the other pages,
  and the Geography page should say so on the page rather than leaving a reader
  to discover that the slicer does nothing elsewhere.

Set both to sync across pages in the Sync Slicers pane.

---

## Rebuilding from scratch

1. Run `python src/analysis/23_star_schema.py`, which writes ten CSVs into
   `dashboard/model/`.
2. In Power BI Desktop: **Get Data → Text/CSV**, and load all ten.
3. In **Model view**, create the eight relationships from the table above.
   Power BI will auto-detect some of them, and it will guess wrong at least once,
   so check each cardinality and cross-filter direction against the table.
4. Mark `dim_date` as a date table using `month_start`.
5. Create a blank table called `Measures`, and paste the DAX above into it.
6. Build the six pages.
7. Export each page to PNG and save into `images/dashboard/`, then copy the
   figures used in the report into `images/figures/`.

Step 7 is what closes section 8's third acceptance criterion, and it is the only
step here that needs a person with Power BI installed.
