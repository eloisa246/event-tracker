# 📥 Inbox — drop zone

This is where **you** drop raw material. Nothing here is expected to be clean,
consistent, or formatted a particular way. Drop it as-is; the pipeline's job is
to normalize it, not yours.

Anything in this folder is treated as **source input** — it gets parsed into
`config/sources.yaml`, never edited in place by automation. Your originals stay
untouched so we can always re-derive from them.

---

## What goes where

### `inbox/orgs/` — the org spreadsheet

Drop the spreadsheet here in whatever format you have it:

- `orgs.xlsx`, `orgs.csv`, `orgs.tsv`, Numbers export — all fine
- Multiple files / multiple tabs — fine
- Don't rename columns, don't reorder, don't delete the messy ones

**Useful columns if you happen to have them** (missing ones are fine — we
enrich later):

| Column | Why it matters |
|---|---|
| Org / venue name | Display name + dedupe key |
| Website URL | Entry point for feed discovery (the single most valuable field) |
| Instagram handle | Lead for finding the real ticketing link (see below) |
| Neighborhood | Filtering + map view |
| Category / vibe | Feed segmentation (music, art, books, community, food…) |
| Address | Geocoding, map view, dedupe |
| Notes | Anything that tells us where their events actually get posted |

> **Instagram handles are not a dead end.** The plan uses them as *leads*: bio
> link → Linktree/Beacons → the real Eventbrite / Dice / lu.ma / Withfriends
> page, which usually *is* machine-readable. A surprising share of
> "Instagram-only" venues resolve to a real feed this way. See `PLAN.md` →
> Tier 1.5.

### `inbox/guides/` — the Apple Maps guide

Apple Maps guides don't export cleanly, so: **paste the text** into
`inbox/guides/apple-maps-guide.md`. A template with an example is already there.

Formatting genuinely does not matter. One name per line, names with addresses
glued on, copy-paste artifacts, duplicated entries, emoji — all handled. If you
have more than one guide, add more files (`apple-maps-guide-bars.md`,
`apple-maps-guide-north-bk.md`, whatever).

### `inbox/notes/` — everything else

Loose lists, screenshots of a venue's calendar page, a Signal message with five
venue names in it, an email from an org with their iCal link, URLs you want
checked. Drop it here and mention it.

---

## Ground rules

1. **Don't pre-clean anything.** Duplicates across the spreadsheet, the guide,
   and your notes are expected and get merged automatically. Removing them by
   hand just costs you time and loses signal about which orgs you care most
   about.
2. **This repo is on GitHub.** Keep anything private out of the inbox — personal
   phone numbers, private email threads, anything an org shared in confidence.
   Public business info is fine.
3. **Add, don't replace.** New version of the spreadsheet? Drop it alongside as
   `orgs-2026-08.xlsx` rather than overwriting. Git keeps the history either way,
   but dated files make it obvious which snapshot a run used.

---

## What happens after you drop something

1. Everything in `inbox/` is parsed into a single deduplicated org list.
2. Each org with a URL goes through **automated feed discovery** — a crawl that
   checks for iCal feeds, RSS, known platform APIs (The Events Calendar,
   Squarespace, Eventbrite, lu.ma, Dice, Bandsintown…), and embedded JSON-LD.
3. You get back a **triage report**: every org, the ingestion tier it landed in,
   and how much work it'll be. Roughly, expect most of the list to land in the
   free/robust tiers and a stubborn tail to need bespoke handling.
4. That report drives what actually gets built first, so the discovery pass runs
   before any scraper code is written.

Details of all of the above: [`../PLAN.md`](../PLAN.md).
