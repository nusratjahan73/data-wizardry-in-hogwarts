# Ethics, security and trust

How I obtained, protected and interpreted the data in this project. I cover seven topics here, and I answer each one for this project and not in general terms, so each section below names the source, the script and the line of the build it applies to.

I wrote this after finishing the collection and analysis, so it describes what I actually did rather than what I intended.

## 1. Terms of use

Before collecting anything I checked each source for whether automated access is permitted, what rate limit applies, and what identification the operator asks for. I route every outbound request in this project through one client, `src/utils/http.py`, which sets a `User-Agent` naming the project on every request and spaces calls to the published limit. That is what lets the table below describe my behaviour rather than my intentions.

| Source | Automated collection | Rate limit applied | What I did to comply |
|---|---|---|---|
| PotterDB | Permitted, public REST API, no key | 900 requests/hour published; 4.0s minimum gap enforced in `config.yaml` | 55 paged calls for characters plus one per book for chapters, evenly spaced. 282 seconds for 6,140 records. |
| HP API | Permitted, public, no key | None published; 1.0s gap applied anyway | Two calls total. |
| Wikimedia pageviews | Permitted, official analytics API, no key | No hard limit published; 0.2s gap applied, and I honour the API's own `Retry-After` header | 37 calls. The server asked for a pause three times during my run and the client waited the requested 5, 49 and 53 seconds rather than retrying immediately. |
| Google Trends | Not an official public API. The endpoint is undocumented and throttles aggressively | 12s gap between requests, plus an additional 12s between groups | I collected through `trendspy`, the maintained successor to the archived `pytrends`. 40 requests took 696 seconds, almost all of it deliberate waiting. |
| Statistics Canada | Permitted, public web data service under the Statistics Canada Open Licence | None published; 2.0s gap applied | I used the bulk table download rather than per series calls: three requests instead of several thousand. |
| Rebrickable | Bulk catalogue dumps are published for public download | None on the CDN | Five files. I did not use the keyed API, so no key was required and anyone cloning the repository can reproduce the source. |
| Brickset | Permitted with a free API key | 2.0s gap configured | **Not collected.** I had no key. See below on what I did not do instead. |
| Reddit | Permitted only through the official API with registered credentials | `praw` handles Reddit's own limits | **Not collected.** I had no credentials. |

### The two sources I did not collect

Brickset and Reddit both publish an API and both ask that automated access go through it. I collected neither, because I had no credentials, and in both cases an alternative was available which I deliberately did not take:

- Brickset's set data is visible on its public web pages and I could have scraped it.
- Reddit exposes an undocumented JSON endpoint that returns post data without authentication.

Scraping either would have produced the data. It would also have made every statement I make in this section false, because I would then have had to say that I collected two sources in a way their operators explicitly ask people not to. The cost of not scraping is that six analyses could not run the way I first planned them: 3.1, 3.4, 4, 5.3, 5.4 and 7. I replaced each with an analysis on data I could get without a key, and I label every replacement as one wherever it appears. I record that cost in `open_questions.md` and in the README rather than hiding it behind a gap in the analysis.

This is the clearest ethical decision I made in this project, and it was a real trade off rather than a costless one.

## 2. Privacy of fan data

Public posts were not written for research. Somebody arguing about a film in 2019 did not consent to being a row in a Canadian retailer's demand model, and the fact that a post is publicly readable is not the same as it being fair game.

I built the controls below into the collection script, `src/collect/08_reddit.py`, rather than applying them afterwards. That ordering is the point: a privacy rule applied after collection has already been broken once, because the raw file on disk already contains the thing the rule was meant to prevent.

- **Usernames never reach disk.** I replace each author at the moment of collection with a salted SHA-256 hash truncated to 16 characters. The salt lives in `.env`, which is ignored by git, so nobody reading this repository can reverse the hashes. The hash exists only so that posts by the same person can be grouped into segmentation features; I never report it.
- **Salted, not plain.** A plain SHA-256 of a username is reversible in seconds with a dictionary of known usernames. It would be personal data wearing a disguise.
- **Fields are selected, not dumped.** `post_record` lists the fields it keeps. Anything not on that list cannot reach the corpus, which is a stronger guarantee than deleting fields afterwards.
- **Account age, not account identity.** Age band is a useful segmentation feature; the account it belongs to is not. I store only the age in days at the time of posting.
- **The cleaning step refuses to proceed on a violation.** `src/clean/16_clean_reddit.py` raises and stops if a raw file contains an `author` field rather than an `author_hash`. I log and work around every other data problem in this project; this one is a hard stop, because personal data on disk cannot be fixed by writing a note about it.
- **No individual is quoted.** Nowhere in this repository, in any figure, table or document, do I reproduce any individual user's post.
- **Aggregation floor.** I set `ethics.min_aggregate_group_size` in `config.yaml` to 20; I would report no group smaller than that.

A test enforces the outcome rather than trusting the process: `test_no_personal_identifier_reaches_processed_tables` in `tests/test_processed.py` fails the build if any processed table gains a column named `author`, `username`, `email` or similar.

**To be honest about the current state:** I collected no fan text at all, so no personal data exists in this repository today. My controls above are real and tested, but they have not yet had to protect anything. If credentials are added later, they take effect before the first record is written.

## 3. Young audiences

The franchise reaches children, and a project that models its audience has to take that seriously rather than note it.

**The obligations.** In Canada, PIPEDA governs collection of personal information in the course of commercial activity, and the Office of the Privacy Commissioner has been explicit that consent from a child cannot be considered meaningful; consent must come from a parent or guardian. Quebec's Law 25 adds stricter consent and deindexing requirements. In the United States, COPPA applies to operators of services directed at children under 13 and to anyone with actual knowledge that they are collecting data from a child under 13, and requires verifiable parental consent before doing so.

**How I avoid the problem.** I collect no data about identifiable individuals of any age, which is the only reliable way to avoid collecting data about identifiable children.

- Reddit requires users to be 13 or older, so users under 13 are already out of scope in principle. That is not a sufficient control on its own, because age gating by self declaration is not verification.
- The sufficient control is that I collect, infer at the individual level, and store no age at all. My first plan for module 4 would have used account age, posting behaviour and platform mix as *proxies for an age band at cluster level*, never as an attribute of a person. Without fan text I replaced it with product groups built from construction sets, so the current build holds no data about people at all.
- I store no username, email, location, or any other identifier, so no record in this project can be linked back to a person, of any age.
- I collect no data from any platform aimed at children.
**The proxy limitation, stated plainly.** Account age is not age. A fourteen year old with a six year old account does not exist, but a forty year old with a six month old account is common. Had I run that plan, any age band conclusion would have been a statement about cohorts of accounts, not about people.

## 4. Security

**Credentials.** No key, secret or token appears anywhere in this repository. The only credential file I track is `.env.example`, which lists key *names* with empty values so a reader knows what to obtain. Real values go in `.env`, which is the first entry in `.gitignore`.

**How the code reads them.** I read secrets only through `secret()` in `src/utils/config.py`, which returns `None` rather than raising when a key is absent. I chose that design so a collection script can log the missing key by name, write an entry to the issues register, and skip its source cleanly instead of crashing a four hour build. Both `07_brickset.py` and `08_reddit.py` took exactly that path in this build.

**What `.gitignore` prevents.** `.env` and any `.env.*` variant, `*.key`, `*.pem`, `credentials.json`, and `praw.ini`, which is the file `praw` will write credentials into if allowed to. It also excludes `data/raw`, `data/cleaned` and `data/processed`, so no collected fan text could be committed even by accident; I ship the code that rebuilds the data, not the data.

**Verification.** I scanned the repository history for credential patterns as part of my checks for module 8. `.env` has never existed in this repository, because I never obtained any credentials.

**Residual risk.** The `REDDIT_HASH_SALT` is the weakest point in my design: if it were ever committed, every username hash in the corpus would become reversible in bulk. It is ignored by git, but the stronger protection is that I truncate hashes to 16 characters and never publish them, so an attacker would need both the salt and access to files I do not distribute.

## 5. Brand and reputational risk

Public controversy attached to the franchise is a real commercial variable. A retailer committing several million dollars to a category needs to know the size of that risk. It does not need, and I do not offer, an opinion about the underlying dispute.

**What I can say.** Attention to the franchise is measurable and I measured it. My composite attention series shows a declining trend across the pageview window, and the new series' own article rose roughly a hundredfold from its 2024 level through 2025 casting and production news. Both are in `docs/findings.md`.

**What I cannot say, and why.** I planned to measure sentiment and its effect on demand. I could not measure sentiment, because I did not collect the fan text corpus, for the credentials reason in section 1. There is therefore **no sentiment evidence in this project at all**, and the honest position is to say so rather than to substitute impressions for data.

Specifically, I make no claim about:

- whether controversy has moved fan sentiment in either direction;
- whether any such movement has affected purchasing;
- how large a risk this represents to the recommended buy.
**How this affects the recommendation.** The buy I recommend in module 6 carries an unquantified downside risk from this source. That is a genuine weakness of the recommendation and I state it in the README and in the methods note rather than leaving it implicit. A buyer reading this work should treat my recommended quantity as conditional on brand risk being no worse than it is today, and should commission sentiment measurement before committing the full amount.

**My position.** I take no view on the controversy itself. That is not evasion; it is the correct scope. A retailer needs the size of the risk, and I was unable to measure it.

## 6. Machine generated content

A growing share of online fan text is written by language models. This matters for a sentiment measure specifically: a generated review reflects no human opinion, so including it does not add a weak signal, it adds a confident sounding non signal that biases the average toward whatever register the model writes in.

**Detection attempted.** None, because I collected no corpus. Had I collected one, my plan was perplexity based screening as a first pass, plus behavioural flags at the account level (posting cadence, account age at first post, near duplicate text across accounts).

**The limits of that plan, stated in advance so I do not oversell it.** Perplexity screening has a poor false positive rate on non native English writers and on formulaic genres, both of which are well represented in fan discussion. Published detectors do not generalise reliably across model families, and they degrade as models improve. Any figure I produced for "share of corpus likely machine written" would carry an error bar wide enough to make it close to useless as a filter, though still useful as a caution.

**Effect on confidence.** Because I performed no sentiment analysis, no result in this project is currently contaminated by generated text. If the corpus is collected later, every sentiment figure derived from it should be reported with an explicit statement that some unknown share of the input was not written by a person, and the trend over time should be treated with more suspicion in recent years than in older ones, since the contamination is growing.

## 7. Bias in the analysis

I name each bias below with the specific conclusion of mine it threatens, rather than listing it as a general caution.

**English language sources only.** Every Wikipedia article I collected is from `en.wikipedia`, and every search term is English. The franchise is global and Universal Studios Japan is one of the four parks in my attendance table. *Threatens:* the attention series underpinning my entire forecast, and therefore the size of my recommended buy. I am using English attention as a proxy for Canadian demand, which is defensible for a mostly English speaking market but systematically underweights Quebec. For a Canadian retailer with Quebec stores, this is a material gap.

**Wikipedia measures curiosity, not purchase intent.** A pageview is someone looking something up, which may be a fan, a journalist, a student or someone who just watched a trailer. *Threatens:* my pass through assumption in module 6. This is already my largest acknowledged weakness, since module 5.2 could not measure the attention to sales relationship at all.

**Search interest covers only people who search.** Google Trends misses everyone who navigates directly, uses an app, or is served the franchise by a recommendation engine, and the last of those is how a streaming premiere will actually reach most of its audience. *Threatens:* any use I make of the Trends series as a demand proxy. Mitigated by my using Wikipedia pageviews as the primary series and Trends as the secondary one.

**A national category standing in for a specific product line.** NAICS 459A covers every sporting goods, hobby, book and news retailer in Canada. *Threatens:* my elasticity in module 5.2, which I measured on it and which came back indistinguishable from zero. The correct reading is that the instrument is too coarse, not that no effect exists, and my finding says so.

**Survivorship in the film table.** Eleven films that were made and released. Cancelled projects and the counterfactual of a franchise that had not been extended are absent. *Threatens:* any inference from film performance to future performance. Mitigated by a rule I set at the start and keep throughout, that the eleven rows are descriptive only and I fit no predictive model to them.

**Audience scores gathered decades after release.** A Rotten Tomatoes audience score read in 2026 for a 2001 film reflects who chose to rate it over twenty five years, not its audience at release. *Threatens:* the critic versus audience gap on my dashboard's Reception page, which is not a like for like comparison and which I label on the page itself.

**Pandemic exclusion is a judgement.** I drop March 2020 to June 2021 from the elasticity work, and the whole of 2020 and 2021 from the seasonality work. *Threatens:* nothing badly, but it is my choice rather than a neutral act, and a different analyst could reasonably keep those months and model the disruption instead. The exclusion is in the code, in the config and in every affected finding.

**Absent sources bias what I can conclude.** The analyses I had to replace because of missing credentials are precisely the ones that would have described the *audience* rather than the *attention*. So I say a great deal about how much interest exists and very little about who holds it, which is a shape imposed by data availability, not by the business question.

## My checks

I set three checks for this part:

1. **All seven topics covered with specific reference to this project.** Sections 1 to 7 above; each cites the script, config key or table it describes.
1. **No username, email address or direct quotation from an individual user anywhere in the repository.** True, and enforced by `test_no_personal_identifier_reaches_processed_tables`. Currently trivially true, since I collected no fan text.
1. **A scan of the repository history finds no credentials.** I ran these rather than asserting them. Three checks, all returning nothing on 2 September 2026:

```
git log --all --diff-filter=A --name-only --pretty=format: | grep -E "(^|/)\.env$|\.pem$|\.key$|credentials\.json|praw\.ini"
git grep -nIE "(api[_-]?key|client[_-]?secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_-]{16,}" $(git rev-list --all)
git grep -nIE "['\"][A-Za-z0-9+/]{32,}['\"]" -- '*.py' '*.yaml' '*.md'
```

The first confirms no `.env`, key, certificate or `praw.ini` was ever added in any commit. The second looks for assignment of a long value to a credential shaped name across every commit reachable from any ref. The third looks for long opaque literals in tracked source, config and documentation. All three return nothing, which is unsurprising given that I never obtained a credential, but a check I actually ran is worth more than a claim I did not.
