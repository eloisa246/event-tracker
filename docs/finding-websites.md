# Finding an org's real events source

The spreadsheet gives us Instagram handles, not websites. A website is what the
discovery job needs, so this is the step that unblocks everything else.

Two routes. Try the cheap one first.

---

## Route 1 — name search (automatic, works most of the time)

Search the org's name plus its neighborhood and "official website". On the first
34 orgs this found the right site **28 times out of 34**, so it should stay the
default — it costs nothing and needs no human.

It reliably fails on two kinds of org:

- **Generic names.** "BACKSPACE" returns everything and nothing. So do
  "Cassette", "Syndicated", "Spectacle".
- **Orgs with no website at all**, which is more common than it sounds among
  DIY spaces and party collectives.

## Route 2 — the Instagram bio link (manual, near-100%)

When search fails, go to the org's Instagram and open the link in their bio.
That link is almost always a Linktree, Beacons, or similar, and inside it is the
thing we actually want.

```
@wearebackspace  →  bio link  →  wearebackspace.com
@cassettenyc     →  bio link  →  dice.fm/venue/cassette-922xo
```

This works because **the bio link is the org's own answer to "where do I send
people to buy tickets"** — which is the same question the calendar is asking.
Search guesses; the bio link is the org telling you directly.

### What lands there is often better than a website

Cassette has no website at all. Its bio link goes straight to Dice, which is a
proper ticketing platform with structured data. That's a **Tier 1** source —
more reliable than scraping a hand-built HTML calendar would have been. An org
with "no website" is not a dead end and frequently isn't even a downgrade.

Watch for bio links pointing at: Dice, Eventbrite, lu.ma, Withfriends, Resident
Advisor, Shotgun, Partiful, Bandsintown. All of these are better outcomes than
a bespoke site.

---

## Strip the tracking junk

Bio links come loaded with tracking parameters:

```
https://quietreading.org/?utm_source=ig&utm_medium=social&fbclid=PAdGRleATjm...
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                        delete all of this
```

Keep only `https://quietreading.org/`. `scripts/parse_inbox.py` strips
`utm_*`, `fbclid`, `gclid`, `igshid` and friends automatically, but if you're
pasting a link into a spreadsheet by hand, cut everything from the `?` onward
unless it's clearly part of the real address.

---

## Recording what you find

Add the org to `data/websites.csv`:

| column | what to put |
|---|---|
| `website` | the cleaned root URL |
| `events_url` | the specific events/calendar page, if there is one |
| `other_platforms` | `dice:slug`, `eventbrite:org-id`, `ra:12345` — anything else they use |
| `confidence` | `high` if you saw it yourself, `medium` if you inferred it |
| `notes` | anything odd — closed for renovation, private-rental only, seasonal |

Then re-run the discovery job and it takes over from there.

---

## Scaling this to the rest of the list

209 orgs still need this. Realistic split, based on how the first 34 went:

1. Run name search across all of them automatically — expect it to resolve most.
2. What's left is the manual bio-link pass. It's a couple of minutes each and
   doesn't need to happen all at once; an org with no website simply stays out
   of the calendar until someone gets to it.

Worth doing in category order rather than alphabetically — music venues and
events boards earn their keep immediately, a retail shop that posts an event
twice a year does not.
