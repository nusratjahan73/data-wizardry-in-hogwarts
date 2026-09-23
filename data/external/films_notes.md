# Notes on films.csv

I hand entered this on 2 September 2026. Eleven rows. Section 6 of the brief allows
hand entry for a table this small, on condition that every figure is sourced and
dated, which the per column source fields in the CSV do.

## Why this table is not collected from PotterDB

I collected PotterDB in `01_potterdb.py` and it does carry budget and box office
for all eleven films, so using it would have been the shorter route. Reading it
against the published figures showed me it could not be trusted for money:

| Problem in PotterDB | What it says | What is correct |
| --- | --- | --- |
| Philosopher's Stone box office | `$1.018 million` | 966.6 million US dollars; the unit is wrong by a factor of a thousand |
| Deathly Hallows Part 2 box office | `$1,342 billion` | 1.312 billion US dollars; the comma is a decimal point |
| Prisoner of Azkaban release date | `2002-11-15` | 31 May 2004; it repeats the Chamber of Secrets date |
| Philosopher's Stone release date | `2001-11-04` | 15 November 2001 |
| Order of the Phoenix budget | `$150-200 million` | a range, not a number |
| Deathly Hallows budgets | `$250 million (shared with part 1)` | prose, not a number |

Three of those would survive a careless parse and quietly corrupt the return on
investment analysis in module 2. I keep PotterDB in the project for what it is
good at, which is the character and chapter catalogue, and I take the film
financials from sources that specialise in them. I repeat the comparison in
`docs/word/methods.docx` as a worked example of why a source should be checked against
a second one before it is trusted.

## Sources

- **Budget, domestic, international and worldwide gross:** The Numbers,
  Harry Potter franchise page. One consistent set from one source, so the
  columns add up across films.
- **Opening weekend, domestic, three day:** Box Office Mojo, J.K. Rowling's
  Wizarding World franchise page.
- **Critic and audience scores:** Rotten Tomatoes, per film page. `rt_critic_score`
  is the Tomatometer and `rt_audience_score` is the Popcornmeter, both read on
  2 September 2026.
- **Metacritic and CinemaScore:** the critical reception tables on the Wikipedia
  articles for the film series and for Fantastic Beasts.

## Known limitations, to be repeated in the report

1. **Two release date columns.** `release_date` is the first theatrical release
   anywhere, as The Numbers records it. `release_date_na` is the North American
   release that the opening weekend figure belongs to. They differ by up to five
   days. Any analysis joining opening weekend to a date must use
   `release_date_na`, or it will place the takings in the wrong week.

2. **Nominal dollars.** Every money column is in US dollars of its own year.
   Comparing 2001 with 2022 without adjusting is comparing different things.
   I use the CPI series collected in `05_statcan.py` to produce real columns
   during cleaning, and I keep both.

3. **The Deathly Hallows budget is a split, not a measurement.** The two parts
   were shot together on a reported combined budget of about 250 million US
   dollars. The Numbers assigns 125 million to each. That is a convention, not a
   fact, and it inflates the measured return on investment of Part 2, which is
   the more profitable half. Any profit ranking must say so.

4. **Worldwide gross includes re-releases.** Philosopher's Stone has been
   re-released more than once, and Box Office Mojo's worldwide total for it
   exceeds one billion dollars where The Numbers reports 966.6 million. The
   difference is re-release income earned up to twenty years after the original
   run. I use the single consistent set from The Numbers.

5. **Audience scores are not a fixed population.** A Popcornmeter score gathered
   in 2026 for a film released in 2001 reflects who chose to rate it over
   twenty-five years, not its audience at release. The critic score was fixed
   close to release; the audience score was not. The gap between them is
   readable, but it is not a like for like comparison, and the Reception page of
   the dashboard says so on the page rather than in a footnote.

6. **Eleven rows is a description, not a sample.** Section 18 of the brief
   forbids fitting a predictive model on this table, and module 5 keeps to that.
   Everything I do with these rows is descriptive.
