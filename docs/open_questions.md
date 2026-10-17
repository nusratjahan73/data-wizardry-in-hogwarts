# Open questions

When I planned this project I left six decisions open, because each one needs a judgement call and not only analysis. I carry each one below forward using a stated default so the build is not blocked. I do not treat any default as final.

Three further questions came up while I was building, and I list them after the six I expected from the start.

## Left open in my plan

### 1. Should the client be an unnamed composite retailer or a named proxy company?

**Default I am using:** unnamed composite, with a listed retailer used only where a financial benchmark is genuinely needed, and named as a proxy when it is.

**Why it matters:** naming a real company invites the reader to check my recommendation against that company's actual buying, which I have no visibility into. The composite avoids implying knowledge my analysis does not have.

### 2. Which service level should the safety stock calculation target?

**Default I am using:** 95 percent, held in `config.yaml` as `retail.service_level` and reported as an assumption everywhere it appears.

**Why it matters:** the service level drives the safety stock quantity directly. Moving it to 90 or 99 changes the recommended order, so I expose it in config and show the sensitivity rather than presenting the number as fixed.

### 3. How much of the buy should be reserved for the January position?

**Default I am using:** no single figure. I model several proportions (`retail.january_reserve_proportions`) and present the trade off, as I planned.

**Why it matters:** this is the commercial heart of my recommendation, and the right answer depends on the retailer's appetite for markdown risk, which is a business judgement rather than an analytical one.

### 4. Should the segmentation use four clusters to match the four houses?

**Default I am using:** no. I let the number of clusters be whatever the silhouette score and the elbow method jointly support, and apply house names afterwards to whatever number results.

**Why it matters:** choosing k to fit a theme would be fitting the data to the decoration. I ruled it out in my plan and in my methods note.

### 5. Which currency should be the reporting currency?

**Default I am using:** Canadian dollars, since the client is Canadian.

**Note:** box office is published in US dollars and I convert it at a single stated rate rather than a historic series, so that inflation and currency movement are not mixed in one column. I keep both the nominal US and the adjusted Canadian columns.

### 6. How far back should the fan text corpus reach?

**Default I am using:** as far as the archive allows, with the cut off stated.

**Currently blocked.** I collected no fan text, because Reddit requires free application credentials I do not have. See the credentials question below.

## Raised during the build

### 7. Two free API keys would bring back six analyses

Neither key costs anything and both take a few minutes to obtain, but each one needs an account that I have not set up.

| Key | What it unblocks | What happens without it |
|---|---|---|
| `BRICKSET_API_KEY` | Retail prices for the construction toy line | Module 3.4 (licensing premium) and module 5.3 (price model) run as substitutes, with set size in place of price. Piece counts, years and themes are all present; only money is missing. |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `REDDIT_HASH_SALT` | The fan text corpus | Modules 3.1 (sentiment over time), 4 (audience segmentation), 5.4 (sentiment classifier) and 7 (big data on text) run as substitutes on other data. |

I did not scrape around either. Both sites publish an API and ask that automated access go through it, and module 8 has to be able to state truthfully that I collected every source the way its owner asked. Scraping around a missing key would make that statement false.

Everything else in the project runs without any credential at all.

### 8. data/cleaned holds two folders that my first folder plan did not name

My first folder plan showed `data/cleaned` with seven source folders. My source list then added film performance and theme park attendance as sources in their own right, both hand entered into `data/external`. Cleaning them has to put the result somewhere, so I created `data/cleaned/films/` and `data/cleaned/parks/`, following the names in my source list and not the first folder plan.

The alternative would have been to leave cleaned film data in `data/external` beside the hand entered original, which would break the rule that raw inputs are never edited in place. This seemed to me the smaller departure, but it is a departure, so I record it here rather than pass over it.

`data/raw/hpapi/` exists for the same reason: my source list has the HP API as a source with its own `data/raw/hpapi/` destination, though my first folder plan showed seven folders and not eight.

### 9. src/report/ is a script folder that my first plan did not name

My first plan had six script folders and gave analysis the numbers 20 to 29, which is now full. `60_build_report.py` produces a deliverable rather than an analysis, so I gave it its own folder and number range rather than squeeze it into one that does not describe it.

It converts my generated Markdown documentation into Word, which matters because those documents are themselves written by code: `findings.md` is rewritten by every analysis script, `data_dictionary.md` by `19_data_dictionary.py`, and `build_log.md` as modules complete. Running the report last means the Word files always reflect the latest run rather than a version somebody exported once and forgot.

For those three, the Markdown remains the single source and the matching `.docx` in `docs/word/` is overwritten on every build, so editing one is a mistake; edit the Markdown. I first kept this document, the methods note, the ethics note and the build walkthrough as Word only, because they hold reasoning rather than results. That made them drift: whenever the project changed, the Word files kept describing the old version. So now every document lives as Markdown in `docs/`, and `60_build_report.py` turns all of them into Word on every run. No script writes the text of the reasoning documents. I edit their Markdown by hand, and the Word copies are only ever outputs.
