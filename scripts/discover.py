#!/usr/bin/env python3
"""Probe each org's site and work out the cheapest way to get its events.

Runs through the ingestion tiers in PLAN.md and reports, per org, the best
option found. Writes data/discovery.json and docs/triage.md.

This needs real internet access, so it runs in GitHub Actions rather than
locally. Nothing here writes to config/ — a human reads the triage report and
decides what goes into config/sources.yaml.
"""
import csv, json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA, DOCS = ROOT / "data", ROOT / "docs"

UA = ("brooklyn-event-calendar/0.1 (+https://github.com/"
      "9dpzmbpyym-crypto/Event-Calender) events-aggregator")
TIMEOUT = 15
DELAY = 1.5              # minimum seconds between requests to the SAME host

# Paths worth trying blind. Many sites serve a working feed without ever
# linking to it, which is a free Tier 0 win.
FEED_PATHS = [
    "/events.ics", "/calendar.ics", "/events/events.ics",
    "/?ical=1", "/events/?ical=1", "/calendar/?ical=1",
    "/wp-json/tribe/events/v1/events?per_page=50",
    "/events/feed/", "/feed/",
    "?format=ical",                       # Squarespace events collections
]

PLATFORMS = [
    ("the-events-calendar", r"tribe-events|the-events-calendar|tribe_events"),
    ("wordpress",           r"wp-content|wp-includes|wp-json"),
    ("squarespace",         r"squarespace\.com|static1\.squarespace"),
    ("wix",                 r"wixstatic|wix\.com|_wixCssStates"),
    ("shopify",             r"cdn\.shopify\.com"),
    ("eventbrite",          r"eventbrite\.(com|ca)"),
    ("dice",                r"dice\.fm"),
    ("luma",                r"lu\.ma"),
    ("resident-advisor",    r"ra\.co"),
    ("bandsintown",         r"bandsintown\.com"),
    ("withfriends",         r"withfriends\.(co|events)"),
    ("seetickets",          r"seetickets|eventim"),
    ("shotgun",             r"shotgun\.live"),
    ("ticketmaster",        r"ticketmaster\.com"),
    ("google-calendar",     r"calendar\.google\.com"),
    ("meetup",              r"meetup\.com"),
]

_last_hit = {}
_hit_lock = threading.Lock()
WORKERS = 6              # orgs probed at once; each is a different host

def polite_get(client, url):
    """Fetch a URL, pausing only if we hit this same host recently.

    The delay is what keeps us from hammering one venue's server. Because it
    is keyed on host, unrelated orgs never wait on each other -- which is only
    useful in combination with probing several orgs concurrently.
    """
    host = urlparse(url).netloc
    with _hit_lock:
        wait = DELAY - (time.monotonic() - _last_hit.get(host, 0))
        _last_hit[host] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)
    try:
        return client.get(url)
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        time.sleep(2)                      # one retry; slow hosts are common
        return client.get(url)


JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                    re.S | re.I)
ICS_HREF = re.compile(r'href=["\']([^"\']*(?:\.ics|ical=1|/ical/|format=ical)[^"\']*)["\']', re.I)
# Explicit Google Calendar URLs. Tried first — these are unambiguous.
GCAL_URL = re.compile(
    r'calendar\.google\.com/calendar/(?:embed|ical)[^"\'>]*?[?&]src=([^"\'&<\\]+)'
    r'|calendar\.google\.com/calendar/ical/([^/"\'<\\]+)/', re.I)
# Fallback: Wix and similar stash the id in a script blob with no URL around
# it. Restricted to group.calendar.google.com ids -- matching bare gmail
# addresses would turn any contact email on the page into a fake calendar.
GCAL_ID = re.compile(r'([\w.+-]+(?:%40|@)group\.calendar\.google\.com)', re.I)

ALT_CAL = re.compile(r'<link[^>]+type=["\']text/calendar["\'][^>]*>', re.I)
HREF_IN_TAG = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def count_jsonld_events(html):
    """How many schema.org Events are embedded in this page."""
    n = 0
    for blob in JSONLD.findall(html):
        try:
            doc = json.loads(blob.strip())
        except Exception:
            # some sites emit multiple concatenated objects or trailing junk
            n += len(re.findall(r'"@type"\s*:\s*"?\[?\s*"?Event', blob, re.I))
            continue
        stack = [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                t = node.get("@type", "")
                types = t if isinstance(t, list) else [t]
                if any(str(x).endswith("Event") for x in types):
                    n += 1
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return n


PLATFORM_REF = {
    "eventbrite": "https://www.eventbrite.com/o/{}",
    "dice":       "https://dice.fm/venue/{}",
    "ra":         "https://ra.co/clubs/{}",
    "luma":       "https://lu.ma/{}",
    "withfriends": "https://withfriends.events/o/{}/",
}

PLATFORM_ALIAS = {"resident-advisor": "ra"}

PLATFORM_DOMAIN = {
    "eventbrite": r"eventbrite\.(?:com|ca)",
    "dice": r"dice\.fm",
    "luma": r"lu\.ma",
    "withfriends": r"withfriends\.(?:co|events)",
    "resident-advisor": r"ra\.co",
    "bandsintown": r"bandsintown\.com",
    "shotgun": r"shotgun\.live",
    "seetickets": r"(?:seetickets|eventim)\.[a-z.]+",
    "ticketmaster": r"ticketmaster\.com",
}
# organizer/venue pages beat a link to a single ticket listing
GOOD_PATH = re.compile(r"/(?:o|venue|clubs|artists|p)/|/organizer/[^/]*\d", re.I)
# the platforms' own marketing and help pages, which are not anybody's listing
JUNK_PATH = re.compile(
    r"/(?:pricing|help|blog|signup|sign-up|login|log-in|about|contact|"
    r"support|legal|privacy|terms|careers|press|download|apps?|"
    r"organizer/(?:pricing|overview|resources)|d/|discover)\b", re.I)


def best_platform_link(html, platform):
    """Pull the most useful link to `platform` out of a page."""
    pat = re.compile(r'href=["\'](https?://[^"\']*'
                     + PLATFORM_DOMAIN[platform] + r'[^"\']*)["\']', re.I)
    links = [u for u in dict.fromkeys(pat.findall(html))
             if not JUNK_PATH.search(urlparse(u).path)]
    if not links:
        return ""
    ranked = sorted(links, key=lambda u: (not GOOD_PATH.search(u), len(u)))
    return ranked[0]


def parse_platforms(field):
    """Turn 'dice:cassette-922xo | ra:285265' into [(name, url), ...]."""
    out = []
    for part in (field or "").split("|"):
        part = part.strip()
        if not part:
            continue
        name, _, ref = part.partition(":")
        name, ref = name.strip().lower(), ref.strip()
        if name in PLATFORM_REF and ref:
            out.append((name, PLATFORM_REF[name].format(ref)))
        elif name:
            out.append((name, ""))
    return out


def ics_event_count(resp):
    """Number of events in an iCal response, or None if it isn't iCal at all.

    Squarespace puts an "add to calendar" link on every single event, so a
    naive .ics check happily returns a 260-byte file containing one event and
    calls it the venue's calendar feed. Counting VEVENTs is what separates a
    real feed from a single-event download.
    """
    ct = resp.headers.get("content-type", "").lower()
    body = resp.text
    if "calendar" not in ct and not body.lstrip().startswith("BEGIN:VCALENDAR"):
        return None
    return body.count("BEGIN:VEVENT")


def probe(client, org, log):
    """Return a dict describing the best ingestion route found for one org."""
    out = {
        "name": org["name"], "website": org.get("website", ""),
        "events_url": org.get("events_url", ""),
        "tier": None, "method": None, "feed_url": "",
        "platforms": [], "jsonld_events": 0, "evidence": [], "error": "",
    }
    base = org.get("website") or org.get("events_url")
    if not base:
        out.update(tier="5-manual", method="no-website",
                   error="no website known")
        return out

    pages = {}
    for url in filter(None, [org.get("events_url"), org.get("website")]):
        try:
            r = polite_get(client, url)
            if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
                pages[url] = r.text
            else:
                out["evidence"].append(f"{url} -> HTTP {r.status_code}")
        except Exception as e:
            out["evidence"].append(f"{url} -> {type(e).__name__}")
            log(f"    fetch failed {url}: {e}")

    if not pages:
        # A site that answers 403/202 to an identified crawler is declining to
        # be crawled. Rather than disguise ourselves, use a platform the org
        # already publishes to — that is the org's own public listing.
        alt = parse_platforms(org.get("other_platforms", ""))
        if alt:
            name, ref = alt[0]
            out.update(tier="1-platform", method=f"{name}-fallback",
                       feed_url=ref)
            out["evidence"].append(
                f"site declined our crawler; using its {name} listing instead")
            return out
        out.update(tier="4-browser", method="unreachable-or-js-only",
                   error="no HTML retrieved")
        return out

    html_all = "\n".join(pages.values())

    for name, pat in PLATFORMS:
        if re.search(pat, html_all, re.I):
            out["platforms"].append(name)

    # --- Tier 0: a real calendar feed ------------------------------------
    # Collection-level candidates first. A per-event "add to calendar" link
    # also ends in .ics, so ordering matters: ask for the whole calendar
    # before settling for whatever single event a page happens to link.
    candidates = []
    for u in filter(None, [org.get("events_url"), org.get("website")]):
        candidates.append(u.split("?")[0].rstrip("/") + "?format=ical")  # Squarespace
    root = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
    candidates += [root + path for path in FEED_PATHS if path.startswith("/")]

    for tag in ALT_CAL.findall(html_all):
        m = HREF_IN_TAG.search(tag)
        if m:
            candidates.insert(0, urljoin(base, m.group(1)))

    seen, per_event = set(), None
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            r = polite_get(client, url)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        n = ics_event_count(r)
        if n is None:
            if "tribe/events" in url and "json" in r.headers.get("content-type", ""):
                try:
                    count = len(r.json().get("events", []))
                except Exception:
                    count = 0
                if count:
                    out.update(tier="1-platform",
                               method="the-events-calendar-rest", feed_url=url)
                    out["evidence"].append(f"Tribe REST returned {count} events")
                    return out
            continue
        if n >= 2:
            out.update(tier="0-feed", method="calendar-feed", feed_url=url)
            out["evidence"].append(f"iCal feed with {n} events")
            return out
        if n == 1 and per_event is None:
            per_event = url          # remember, but keep looking for the real feed

    # Links inside the page. These are usually per-event on Squarespace, so
    # only accept one that actually holds a calendar's worth of events.
    for href in list(dict.fromkeys(ICS_HREF.findall(html_all)))[:5]:
        url = urljoin(base, href)
        if url in seen:
            continue
        seen.add(url)
        try:
            r = polite_get(client, url)
        except Exception:
            continue
        if r.status_code == 200:
            n = ics_event_count(r)
            if n and n >= 2:
                out.update(tier="0-feed", method="ics-in-page", feed_url=url)
                out["evidence"].append(f"iCal feed linked in page with {n} events")
                return out
            if n == 1 and per_event is None:
                per_event = url

    # Curated platform ids from websites.csv, before anything that depends on
    # page content. Public Records and Cafe con Libros each fingerprinted a
    # platform on one run and not the next -- these sites render differently
    # between fetches, so a human-verified id is strictly more reliable than
    # whatever markup came back this time.
    curated = [(n, u) for n, u in
               parse_platforms(org.get("other_platforms", "")) if u]
    if curated:
        name, url = curated[0]
        out.update(tier="1-platform", method=f"{name}-curated", feed_url=url)
        out["evidence"].append(f"verified {name} listing from websites.csv")
        if len(curated) > 1:
            out["evidence"].append(
                "also on: " + ", ".join(n for n, _ in curated[1:]))
        return out

    m = GCAL_URL.search(html_all) or GCAL_ID.search(html_all)
    if m:
        cal_id = unquote(next(g for g in m.groups() if g))
        out.update(tier="0-feed", method="google-calendar-embed",
                   feed_url=f"https://calendar.google.com/calendar/ical/"
                            f"{cal_id}/public/basic.ics")
        out["evidence"].append("embedded Google Calendar")
        return out

    if per_event:
        out["evidence"].append(
            f"only per-event iCal found - not a calendar feed")

    # --- Tier 1: ticketing platform the site points at --------------------
    # Recording only "links to eventbrite" is useless downstream: the builder
    # needs the actual organizer/venue URL. Prefer a curated id from
    # websites.csv, otherwise pull the best-looking link out of the page.

    curated = dict((n, u) for n, u in parse_platforms(org.get("other_platforms", "")) if u)
    for p in ("eventbrite", "dice", "luma", "withfriends", "resident-advisor",
              "bandsintown", "shotgun", "seetickets", "ticketmaster"):
        if p not in out["platforms"]:
            continue
        url = curated.get(p) or curated.get(PLATFORM_ALIAS.get(p, p)) or ""
        if not url:
            url = best_platform_link(html_all, p)
        out.update(tier="1-platform", method=f"{p}-linked", feed_url=url)
        out["evidence"].append(
            f"page links to {p}" + (f": {url}" if url else " (no usable URL found)"))
        return out

    # --- Tier 2: structured data in the page ------------------------------
    out["jsonld_events"] = count_jsonld_events(html_all)
    if out["jsonld_events"] >= 2:
        out.update(tier="2-jsonld", method="schema.org-events",
                   feed_url=org.get("events_url") or base)
        out["evidence"].append(f"{out['jsonld_events']} JSON-LD Events in page")
        return out

    # --- Tier 3: hand-written selectors will be needed --------------------
    out.update(tier="3-scrape", method="needs-selectors",
               feed_url=org.get("events_url") or base)
    out["evidence"].append(
        f"no feed/platform/JSON-LD found; {out['jsonld_events']} JSON-LD Events")
    return out


def main():
    rows = list(csv.DictReader(open(DATA / "websites.csv", encoding="utf-8")))
    results = []
    headers = {"User-Agent": UA, "Accept": "*/*"}
    log = lambda m: print(m, flush=True)

    # Each org's own probe is necessarily serial (11 requests to one host, each
    # spaced by DELAY), so the only way to shorten the run is to work on several
    # orgs at once. Different orgs are different hosts, so nobody gets hammered.
    def run_one(org):
        with httpx.Client(headers=headers, timeout=TIMEOUT,
                          follow_redirects=True) as c:
            try:
                res = probe(c, org, log)
            except Exception as e:             # one bad site must not stop the run
                res = {"name": org["name"], "tier": "error", "method": "",
                       "feed_url": "", "platforms": [], "jsonld_events": 0,
                       "evidence": [], "error": f"{type(e).__name__}: {e}"}
        log(f"  {org['name'][:34]:34} -> {res['tier']} / {res['method']}")
        return res

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(run_one, rows))
    log(f"\nprobed {len(results)} orgs in {time.monotonic()-started:.0f}s")

    DATA.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    (DATA / "discovery.json").write_text(
        json.dumps({"generated": datetime.now(timezone.utc).isoformat(),
                    "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    by_tier = defaultdict(list)
    for r in results:
        by_tier[r["tier"] or "unknown"].append(r)

    lines = ["# Feed discovery triage", "",
             f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · "
             f"{len(results)} orgs probed", "",
             "Tiers are defined in [PLAN.md](../PLAN.md). Lower is cheaper and "
             "more durable.", "", "## Summary", "",
             "| Tier | Orgs | What it means |", "|---|---|---|"]
    meaning = {
        "0-feed":     "Real calendar feed. Free, robust, done.",
        "1-platform": "Known ticketing platform. One adapter covers many orgs.",
        "2-jsonld":   "Structured data in the page. Generic extractor works.",
        "3-scrape":   "Needs hand-written selectors. Maintenance cost.",
        "4-browser":  "JS-rendered or unreachable. Browser + LLM fallback.",
        "5-manual":   "No machine-readable source. Hand entry.",
        "error":      "Probe crashed — investigate.",
    }
    for tier in sorted(by_tier):
        lines.append(f"| `{tier}` | {len(by_tier[tier])} | {meaning.get(tier,'')} |")

    for tier in sorted(by_tier):
        lines += ["", f"## {tier}", ""]
        for r in sorted(by_tier[tier], key=lambda x: x["name"]):
            bits = [f"**{r['name']}** — {r['method']}"]
            if r.get("feed_url"):
                bits.append(f"\n  - feed: `{r['feed_url']}`")
            if r.get("platforms"):
                bits.append(f"\n  - platforms seen: {', '.join(r['platforms'])}")
            for e in r.get("evidence", []):
                bits.append(f"\n  - {e}")
            if r.get("error"):
                bits.append(f"\n  - ⚠️ {r['error']}")
            lines.append("- " + "".join(bits))

    (DOCS / "triage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote data/discovery.json and docs/triage.md")
    for tier in sorted(by_tier):
        print(f"  {tier:12} {len(by_tier[tier])}")


if __name__ == "__main__":
    sys.exit(main())
