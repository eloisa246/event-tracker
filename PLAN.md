# Brooklyn Event Calendar — Build Plan

Aggregate the event calendars of a few dozen Brooklyn organizations and venues
into one calendar people can subscribe to, browse, and share.

**Status:** Phases 0–3 are substantially built and running. 14 sources produce
336 events into [`public/calendar.ics`](public/calendar.ics), rebuilt by
[`scripts/run.sh`](scripts/run.sh) from cron.

> ⚠️ **§6 below is superseded.** It recommends GitHub Actions as the runner.
> That is exactly the usage GitHub restricted the previous account for, in
> writing. The pipeline runs off-GitHub now — see
> [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md), which is the authority on this.

---

## 1. The actual problem

Aggregating a few dozen event calendars is not one problem, it's three:

1. **Extraction** — every org publishes differently. Some have clean iCal feeds.
   Some run WordPress plugins with REST APIs. Some are a hand-updated HTML table.
   Some post only to Instagram stories.
2. **Normalization** — turning wildly different records into one schema with
   correct timezones, stable identities, and no duplicates (the same show listed
   on the venue site *and* Eventbrite *and* Dice).
3. **Not rotting** — a few dozen scrapers is a few dozen things that break
   silently when a site gets redesigned. **This is the part that kills projects
   like this**, and most of the design below is in service of it.

The guiding principle: **push every source as far up the reliability ladder as
possible, and never write a bespoke scraper when a feed exists.** Bespoke
scrapers are a maintenance liability, so each one should be a deliberate,
last-resort decision — not the default move.

---

## 2. Ingestion tiers

Every org gets classified into the highest (cheapest, most durable) tier it
supports. Discovery is automated; the tier assignment is the output of Phase 0.

### Tier 0 — Native calendar feeds ✅ *ideal*
Zero parsing risk, survives redesigns, updates instantly.

- **iCal / .ics** — `/events.ics`, `?ical=1`, `<link rel="alternate">` with
  `text/calendar`, "Subscribe" / "Add to calendar" links.
- **Google Calendar embeds** — an embedded calendar exposes its calendar ID in
  the iframe `src`; that maps directly to a public ICS URL. Extremely common for
  nonprofits, libraries, community orgs, mutual aid groups.
- **RSS/Atom event feeds** — dated items, parseable.

> **No outreach** (decided — see §10). Orgs are not emailed for their feed
> links, so Tier 0 membership is whatever automated discovery can find on its
> own. Discovery therefore probes hard for undocumented feeds: many sites serve
> a working `.ics` at a conventional path without ever linking to it, and those
> are worth finding since they're free and permanent.

### Tier 1 — Platform APIs 🟢 *one adapter, many venues*
Each adapter is written once and reused across every org on that platform. This
is where the leverage is.

| Platform | Access route | Common for |
|---|---|---|
| **The Events Calendar** (WordPress plugin) | REST at `/wp-json/tribe/events/v1/events` + ICS export | Nonprofits, galleries, community orgs — likely the single biggest cluster |
| **WordPress core** | `/wp-json/wp/v2/<post-type>` | Custom event post types |
| **Eventbrite** | Public organizer page: schema.org JSON-LD per event + the page's own pagination JSON | Ticketed events, workshops, fundraisers |
| **lu.ma** | Per-calendar iCal subscribe link | Newer/tech-adjacent orgs, reading series |
| **Squarespace** | Events collection JSON + per-page ICS | Small venues, galleries, restaurants |
| **Dice.fm** | Venue/promoter endpoints + JSON-LD | Music venues |
| **Bandsintown / Songkick** | Venue calendar APIs | Music venues |
| **Resident Advisor** | GraphQL | Club / DJ nights |
| **Ticketmaster Discovery** | Free API key, filter by venue | Large venues (Barclays, Kings Theatre tier) |
| **Meetup** | JSON-LD on public pages | Community groups, clubs |
| **Withfriends / Prekindle / Tixr / See Tickets / Shotgun** | JSON-LD, varies | Indie venues |
| **Wix Events** | Site JSON API | Small businesses |

⚠️ These exact endpoints are **hypotheses to verify in Phase 0**, not
guarantees — platforms change and several have tightened access over the years.
Discovery probes each one and reports what actually responds. Treat the table as
a checklist to test, not a spec.

### Tier 1.5 — Instagram-handle → real-feed resolution 🟡 *the unlock*
An Instagram handle looks like a dead end but usually isn't. The pipeline:

```
@venue → IG bio link → Linktree/Beacons/Later.link → Eventbrite | Dice | lu.ma
       → which IS machine-readable → promote org to Tier 0/1
```

Run this on every IG-only org before writing them off. Expect a meaningful
fraction to resolve to a real feed. What doesn't resolve drops to Tier 4.

Scraping IG posts/stories directly is **explicitly out of scope**: it's against
their ToS, requires authenticated sessions, breaks constantly, and risks the
account. Not worth it.

### Tier 2 — Structured data embedded in HTML 🟢 *generic, high coverage*
One generic extractor covering many sites, no per-site code.

- **schema.org JSON-LD** (`@type: Event`) — the single highest-leverage generic
  scraper. Ticketing platforms and modern CMSes emit it almost universally.
- **Microdata / RDFa** — older sites.
- **OpenGraph** — weak fallback, usually only gets one event.

### Tier 3 — Declarative per-site scrapers 🟠 *maintenance cost begins*
For sites with real HTML calendars and no structured data. Critically, these are
**config, not code** — adding a venue is a YAML edit:

```yaml
- id: example-venue
  strategy: css
  url: https://example.com/events
  selectors:
    item:  ".event-listing"
    title: "h3.event-title"
    date:  ".event-date@datetime"
    url:   "a.event-link@href"
```

Keeping these declarative means the long tail doesn't multiply the codebase, and
a broken venue is a one-line fix.

### Tier 4 — Headless browser + LLM extraction 🔴 *fallback only*
For JS-rendered calendars and sites too irregular for selectors.

- **Playwright** renders the page (already installed in this environment).
- Cleaned text goes to **Claude with a strict JSON schema** for extraction.
- **Cost control:** hash the rendered content; only call the model when the hash
  changes. A venue posting weekly costs a handful of calls a month.
- **Bonus use:** run it once against a Tier 3 candidate to *propose CSS
  selectors*, then hand-verify and freeze them into YAML. Model does the tedious
  part; the durable artifact is cheap deterministic config.

### Tier 5 — Human in the loop ⚪ *the honest floor*
Some orgs will never be machine-readable. Rather than pretend otherwise:

- `inbox/manual-events.md` or a linked Google Sheet for hand-entered events.
- A **quarantine queue**: parses that fail or look wrong surface for review
  instead of silently emitting garbage or vanishing.

---

## 3. Data model

```
Event
  uid            stable, deterministic — sha1(source_id + external_id|url + start) 
  source_id      which org/adapter produced it
  org            display name, slug
  title
  description    plain text, truncated, with link back to source
  start / end    UTC + original tz (America/New_York) + all_day flag
  location       venue name, street address, lat/lng, neighborhood
  url            canonical link to the event (always preserved — attribution)
  ticket_url     if separate from url
  price          free flag, min/max, currency
  categories     music | art | books | community | food | film | …
  image
  status         scheduled | cancelled | postponed
  first_seen / last_seen
  raw_hash       for change detection
  confidence     extraction confidence (Tier 4 events flagged lower)
```

**Stable UIDs matter more than they look.** Regenerating UIDs per-run means every
subscriber's calendar app deletes and re-adds every event on every sync —
notification spam, and nothing shows as *updated* vs *new*. Deterministic UIDs +
an incrementing `SEQUENCE` make edits propagate cleanly.

**Timezones:** store UTC, always carry `America/New_York`, emit ICS with an
explicit `TZID`. Naive local datetimes are the #1 source of off-by-hours bugs,
and DST transitions in March/November are where they surface.

**Recurring events:** pass `RRULE` through when the source is iCal; otherwise
expand to individual instances within a bounded window (~180 days) to avoid
unbounded generation.

**Deduplication** — the same show appears on the venue site, Eventbrite, and
Dice. Match on: fuzzy-normalized title + start within ±30 min + same venue.
Merge into one event, prefer the richest record, keep all source links. Below a
confidence threshold, keep both and flag for review — showing a duplicate is a
smaller failure than silently dropping a real event.

---

## 4. Pipeline

```
inbox/ ──► parse ──► org list ──► feed discovery ──► config/sources.yaml
                                                            │
                    ┌───────────────────────────────────────┘
                    ▼
        fetch (ETag / If-Modified-Since, rate-limited, cached)
                    ▼
        parse (tier-appropriate adapter)
                    ▼
        normalize → dedupe → upsert into store
                    ▼
        emit: calendar.ics · per-category ICS · events.json · static site
                    ▼
        health check → status page → alert on anomalies
```

**Lifecycle / tombstones:** events that disappear from a source get marked
cancelled rather than silently deleted, so subscribers see `STATUS:CANCELLED`
instead of an event quietly vanishing from their calendar.

**Politeness:** per-host delays, `robots.txt` honored on every request and
render, and a descriptive User-Agent pointing at this repo. We are a good
citizen aggregating public listings and linking back — that posture is both
correct and what keeps access open. Details and the reasoning:
[`docs/COMPLIANCE.md`](docs/COMPLIANCE.md).

> **Not yet implemented:** conditional requests (`ETag` / `If-Modified-Since`).
> Every run currently re-fetches every source in full. This is the largest
> remaining politeness win — it would cut most of the bytes we pull from
> venues, since the majority of pages are unchanged between six-hourly runs.
> It needs a small persisted cache of per-URL validators.

---

## 5. Outputs

1. **`calendar.ics`** — ⭐ canonical output, the main subscribable feed (`webcal://`), works in Apple
   Calendar, Google Calendar, Outlook, Fantastical.
2. **Filtered feeds** — per-category and per-org ICS, so someone can subscribe to
   just music, or just three venues.
3. **`events.json`** — plain API for anything downstream.
4. **Static site** (GitHub Pages) — month/list view, filters by neighborhood and
   category, search, "add to calendar" buttons, per-org toggles.
5. **Google Calendar mirror** (Phase 5, secondary surface — ICS stays canonical) — pushed via API. Worth it because Google
   refreshes *external* ICS subscriptions slowly and unpredictably (can be many
   hours to over a day); a directly-written Google Calendar updates immediately
   and gets the familiar share/embed UI.
6. **Optional weekly digest** — email or markdown, "this week in Brooklyn."

---

## 6. Infrastructure

> ⚠️ **Superseded.** This section originally recommended GitHub Actions as the
> cron runner. GitHub restricted the previous account for precisely that —
> "repositories that use GitHub Actions solely to interact with 3rd party
> websites" — and declined the appeal. Do not put this pipeline back on
> Actions. [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md) §1 has the notice and the
> reasoning.

**Recommendation: cron off-GitHub + static output committed back.**

- Daily → [`scripts/run.sh`](scripts/run.sh) → commit `data/events.json` +
  `public/*.ics` → GitHub Pages serves it.
- Runs on your own machine (`cron`/`launchd`, free) or a ~$5 VPS if it needs to
  run unattended.
- The git history is still the audit log: every run's diff shows exactly which
  events appeared, changed, or vanished. When a scraper breaks, the diff shows
  it as "-14 events" rather than silence.
- GitHub keeps doing the parts it is meant for — hosting the code and serving
  the output via Pages.

**Stack: Python.** Best-in-class ecosystem for exactly this work — `httpx`,
`selectolax`/`BeautifulSoup`, `extruct` (JSON-LD/microdata), `dateparser`,
`icalendar`, `playwright`, `rapidfuzz`. TypeScript is viable but the date and
structured-data parsing story is meaningfully weaker.

---

## 7. Monitoring — the part that decides if this survives

A few dozen scrapers will break. The system must notice **without you checking**.

- **Per-source health record:** last success, last event count, error, tier.
- **Anomaly detection:** a source that historically returns ~12 events and now
  returns 0 is a redesign, not a quiet week. Alert on it. This catches the
  silent-failure mode that otherwise takes months to notice.
- **Staleness:** no successful fetch in N days → alert.
- **Public status page** listing every org, its tier, last update, health.
- **Quarantine queue** for suspicious parses (dates in the past, year 1970,
  titles that look like nav elements).

Budget roughly a **couple of hours a month** of maintenance once steady — mostly
re-pinning selectors after redesigns. Declarative Tier 3 config is what keeps
that number small.

---

## 8. Phases

| Phase | Work | Depends on |
|---|---|---|
| **0. Discovery** | Parse `inbox/` → org list. Automated feed probe on every URL. IG bio-link resolution. **Output: triage report — every org, its tier, its effort.** | Your spreadsheet + guide |
| **1. Core** | Data model, store, normalize/dedupe, ICS emitter, off-GitHub cron. 5 pilot orgs spanning different tiers, end to end. | Phase 0 |
| **2. Feeds & platforms** | Tier 0 + Tier 1 adapters (Tribe, Eventbrite, lu.ma, Google Cal, Squarespace, Dice/Bandsintown). | Phase 1 |
| **3. Long tail** | Generic JSON-LD extractor. Declarative CSS scrapers for the remainder. **Anomaly alerting** — pulled forward from Phase 6, since no-outreach means monitoring is the only breakage signal. | Phase 2 |
| **4. Hard cases** | Playwright + LLM fallback. Manual entry path. Quarantine queue. | Phase 3 |
| **5. Surfaces** | Static site, filtered feeds, Google Calendar mirror, subscribe/share UX. | Phase 1 |
| **6. Durability** | Health dashboard, maintenance runbook, quarantine review UX. | Phase 3 |

Phases 1–3 are the bulk of the value. Phase 4 is genuinely optional and should
only be built for orgs you actually care about — it's the highest-cost,
lowest-durability tier.

---

## 9. Legal / etiquette posture

Public event listings, aggregated with attribution and links back to the source
— the same thing every local events newsletter does, and orgs generally *want*
their events found. Concretely:

Full posture, including the GitHub-terms side and the account risk that matters
more than any of this: [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md).

- Respect `robots.txt`; rate-limit; identify the crawler with a contact address.
- Always link back to the original listing; never republish full descriptions
  verbatim at length.
- Honor any removal request immediately, no argument.
- Some ticketing platforms restrict automated collection in their ToS. Where
  that's a concern the mitigation is the same: prefer the org's own site or a
  feed they hand us, and keep the crawl courteous and low-volume.

---

## 10. Decisions made

**Scope: start with ~30, then grow.** The full inbox resolves to 243 unique
orgs — far past the "few dozen" this was scoped for. Rather than narrow the
list permanently, Phase 1 wires up a ~30-org starter set
(`data/shortlist.csv`, generated by `scripts/shortlist.py`) chosen for high
event volume and spread across categories, so the pilot exercises several
different source types. Adding the rest afterwards is mostly mechanical.
The list is NYC-wide, not Brooklyn-only — roughly 107 read as Brooklyn, 17 as
another borough, and 58 don't say. Worth renaming the project if the wider
scope sticks.

**Blocking gap: no websites.** All 182 spreadsheet orgs have an Instagram
handle; none has a website, which is the doorway to a machine-readable
calendar. Spot-checking four orgs by name search found the real site every
time, so this is an extra step rather than a dead end — but it has to happen
before feed discovery can run at all.


**Output surface: both, ICS first.** The subscribable `.ics` feed plus the
browsable site get built in Phase 1; the Google Calendar mirror follows in
Phase 5 as a second surface, not the source of truth. Keeping ICS canonical
means the Google mirror is disposable — if the API integration or the account
breaks, subscribers are unaffected.

**Outreach: none — scrape everything.** No emails to orgs asking for feed links.
Consequences, accepted deliberately:

- More sources land in Tiers 2–4 than would otherwise, so there's a permanently
  larger surface of scrapers to maintain.
- **Monitoring (§7) moves from important to load-bearing.** It's the only thing
  that will tell you a venue redesigned their site, so anomaly alerting ships in
  Phase 3 rather than being deferred to Phase 6.
- Discovery compensates by probing aggressively for *unadvertised* feeds —
  conventional `.ics` paths, plugin exports, embedded calendar IDs — since
  those are free Tier 0 wins that don't require asking anyone.
- Tier 3 staying strictly declarative matters more under this choice: a broken
  venue must stay a one-line YAML fix.

Everything else I'll pick sensible defaults for and flag as I go.

---

## Next step

Drop the spreadsheet in [`inbox/orgs/`](inbox/orgs/) and paste the Apple Maps
guide into [`inbox/guides/apple-maps-guide.md`](inbox/guides/apple-maps-guide.md).
Phase 0 runs against them and comes back with the triage report — which is what
tells us how much of this list is easy and how much is going to fight.
