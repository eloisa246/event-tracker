# Compliance posture

Why this project is built the way it is, and where the real risk sits.

There are **two** separate rulebooks in play, and they are not equally
dangerous. GitHub's terms govern the runner and the hosting. The venues' terms
govern the scraping. Most of the attention below goes to GitHub because that is
what was asked about — but the venue side is where the actual legal exposure
lives, and §3 should not be skimmed.

---

## 1. GitHub's terms

### 1.1 Actions — the clause that matters

GitHub's [Terms for Additional Products and
Features](https://github.com/github/docs/blob/main/content/site-policy/github-terms/github-terms-for-additional-products-and-features.md)
prohibit, on GitHub-hosted runners:

> "any other activity unrelated to the production, testing, deployment, or
> publication of the software project"

and separately prohibit activity that places a burden on GitHub's servers
disproportionate to the benefit it provides. Cryptomining is called out by name.

**Where this repo sits.** The pattern here — a scraper in a repo, run on cron,
committing its output back — is commonly called "git scraping" and is
widespread. The defensible reading is that this repo *is* the software project:
`scripts/build_calendar.py` is the software, `public/*.ics` is its published
output, and the scheduled run is that publication step. That is a real
argument, not a fig leaf.

It is, however, **an argument and not a guarantee.** The clause is written
broadly enough that a pipeline whose repo is a thin wrapper around "use
GitHub's free compute on a timer" reads badly. What keeps this one on the right
side is that it stays visibly modest, so the specific choices in
[`.github/workflows/build-calendar.yml`](../.github/workflows/build-calendar.yml)
are load-bearing:

| Choice | Why |
|---|---|
| `cron: "17 */6 * * *"` — 4 runs/day | Modest cadence. The calendar does not get meaningfully better at 15-minute polling, and frequency is the most visible abuse signal. |
| `timeout-minutes: 30` | A hung browser render is the realistic way this burns hours of runner time for nothing. |
| `concurrency: build-calendar` | Two builds never scrape the same venues simultaneously. |
| `permissions: contents: write` | Least privilege — the token can write this repo and nothing else. |
| Commit only when the diff is non-empty | No churn commits on a quiet window. |

**If you want more margin,** drop to daily (`17 5 * * *`). Nothing about this
calendar needs six-hour freshness; most venues announce days or weeks ahead.
That single change removes most of the argument surface.

Two operational notes:

- The repo is **public**, so Actions minutes are free and unmetered. None of
  this is consuming a paid quota.
- GitHub **disables scheduled workflows after 60 days of repository
  inactivity**. A repo whose only commits come from the bot can trip this. If
  the calendar quietly stops updating, check this first — it is far more likely
  than a ToS action.

### 1.2 Serving the calendar

Right now the `.ics` files are committed to the repo, and the obvious way to
subscribe is a `raw.githubusercontent.com` URL. **Don't build on that.** Raw
URLs are not a content-delivery endpoint, they are uncached, and using them as
a subscription target for a calendar that every client re-polls on its own
schedule is exactly the "disproportionate burden" shape.

**GitHub Pages is the correct surface** and is already the plan (PLAN.md §5).
Pages is intended for this, has a documented ~100 GB/month soft bandwidth
limit, and is fine for a community calendar. Pages may not be used as free
hosting for commercial or SaaS operations — a free neighbourhood events feed is
not that.

### 1.3 The item that is actually highest-risk

**None of the above is the biggest ToS exposure in this project.**

`pack-it-up/RESTORE.md` records that a previous GitHub account,
`9dpzmbpyym-crypto`, was **suspended**, and that the original version of this
work lived there. This repo is on a different account, `eloisa246`, created
2026-08-09.

GitHub's Terms of Service state:

> "One person or legal entity may maintain no more than one free Account"

and reserve the right to "suspend or terminate your access to all or any part
of the Website at any time, with or without cause, with or without notice."

If both accounts are yours and the first is still suspended, then rebuilding
here carries a risk that no amount of workflow hygiene addresses — because the
exposure is at the account layer, not the code layer. A perfectly compliant
scraper on an account that is itself a problem still ends with a lost repo, and
the loss looks exactly like the last one.

**The recommended move is to resolve the account question before investing more
here**, via <https://support.github.com/contact>. Suspension is not deletion:
if the original account is reinstated you also get the 62-commit history back
that `RESTORE.md` is currently trying to work around. If the suspension was an
automated false positive — the `9dpzmbpyym-crypto` name has the shape of an
auto-generated throwaway, and those get caught in anti-spam sweeps regularly —
appeals succeed routinely.

If the two accounts are unrelated, or the first was already resolved, disregard
this section. It is flagged because the cost of being wrong about it is losing
this repo the same way the last one went.

---

## 2. What is deliberately not done

- **No cryptomining.** Named explicitly in the Actions terms.
- **No Instagram scraping.** Ruled out in PLAN.md §2 — against their ToS,
  needs an authenticated session, and risks the account.
- **No use of Actions as general-purpose compute.** The workflow runs this
  repo's pipeline and nothing else.
- **No multi-account parallelism** to dodge quotas.

---

## 3. The venues' terms — the larger legal surface

GitHub can close an account. A venue or ticketing platform can send a lawyer.
The second is rarer but worse, and this is where the genuine exposure is.

What the pipeline does to stay defensible:

- **`robots.txt` is fetched and honoured** for every HTTP request and every
  browser render, via the single chokepoint in `polite_get()` /
  `render_page()`. A disallowed source is skipped and reported in
  `docs/health.md` rather than fetched anyway. *(All 14 configured sources
  currently pass.)*
- **The crawler identifies itself** — the User-Agent names the project and
  links to this repo, so a venue admin who looks it up finds a real page and a
  way to reach you. It previously pointed at
  `9dpzmbpyym-crypto/Event-Calender`, a dead URL on the suspended account,
  which is worse than no contact address at all.
- **Rate limited** — 1.5s between requests to the same host, 6 workers across
  distinct hosts.
- **No automation-detection evasion.** The Chromium launch used to pass
  `--disable-blink-features=AutomationControlled`, whose only purpose is to
  stop a site detecting that the browser is a bot. It is removed. Evading a
  control a site deliberately put up is the single fact most likely to turn "we
  aggregated public listings" into something harder to defend.
- **Attribution, always** — every event keeps `url` pointing at the original
  listing. Descriptions are truncated, not republished wholesale.

### Known limitation

Python's `urllib.robotparser` matches rules **in file order** and does not
implement RFC 9309 longest-match precedence. For a `robots.txt` written as:

```
User-agent: *
Disallow: /
Allow: /events
```

it returns *disallowed* for `/events`, where a spec-compliant parser returns
allowed. This errs toward **not fetching**, which is the safe direction — but
it can silently drop a source you are in fact permitted to crawl. If a source
starts reporting `RobotsDisallowed` and its `robots.txt` has that shape, that
is the cause, and the fix is a real parser (`protego`, which is what Scrapy
uses), not an exemption.

### If a venue asks you to stop

Honour it immediately and without argument — remove them from
`config/sources.yaml` and reply. One removed venue costs almost nothing. One
argued-with venue is how an aggregator gets a reputation that closes doors at
all the others.

---

## 4. Review triggers

Re-read this document when any of these change:

- The cron gets faster, or the source count grows substantially (34 orgs are
  triaged; 243 exist — at that scale the burden question is a real one).
- Playwright rendering expands to many more sources; browser renders are by far
  the heaviest thing here.
- The project starts charging, taking sponsorship, or otherwise becoming
  commercial — that changes the Pages analysis in §1.2.
- Anything is added that authenticates to a platform, or that reads a source
  behind a login.
