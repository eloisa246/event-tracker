# Feed discovery triage

Generated 2026-08-08 05:47 UTC · 34 orgs probed

Tiers are defined in [PLAN.md](../PLAN.md). Lower is cheaper and more durable.

## Summary

| Tier | Orgs | What it means |
|---|---|---|
| `1-platform` | 18 | Known ticketing platform. One adapter covers many orgs. |
| `2-jsonld` | 1 | Structured data in the page. Generic extractor works. |
| `3-scrape` | 14 | Needs hand-written selectors. Maintenance cost. |
| `4-browser` | 1 | JS-rendered or unreachable. Browser + LLM fallback. |

## 1-platform

- **Abrons Arts Center** — eventbrite-linked
  - platforms seen: eventbrite
  - page links to eventbrite (no usable URL found)
- **Baby's All Right** — seetickets-linked
  - feed: `https://wl.seetickets.us/BabysAllRightBrooklyn`
  - platforms seen: squarespace, seetickets
  - page links to seetickets: https://wl.seetickets.us/BabysAllRightBrooklyn
- **Caffeine Underground** — ra-curated
  - feed: `https://ra.co/clubs/213671`
  - platforms seen: wordpress
  - verified ra listing from websites.csv
- **Cassette NYC** — dice-curated
  - feed: `https://dice.fm/venue/cassette-922xo`
  - platforms seen: dice, seetickets
  - verified dice listing from websites.csv
  - also on: ra
- **Elsewhere** — eventbrite-curated
  - feed: `https://www.eventbrite.com/o/elsewhere-105655500371`
  - platforms seen: eventbrite
  - verified eventbrite listing from websites.csv
  - also on: ra
- **Film Noir Cinema** — eventbrite-linked
  - feed: `https://www.eventbrite.com/e/clownspiracy-tickets-1990612090348?aff=oddtdtcreator`
  - platforms seen: squarespace, eventbrite
  - only per-event iCal found - not a calendar feed
  - page links to eventbrite: https://www.eventbrite.com/e/clownspiracy-tickets-1990612090348?aff=oddtdtcreator
- **Friends and Lovers** — eventbrite-curated
  - feed: `https://www.eventbrite.com/o/friends-and-lovers-10023790784`
  - platforms seen: squarespace, eventbrite
  - verified eventbrite listing from websites.csv
  - also on: ra
- **Grand Bazaar NYC** — eventbrite-curated
  - feed: `https://www.eventbrite.com/o/grand-bazaar-nyc-10860076088`
  - verified eventbrite listing from websites.csv
- **Greenlight Bookstore** — eventbrite-fallback
  - feed: `https://www.eventbrite.com/o/greenlight-bookstore-13064382976`
  - https://greenlightbookstore.com/events -> HTTP 403
  - https://greenlightbookstore.com/ -> HTTP 403
  - site declined our crawler; using its eventbrite listing instead
- **Hive Mind Books** — eventbrite-curated
  - feed: `https://www.eventbrite.com/o/hive-mind-books-79929425663`
  - platforms seen: eventbrite
  - verified eventbrite listing from websites.csv
- **Market Hotel** — ra-curated
  - feed: `https://ra.co/clubs/19281`
  - platforms seen: squarespace
  - verified ra listing from websites.csv
- **Nowadays** — ra-curated
  - feed: `https://ra.co/clubs/105873`
  - verified ra listing from websites.csv
- **Nuyorican Poets Cafe** — eventbrite-curated
  - feed: `https://www.eventbrite.com/o/nuyorican-poets-cafe-17401146295`
  - platforms seen: squarespace
  - verified eventbrite listing from websites.csv
- **Public Records** — dice-curated
  - feed: `https://dice.fm/venue/public-records-w2qg`
  - verified dice listing from websites.csv
  - also on: ra
- **Queer Book Club Bushwick** — eventbrite-linked
  - feed: `https://www.eventbrite.com/o/hive-mind-books-79929425663`
  - platforms seen: eventbrite
  - page links to eventbrite: https://www.eventbrite.com/o/hive-mind-books-79929425663
- **Ridgewood Commons** — withfriends-curated
  - feed: `https://withfriends.events/o/ridgewood-commons/`
  - platforms seen: withfriends
  - verified withfriends listing from websites.csv
- **Seventh Heaven Bar & Karaoke** — dice-curated
  - feed: `https://dice.fm/venue/seventh-heaven-bar--karaoke-dkkwg`
  - platforms seen: squarespace, dice
  - verified dice listing from websites.csv
  - also on: ra
- **Starr Bar** — ra-curated
  - feed: `https://ra.co/clubs/130246`
  - platforms seen: squarespace
  - verified ra listing from websites.csv

## 2-jsonld

- **The Tiny Cupboard** — schema.org-events
  - feed: `https://www.thetinycupboard.com/calendar`
  - 198 JSON-LD Events in page

## 3-scrape

- **Alamo Drafthouse NYC** — needs-selectors
  - feed: `https://drafthouse.com/theater/downtown-brooklyn`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **BACKSPACE** — needs-selectors
  - feed: `https://www.wearebackspace.com/`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **BOYFRIEND co-op** — needs-selectors
  - feed: `https://boyfriend.coop/`
  - https://boyfriend.coop/ -> ReadTimeout
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Bibliothèque NYC** — needs-selectors
  - feed: `https://www.bibliothequenyc.com`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Brooklyn Flea** — needs-selectors
  - feed: `https://www.brooklynflea.com/locations`
  - platforms seen: squarespace
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Brooklyn Pop-Up** — needs-selectors
  - feed: `https://www.brooklynpop-up.com/markets`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Café con Libros** — needs-selectors
  - feed: `https://www.cafeconlibrosbk.com/events`
  - platforms seen: wix, google-calendar
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Caveat** — needs-selectors
  - feed: `https://caveat.nyc/events`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Light Industry** — needs-selectors
  - feed: `https://www.lightindustry.org/calendar/`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Metrograph** — needs-selectors
  - feed: `https://metrograph.com/nyc/`
  - platforms seen: wordpress
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Queens Night Market** — needs-selectors
  - feed: `https://queensnightmarket.com/`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Quiet Reading** — needs-selectors
  - feed: `https://quietreading.org/`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **Scratch Ceramics Studio** — needs-selectors
  - feed: `https://www.scratchceramics.com/`
  - platforms seen: squarespace
  - no feed/platform/JSON-LD found; 0 JSON-LD Events
- **The Poetry Project** — needs-selectors
  - feed: `https://www.poetryproject.org/events`
  - no feed/platform/JSON-LD found; 0 JSON-LD Events

## 4-browser

- **100 Sutton** — unreachable-or-js-only
  - https://100sutton.com/upcoming-events/ -> HTTP 202
  - https://100sutton.com/ -> HTTP 202
  - ⚠️ no HTML retrieved
