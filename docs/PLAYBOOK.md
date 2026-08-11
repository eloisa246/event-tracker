# Adding a source: what actually works

Field notes from getting 13 sources live. Every recipe below has a confirmed
win behind it, and every gotcha cost real time at least once. Read the
decision tree and the failure-signature table first — between them they cover
most of what went wrong.

---

## 0. Before anything: are you pointed at the right page?

**More sources failed from a wrong URL than from a hard technical problem.**
Check these first, in this order:

1. **Use the org's own calendar, not their ticketing platform.** A venue often
   sells tickets on Eventbrite/Dice while publishing the full schedule on its
   own site. Elsewhere's Eventbrite listing had 6 events; `elsewhere.club/events`
   had the real programme. The platform is a side door, not the source.
2. **Use the listing page, not one event.** Pointing at
   `/events/some-single-event/` caps that source at exactly one event forever.
3. **Check what a phone sees.** Ridgewood Commons served a third-party booking
   widget (full of *other orgs'* events) to desktop, and its own FullCalendar
   with a plain `.ics` feed to mobile. `diagnose.py --mobile` exists for this.
4. **Strip tracking junk** from any URL out of an Instagram bio —
   `?utm_source=...&fbclid=...` — before putting it in config.

---

## 1. Decision tree

Work top to bottom. Stop at the first that produces events.

```
Does a real .ics feed exist?                    → strategy: ical          ★ best
  ↓ no
Is it Squarespace?                              → strategy: squarespace
  ↓ no
Does plain HTML carry schema.org Events?        → strategy: jsonld / dice
  ↓ no
Does it render in JS or block plain HTTP?       → strategy: browser
  ↓ nothing after three techniques
Park it, with the reason written down.
```

---

## 2. The recipes

### `ical` — a real calendar feed ★ always prefer this

Zero parsing risk, survives redesigns, ~5 lines of adapter.

**How to find one when it isn't advertised:**
- Read the calendar widget's own init code. Ridgewood Commons' page contained
  `events: { url: 'rc-calendar.ics?version=' + version, format: 'ics' }` —
  the whole answer, sitting in a `<script>` tag.
- `<link rel="alternate" type="text/calendar">` in `<head>`.
- Try `?ical=1` (The Events Calendar), `?format=ical` (Squarespace).

**Verify before trusting it:** the response must start with `BEGIN:VCALENDAR`
and contain **2+ `BEGIN:VEVENT`**. A single-VEVENT file is usually a
per-event "add to calendar" download, not the venue's calendar — Squarespace
attaches one to *every* event, and mistaking it for a feed produced three
bogus "working" sources early on.

> Confirmed: Ridgewood Commons — 35 events.

---

### `squarespace` — `?format=json` on the collection page

Squarespace serves any page as JSON. That's the platform's own public view of
a public page, and it carries structured start times the rendered HTML only
formats.

**The one thing that matters:** it only returns event items on the **events
collection page itself**. A homepage or an ordinary page returns site chrome:

```
/            → {website, websiteSettings, collection, shoppingCart}   ✗ no items
/events      → {items: [...]}                                         ✓
```

Five sources returned nothing purely because they were pointed at `/` or at a
regular page. The adapter now finds the collection itself: configured URL →
common paths → **the site's own `sitemap.xml`** (guessing paths produced five
404s per site and found nothing; the sitemap is the site telling you what
exists).

**Gotchas:**
- Timestamps are **epoch milliseconds**, not ISO strings.
- Index-page layouts nest events in `indexSections`, not a flat `items` key.
  Search recursively for the *shape*; don't assume a key path.
- A blog or product collection also has `items` — require at least one item
  with a `startDate` or you'll import blog posts as events.

> Confirmed: Friends and Lovers `/upcoming` 15 · Film Noir `/program` 14 ·
> Starr Bar `/events` 12.

---

### `jsonld` / `dice` — schema.org in plain HTML

One extractor, no browser, no per-site code. Check with:

```bash
curl -s <url> | grep -o 'application/ld+json' | head
```

then look for `"@type":"Event"`. Handles nested `@graph`, arrays, and falls
back to regex counting when the JSON is malformed.

**Dice is the standout platform here** — it serves full schema.org on plain
HTTP with no blocking, which makes any Dice venue effectively free.

> Confirmed: The Tiny Cupboard 141 · Public Records 29 · Cassette 26 ·
> Seventh Heaven 12.

---

### `browser` — render it, then watch what *it* fetches

For pages that build their listing in JavaScript or refuse plain HTTP. Four
techniques, tried in order:

1. **schema.org in the rendered DOM** — same trusted extractor, post-JS.
2. **The page's own JSON network traffic** ← *the workhorse.* A JS calendar is
   reading its data from somewhere; capturing the page's own requests finds
   that source with no endpoint guessing and no per-site selectors.
3. **An "Add to Calendar" widget.** AddEvent puts the real event in *child
   spans*, not data- attributes, which is why attribute searches miss it:
   ```html
   <div class="addeventatc">
     <span class="start    atc_node">04/23/2026 10:00 am</span>
     <span class="end      atc_node">04/23/2026 5:00 pm</span>
     <span class="location atc_node">Grand Bazaar NYC, 100 West 77th St...</span>
   ```
   Usually no title span — falls back to the page's `<h1>`. Common on
   WordPress event sites with no feed, no REST API and no schema.org, which
   is otherwise a dead end.
4. **Follow links to detail pages** — a listing may carry nothing while each
   event's own page carries full schema.org *or its own AddEvent widget*.
   Point config at the **listing**, never a single event page.

A fourth technique (pairing `<time datetime>` with the nearest heading) was
**removed**: it never produced a single event, and proximity-matching can
silently pair the wrong title to the wrong date — worse than finding nothing.

**Gotcha — split date/time fields.** VenuePilot (Market Hotel) returns
`"date": "2026-08-08"` and `"startTime": "23:00:00"` as *separate* fields.
Taking the first present key grabs the bare time, which parses to nothing.
Scan all candidates for a complete value first, then combine.

> Confirmed: Market Hotel 14 · Hive Mind 11 · Greenlight 9 (detail pages) ·
> Elsewhere 2.

---

### `google_calendar`, `tribe_events` — written, never exercised

Both are small and standard enough to keep for the expansion, but **neither
has produced an event here**. Treat a zero from them as "unverified adapter",
not "this org has no events". Verify against one known-good site before
trusting either at scale.

---

### Removed on purpose — don't rebuild these blind

| Platform | What happened |
|---|---|
| **Bandsintown** | REST API 403'd exactly like its HTML. Adapter deleted. A registered `app_id` *might* fix it — untested, so don't assume. |
| **Resident Advisor** | 403 to plain HTTP on all four venues tried. |
| **See Tickets / Eventim** | 403, then a genuine Cloudflare challenge. |
| **Withfriends** | Rendered fine, returned nothing extractable. |

Their strategy names were removed from the registry deliberately: an unknown
strategy now **fails loudly** with "no adapter" instead of quietly reporting
zero events. If you revisit one, `browser` is the untested next thing to try.

---

## 3. Failure signatures → what it actually means

The single highest-leverage table here. Look up the error before theorising.

| What you see | What it means | Do this |
|---|---|---|
| `403 Forbidden` on plain HTTP | Platform blocks non-browser clients | Switch to `browser` |
| Title `Just a moment...`, host `challenges.cloudflare.com` | **Genuine bot challenge** | **Stop. Park it.** Real access control — respect it |
| `ValueError: Content line could not be parsed … '<!'` | Got HTML, not ICS | Your feed URL guess was wrong |
| `404` on `/wp-json/tribe/events/...` | Site has no Events Calendar plugin | Check `/wp-json/` namespaces before assuming |
| `no events collection … /=[website,websiteSettings,collection]` | Pointed at a non-collection Squarespace page | Find the real collection via `sitemap.xml` |
| `0 json responses, 0 event links found`, page renders large | Server-rendered, or a widget | Check embedded `<script>` JSON, widget markup, try `--mobile` |
| `0 event links found` on an archive page | Listing has no per-event links | Diagnose an **individual event page** |
| Renders fine, returns 0, no other signal | Usually the **wrong page entirely** | Re-check section 0 |

---

## 4. Diagnosing a source that returns zero

Production adapters only keep what already looks like an event — right for the
build, useless for debugging. `diagnose.py` renders with **no filtering** and
dumps everything: every response, JSON bodies, iframes, calendar-ish class
names, embedded `<script>` JSON, and third-party widget markup.

```bash
# Run locally: python scripts/diagnose.py <args>
# (Needs real internet — agent sandboxes generally block venue sites. Do NOT
# run this from GitHub Actions; see docs/COMPLIANCE.md §1.)

<source-id> [<source-id> ...]      # configured sources
--mobile <source-id>               # emulate a phone (different widget!)
--url <address> [name]             # any URL, e.g. a /wp-json/ root
(blank)                            # every source currently at zero
```

Output lands in `data/diagnostics/<id>.json` and `docs/diagnostics.md`.

**This is the method that actually worked.** Bandsintown's API, Squarespace's
`?format=json`, VenuePilot's GraphQL and Ridgewood's `.ics` were all found by
*looking at a real response* — never by guessing another endpoint shape.

---

## 5. Gotchas that cost real time

1. **A ticketing platform is not the org's calendar.** (§0)
2. **Desktop and mobile can serve entirely different widgets** — not just a
   reflowed layout. Ridgewood Commons was a *different system* per device.
3. **`post-type-archive-events` is not proof of The Events Calendar.** It's
   generic WordPress naming for any custom post type archive. Confirm via the
   `/wp-json/` namespace list.
4. **Search for a specific marker, not a product name.** Looking for
   `"addevent"` matched the widget's own CSS five times before reaching any
   button. `data-start=` can only appear on a real event.
5. **Don't match `captcha` as a bare substring.** Plenty of ordinary pages load
   reCAPTCHA for a newsletter box; an over-eager check discarded a fully
   rendered 400kb calendar as "blocked". Real challenge pages are *small* and
   say so in the title.
6. **Diagnose the page that has the thing.** `/events/` loads a widget's
   library; only `/events/<slug>/` renders the actual button.
7. **A huge JSON payload may not be this org's.** Ridgewood's 1MB feed was a
   *citywide* discovery blob mixing in unrelated orgs. Check for an
   `organization_name` field before trusting it.
8. **Preview windows hide the answer.** A 6000-char preview of a 1MB body
   shows nothing useful — search the full body for a known term instead.
9. **The diagnostic must render exactly like the build.** They drifted once:
   the builder sent Playwright's default `HeadlessChrome` user agent while the
   diagnostic sent an identifying one, and Grand Bazaar answered with **11kb
   and 80kb respectively**. A source diagnosed as workable — 22 event links
   plainly visible — returned zero in production and looked like a parsing
   bug. Both now share `BROWSER_CONTEXT` from `build_calendar.py`; never
   redefine it locally. If a source behaves differently in diagnosis and
   build, suspect this before anything else.
10. **A marker that "can only mean an event" usually can mean something
    else.** Finding AddEvent's button took three tries: `addevent` matched its
    own CSS, `data-start=` matched a content editor's character offsets on
    every `<p>` tag, and only `class="addeventatc"` was unambiguous — CSS
    writes selectors dot-prefixed, HTML writes them quote-prefixed. Test a
    marker against a fixture containing the traps before trusting it.

---

## 6. When to stop

**If three evidence-based techniques return nothing and the diagnostic offers
no new lead, park it** — with the specific reason and the next step, in
`config/sources.yaml`.

Do not add a fourth speculative technique. That pattern — hit a wall, add a
fallback, still fail, add another — is how an adapter grows four layers deep
where only two ever fire. Parking is not giving up; every parked source here
carries a written reason, and two of them (Grand Bazaar, Baby's All Right)
name the exact next thing to try.

A source that always returns zero is **worse than an absent one**: it looks
like a venue with no events rather than a bug.
