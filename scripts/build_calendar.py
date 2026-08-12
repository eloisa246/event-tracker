#!/usr/bin/env python3
"""Fetch every configured source, normalize the events, and emit the calendar.

Reads config/sources.yaml. Writes:
  data/events.json      the normalized store
  public/calendar.ics   the subscribable feed
  public/<category>.ics filtered feeds
  docs/health.md        per-source status

Run from cron via scripts/run.sh -- on your own machine or a VPS, NOT from
GitHub Actions (docs/COMPLIANCE.md §1). Safe to run repeatedly: identities are
stable, so
re-running produces the same UIDs and subscribers see updates rather than a
delete-and-re-add of everything.
"""
import hashlib, json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx, yaml

ROOT = Path(__file__).resolve().parent.parent
DATA, PUBLIC, DOCS = ROOT / "data", ROOT / "public", ROOT / "docs"

NY = ZoneInfo("America/New_York")
UA = ("brooklyn-event-calendar/0.1 (+https://github.com/"
      "eloisa246/event-tracker) events-aggregator")

# Browser context for every rendered page. scripts/diagnose.py imports this
# rather than defining its own, and that is the whole point: the diagnostic is
# only worth running if it renders what the build renders.
#
# They drifted once, expensively. The builder passed no user_agent, so
# Playwright sent its default "HeadlessChrome" string, while the diagnostic
# sent the identifying one below. Grand Bazaar answered the first with 11kb
# and the second with 80kb -- so a source that diagnosed as perfectly
# workable, with 22 event links visible, returned zero in production and
# looked like a parsing problem. Any per-page finding is only as trustworthy
# as the two paths being identical.
BROWSER_CONTEXT = {
    "locale": "en-US",
    "timezone_id": "America/New_York",
    "viewport": {"width": 1280, "height": 2000},
    "user_agent": UA + " Mozilla/5.0",
}
WINDOW_DAYS = 180
WORKERS = 6
DELAY = 1.5

_last_hit, _hit_lock = {}, threading.Lock()

# robots.txt, fetched once per host and cached for the run.
#
# Fail-open is deliberate: a host that has no robots.txt, or whose robots.txt
# is unreachable, is treated as allowing the fetch. That matches what every
# mainstream crawler does -- absence of the file is not a prohibition. Only an
# explicit Disallow that matches stops us, and when it does we skip the source
# and say so in health.md rather than fetching anyway.
UA_TOKEN = "brooklyn-event-calendar"
_robots, _robots_lock = {}, threading.Lock()


class RobotsDisallowed(Exception):
    """robots.txt explicitly disallows this path for our user-agent."""


def _robots_for(origin):
    with _robots_lock:
        if origin in _robots:
            return _robots[origin]
    rp = RobotFileParser()
    try:
        # Fetched with our own UA and short timeout rather than
        # RobotFileParser.read(), which would use urllib's default UA and
        # ignore our timeout entirely.
        r = httpx.get(origin + "/robots.txt", timeout=10,
                      headers={"User-Agent": UA}, follow_redirects=True)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except Exception:
        rp.parse([])                  # unreachable -> treat as allow-all
    with _robots_lock:
        _robots.setdefault(origin, rp)
        return _robots[origin]


def robots_allows(url):
    p = urlparse(url)
    if not p.scheme.startswith("http"):
        return True
    return _robots_for(f"{p.scheme}://{p.netloc}").can_fetch(UA_TOKEN, url)


def polite_get(client, url):
    if not robots_allows(url):
        raise RobotsDisallowed(f"robots.txt disallows {urlparse(url).path or '/'}")
    host = urlparse(url).netloc
    with _hit_lock:
        wait = DELAY - (time.monotonic() - _last_hit.get(host, 0))
        _last_hit[host] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)
    try:
        return client.get(url)
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        time.sleep(2)
        return client.get(url)


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------
@dataclass
class Event:
    uid: str = ""
    source_id: str = ""
    org: str = ""
    title: str = ""
    description: str = ""
    start: str = ""              # ISO 8601, always tz-aware
    end: str = ""
    all_day: bool = False
    location: str = ""
    url: str = ""
    categories: list = field(default_factory=list)
    status: str = "scheduled"
    extra_urls: list = field(default_factory=list)

    def compute_uid(self):
        """Deterministic identity: same event in, same UID out, every run.

        Regenerating UIDs per run makes every subscriber's calendar delete and
        re-add every event on every sync. Keyed on source + canonical link (or
        title) + start, so an edited title or moved time is an update rather
        than a stranger.
        """
        key = f"{self.source_id}|{self.url or self.title.lower()}|{self.start}"
        self.uid = hashlib.sha1(key.encode("utf-8")).hexdigest() + "@bk-calendar"
        return self.uid


def to_iso(value, all_day=False):
    """Normalize whatever a source gave us into a tz-aware ISO string."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.isoformat() if all_day else datetime(
            value.year, value.month, value.day, tzinfo=NY).isoformat()
    else:
        s = str(value).strip()
        if not s:
            return ""
        s = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)       # sources publish local time
    return dt.isoformat()


def in_window(ev, days=WINDOW_DAYS):
    if not ev.start:
        return False
    try:
        dt = datetime.fromisoformat(ev.start)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    now = datetime.now(timezone.utc)
    return now - timedelta(days=1) <= dt <= now + timedelta(days=days)


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------
def fetch_ical(client, src):
    from icalendar import Calendar
    r = polite_get(client, src["feed_url"])
    r.raise_for_status()
    cal = Calendar.from_ical(r.text)
    out = []
    for comp in cal.walk("VEVENT"):
        dtstart = comp.get("DTSTART")
        if not dtstart:
            continue
        raw = dtstart.dt
        all_day = not isinstance(raw, datetime)
        dtend = comp.get("DTEND")
        ev = Event(
            source_id=src["id"], org=src["name"],
            title=str(comp.get("SUMMARY", "")).strip(),
            description=str(comp.get("DESCRIPTION", "")).strip()[:800],
            start=to_iso(raw, all_day),
            end=to_iso(dtend.dt, all_day) if dtend else "",
            all_day=all_day,
            location=str(comp.get("LOCATION", "")).strip(),
            url=str(comp.get("URL", "")).strip(),
            categories=list(src.get("categories", [])),
            status=str(comp.get("STATUS", "CONFIRMED")).lower().replace(
                "confirmed", "scheduled"),
        )
        if ev.title:
            out.append(ev)
    return out


def fetch_google_calendar(client, src):
    cal_id = src.get("calendar_id") or ""
    src = dict(src, feed_url=src.get("feed_url") or
               f"https://calendar.google.com/calendar/ical/{cal_id}/public/basic.ics")
    return fetch_ical(client, src)


JSONLD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)


def _walk_events(node, found):
    if isinstance(node, dict):
        t = node.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if any(str(x).endswith("Event") for x in types):
            found.append(node)
        for v in node.values():
            _walk_events(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_events(v, found)


def fetch_jsonld(client, src):
    r = polite_get(client, src["feed_url"])
    r.raise_for_status()
    found = []
    for blob in JSONLD.findall(r.text):
        try:
            _walk_events(json.loads(blob.strip()), found)
        except Exception:
            continue

    out = []
    for node in found:
        loc = node.get("location") or {}
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        loc_name = loc.get("name", "") if isinstance(loc, dict) else str(loc)
        addr = loc.get("address", "") if isinstance(loc, dict) else ""
        if isinstance(addr, dict):
            addr = " ".join(str(addr.get(k, "")) for k in
                            ("streetAddress", "addressLocality") if addr.get(k))
        ev = Event(
            source_id=src["id"], org=src["name"],
            title=str(node.get("name", "")).strip(),
            description=re.sub(r"<[^>]+>", "",
                               str(node.get("description", "")))[:800].strip(),
            start=to_iso(node.get("startDate", "")),
            end=to_iso(node.get("endDate", "")),
            location=", ".join(x for x in (loc_name, addr) if x),
            url=urljoin(src["feed_url"], str(node.get("url", ""))),
            categories=list(src.get("categories", [])),
            status="cancelled" if "Cancel" in str(node.get("eventStatus", ""))
                   else "scheduled",
        )
        if ev.title and ev.start:
            out.append(ev)
    return out


# A Bandsintown adapter lived here and was removed. Its REST API returned 403
# to every request, exactly as their HTML pages did, so it never produced a
# single event. The plausible fix -- registering a real app_id -- was never
# tested, and shipping an adapter that has only ever failed invites someone to
# configure it and get a silent zero. See docs/PLAYBOOK.md if it's revisited.


# Common paths for a Squarespace events collection. ?format=json only returns
# event items on the collection page itself -- a homepage or a regular page
# returns site chrome, which is why pointing at "/" silently yielded nothing.
SQ_PATHS = ["/events", "/calendar", "/shows", "/upcoming", "/program",
            "/whats-on", "/schedule", "/tickets"]


SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
EVENTISH = re.compile(r"event|calendar|show|program|schedule|whats-?on|upcoming|"
                      r"gig|listing|market|class", re.I)


def sitemap_pages(client, root):
    """Page URLs from the site's own sitemap, event-looking ones first.

    Guessing paths produced five 404s per site and found nothing. The sitemap
    is the site telling us which pages exist, so use that instead.
    """
    try:
        r = polite_get(client, root + "/sitemap.xml")
        if r.status_code != 200:
            return []
    except Exception:
        return []
    urls = [u for u in SITEMAP_LOC.findall(r.text)
            if urlparse(u).netloc == urlparse(root).netloc]
    urls.sort(key=lambda u: (not EVENTISH.search(urlparse(u).path), len(u)))
    return urls[:12]


def fetch_squarespace(client, src):
    """Read a Squarespace events collection through its own ?format=json view.

    Tries the configured page, then the usual collection paths, then whatever
    the site's sitemap says exists. When nothing holds events it records the
    JSON keys each page returned, so the next failure says what the site
    actually served instead of just "nothing".
    """
    configured = src["feed_url"].split("?")[0].rstrip("/")
    parts = urlparse(configured)
    root = f"{parts.scheme}://{parts.netloc}"
    from_sitemap = sitemap_pages(client, root)
    candidates = [configured] + [root + p for p in SQ_PATHS] + from_sitemap

    tried, seen = [], set()
    for page in candidates:
        if page in seen:
            continue
        seen.add(page)
        try:
            r = polite_get(client, page + "?format=json")
            if r.status_code != 200:
                tried.append(f"{urlparse(page).path or '/'}={r.status_code}")
                continue
            data = r.json()
        except Exception:
            tried.append(f"{urlparse(page).path or '/'}=nojson")
            continue
        events = find_event_records(data, src, page)
        if events:
            src["_method"] = f"squarespace-json {urlparse(page).path or '/'}"
            return events
        keys = ",".join(list(data.keys())[:4]) if isinstance(data, dict) else "?"
        tried.append(f"{urlparse(page).path or '/'}=[{keys}]")

    # Show what the sitemap offered and the pages actually checked. Truncating
    # to the first few hid the sitemap attempts entirely last run, which made
    # it impossible to tell whether that step had even happened.
    sm = (f"sitemap:{len(from_sitemap)} pages "
          f"({', '.join(urlparse(u).path for u in from_sitemap[:4])})"
          if from_sitemap else "sitemap: none")
    src["_method"] = f"no events collection. {sm}. checked: " + " ".join(tried[-6:])
    return []


# --- browser rendering -----------------------------------------------------
# Eventbrite organizer pages build their listing in JavaScript, so an HTTP
# fetch returns an empty shell. Rendering with a real browser is the only way
# to read them. Kept deliberately narrow: one page load per source per run,
# results cached, and anything that is a genuine access control (a CAPTCHA or
# a login wall) is reported as blocked rather than worked around.
BROWSER_WAIT_MS = 6000
BLOCKED_MARKERS = re.compile(
    r"are you a robot|verify you are human|unusual traffic|px-captcha|"
    r"cf-challenge|please enable javascript and cookies|"
    r"checking your browser before accessing", re.I)
CHALLENGE_TITLE = re.compile(
    r"<title[^>]*>\s*(?:just a moment|attention required|access denied|"
    r"security check|verify)", re.I)


def looks_blocked(html):
    """A challenge page, as opposed to a page that merely mentions captcha.

    Matching the word "captcha" anywhere was too eager: plenty of real pages
    load reCAPTCHA for a newsletter signup, and a fully rendered 400kb
    calendar was being discarded as a challenge. Real challenge pages are
    small and say so in the title.
    """
    if CHALLENGE_TITLE.search(html[:4000]):
        return True
    return len(html) < 60000 and bool(BLOCKED_MARKERS.search(html[:20000]))


def render_page(url):
    """Render a page and also capture the JSON its own scripts fetch.

    A site that draws its calendar in JavaScript is reading that calendar from
    somewhere. Watching the page's own network traffic finds that source
    without guessing at endpoints or writing per-site selectors, and the data
    there is structured where the rendered markup is not.

    Returns (html, [json payloads]); html is "" if the page is a challenge.
    """
    from playwright.sync_api import sync_playwright
    if not robots_allows(url):
        raise RobotsDisallowed(f"robots.txt disallows {urlparse(url).path or '/'}")
    payloads = []

    def on_response(resp):
        try:
            ct = (resp.headers or {}).get("content-type", "")
            if "json" not in ct.lower() or resp.status != 200:
                return
            if len(payloads) >= 40:
                return
            payloads.append(resp.json())
        except Exception:
            pass

    with sync_playwright() as pw:
        # Launched with default flags. An earlier version passed
        # --disable-blink-features=AutomationControlled, whose only purpose is
        # to stop a site from detecting that the browser is automated. Hiding
        # that we are a bot contradicts the posture in PLAN.md §9 -- identify
        # yourself, respect robots.txt, stay easy to block -- so it is gone. A
        # source that only worked with it was working by evading a control the
        # site chose to put up; if one goes dark here, that is the signal, and
        # the fix is to ask the venue, not to hide better.
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(**BROWSER_CONTEXT)
            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=BROWSER_WAIT_MS)
            except Exception:
                pass                      # slow trackers shouldn't fail the render
            page.mouse.wheel(0, 6000)     # events often lazy-load on scroll
            page.wait_for_timeout(2000)
            html = page.content()
        finally:
            browser.close()
    if looks_blocked(html):
        return "", payloads
    return html, payloads


# One generic definition of "this dict looks like an event", used everywhere
# an unstructured JSON blob needs searching: a page's own network traffic
# (browser adapter) and a Squarespace ?format=json response alike. Squarespace
# previously had its own hardcoded key list ("items"/"upcoming"/"past") that
# missed index-page layouts entirely (Baby's All Right's homepage IS its
# events collection, nested differently than a plain collection page) --
# recursively searching for the shape instead of a fixed set of paths finds
# it regardless of how deep or where it sits.
TITLE_KEYS = ("name", "title", "eventName", "headline", "event_name")
DATE_KEYS = ("startDate", "start_date", "startsAt", "starts_at", "startTime",
             "start_time", "start", "date", "datetime", "doorsAt", "eventDate")
END_KEYS = ("endDate", "end_date", "endsAt", "ends_at", "end")
TIME_KEYS = ("startTime", "start_time", "doorTime", "door_time", "time")
DESC_KEYS = ("description", "excerpt", "body", "summary")
LINK_KEYS = ("url", "link", "permalink", "ticketUrl", "fullUrl", "slug")
BARE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


BARE_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def _node_datetime(node, keys):
    """Pull a datetime out of a dict, trying `keys` in order.

    Handles every shape actually seen in production: Squarespace's epoch
    milliseconds, a {utc,local,iso} wrapper, and a bare YYYY-MM-DD date that
    needs recombining with a separate time-of-day field -- VenuePilot's
    GraphQL API (Market Hotel) puts "date" and "startTime" on the same
    object rather than one combined timestamp.

    That split is what makes this two-pass rather than "take the first key
    present": "startTime" sorts before "date" in DATE_KEYS, and on VenuePilot
    it holds only "23:00:00" -- a bare time with no date, which parses to
    nothing on its own. Taking the first non-empty key naively would grab
    that and give up before ever reaching the real date. Every candidate is
    scanned for a genuinely complete value first; a bare date is remembered
    and only used, combined with a time field, if nothing better turns up.
    """
    date_only = None
    for k in keys:
        v = node.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, (int, float)):
            return to_iso(datetime.fromtimestamp(v / 1000, tz=timezone.utc))
        if isinstance(v, dict):
            v = v.get("utc") or v.get("local") or v.get("iso") or ""
            if not v:
                continue
        if isinstance(v, str):
            v = v.strip()
            if BARE_TIME.match(v):
                continue                      # time with no date -- useless alone
            if BARE_DATE.match(v):
                date_only = date_only or v    # keep looking for something fuller
                continue
            parsed = to_iso(v)
            if parsed:
                return parsed
    if date_only:
        t = next((node[k] for k in TIME_KEYS if isinstance(node.get(k), str)
                  and BARE_TIME.match(node[k].strip())), None)
        return to_iso(f"{date_only}T{t.strip()}" if t else date_only)
    return ""


def find_event_records(node, src, page_url, found=None, seen=None):
    """Recursively find event-shaped dicts anywhere in a JSON structure."""
    if found is None:
        found, seen = [], set()
    if isinstance(node, dict):
        title = next((node[k] for k in TITLE_KEYS
                      if isinstance(node.get(k), str) and node[k].strip()), None)
        if title:
            start = _node_datetime(node, DATE_KEYS)
            # a plausible event has a real title and a parseable date
            if start and 4 <= len(title) <= 200:
                key = (title.strip().lower(), start[:16])
                if key not in seen:
                    seen.add(key)
                    link = next((node[k] for k in LINK_KEYS
                                 if isinstance(node.get(k), str)), "")
                    desc = next((node[k] for k in DESC_KEYS
                                 if isinstance(node.get(k), str)), "")
                    loc = node.get("venue") or node.get("location") or {}
                    loc_name = (loc.get("name") or loc.get("addressTitle") or "") \
                              if isinstance(loc, dict) else (loc if isinstance(loc, str) else "")
                    found.append(Event(
                        source_id=src["id"], org=src["name"],
                        title=title.strip(),
                        description=re.sub(r"<[^>]+>", "", desc)[:800].strip(),
                        start=start, end=_node_datetime(node, END_KEYS),
                        location=loc_name,
                        url=urljoin(page_url, link) if link else page_url,
                        categories=list(src.get("categories", []))))
        for v in node.values():
            find_event_records(v, src, page_url, found, seen)
    elif isinstance(node, list):
        for v in node:
            find_event_records(v, src, page_url, found, seen)
    return found


def events_from_payloads(payloads, src, page_url):
    """Find event-shaped records in whatever JSON the page fetched."""
    found, seen = [], set()
    for p in payloads:
        find_event_records(p, src, page_url, found, seen)
    return found


def _events_from_html(html, src, page_url):
    found = []
    for blob in JSONLD.findall(html):
        try:
            _walk_events(json.loads(blob.strip()), found)
        except Exception:
            continue
    out = []
    for node in found:
        loc = node.get("location") or {}
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        ev = Event(
            source_id=src["id"], org=src["name"],
            title=str(node.get("name", "")).strip(),
            description=re.sub(r"<[^>]+>", "",
                               str(node.get("description", "")))[:800].strip(),
            start=to_iso(node.get("startDate", "")),
            end=to_iso(node.get("endDate", "")),
            location=(loc.get("name", "") if isinstance(loc, dict) else str(loc)),
            url=urljoin(page_url, str(node.get("url", ""))),
            categories=list(src.get("categories", [])),
        )
        if ev.title and ev.start:
            out.append(ev)
    return out


# Links to individual event pages found in a rendered listing. Those detail
# pages are SEO-oriented and do carry schema.org data even when the listing
# they came from carries none.
EVENT_LINK = re.compile(
    r'href=["\'](https?://[^"\']*(?:'
    r'eventbrite\.[a-z.]+/e/|withfriends\.events/[^"\']*/events?/|'
    r'/event[s]?/|/e/)[^"\'#?]*)', re.I)


# AddEvent's "Add to Calendar" button carries the event in child spans, not
# in data- attributes:
#   <div class="addeventatc">
#     <span class="start    atc_node">04/23/2026 10:00 am</span>
#     <span class="end      atc_node">04/23/2026 5:00 pm</span>
#     <span class="location atc_node">...</span>
# Attribute-based searches miss it entirely for that reason. The widget is
# common on WordPress event pages that expose no feed, no REST API and no
# schema.org, which is otherwise a dead end.
ATC_BLOCK = re.compile(r'class="[^"]*addeventatc[^"]*"(.*?)</div>', re.S | re.I)
ATC_FIELD = re.compile(
    r'<span[^>]*class="[^"]*\b(start|end|title|location|description)\b[^"]*"[^>]*>(.*?)</span>',
    re.S | re.I)
# "04/23/2026 10:00 am"
ATC_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*([ap]m)?", re.I)


def _atc_datetime(text):
    m = ATC_DATE.search(text or "")
    if not m:
        return ""
    mo, day, yr, hh, mm, ampm = m.groups()
    hh = int(hh)
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hh != 12:
            hh += 12
        elif ampm == "am" and hh == 12:
            hh = 0
    return to_iso(datetime(int(yr), int(mo), int(day), hh, int(mm), tzinfo=NY))


def events_from_addevent(html, src, page_url):
    """Read events out of AddEvent 'Add to Calendar' widgets on a page."""
    out = []
    for block in ATC_BLOCK.findall(html):
        fields = {}
        for name, value in ATC_FIELD.findall(block):
            name = name.lower()
            if name not in fields:
                fields[name] = re.sub(r"<[^>]+>", "", value).strip()
        start = _atc_datetime(fields.get("start", ""))
        if not start:
            continue
        # The widget often omits a title span and relies on the page's <h1>.
        title = fields.get("title") or ""
        if not title:
            h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
            title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""
        if not title:
            continue
        ev = Event(
            source_id=src["id"], org=src["name"], title=title,
            description=fields.get("description", "")[:800],
            start=start, end=_atc_datetime(fields.get("end", "")),
            location=fields.get("location", ""),
            url=page_url, categories=list(src.get("categories", [])),
        )
        out.append(ev)
    return out


def _events_from_detail_pages(client, html, src, page_url, limit=25):
    """Follow links from a listing to detail pages that carry structured data."""
    links = []
    for u in dict.fromkeys(EVENT_LINK.findall(html)):
        if urlparse(u).netloc and u not in links:
            links.append(u)
    out = []
    for link in links[:limit]:
        try:
            r = polite_get(client, link)
            if r.status_code != 200:
                continue
        except Exception:
            continue
        got = _events_from_html(r.text, src, link)
        if not got:
            got = events_from_addevent(r.text, src, link)
        out += got
    return out, len(links)


def fetch_browser(client, src):
    """Render the page and try three techniques, in order of actual evidence.

    Each one is kept because it has a confirmed win in production, not because
    it seemed plausible. A fourth technique -- pairing a bare <time datetime>
    with the nearest heading text -- was cut. It never once produced a real
    event across every source that fell through to it, and matching a
    timestamp to a title by proximity is exactly the kind of guess that can
    silently pair the wrong two together rather than just finding nothing.
    """
    url = src["feed_url"]
    try:
        html, payloads = render_page(url)
    except Exception as e:
        src["_method"] = f"render failed: {type(e).__name__}"
        return []
    if not html:
        src["_method"] = "blocked (captcha or challenge page) - not worked around"
        return []
    kb = len(html) // 1024

    # 1. schema.org in the rendered DOM -- the same trusted extractor used for
    #    every non-browser source, just applied after JS has run.
    events = _events_from_html(html, src, url)
    if events:
        src["_method"] = f"browser-render {kb}kb, schema.org in listing"
        return events

    # 2. what the page fetched for itself. A JS-built calendar is reading its
    #    data from somewhere, and this is it. Confirmed on Hive Mind and
    #    Elsewhere -- the strongest technique here after schema.org itself.
    events = events_from_payloads(payloads, src, url)
    if events:
        src["_method"] = (f"browser-render {kb}kb, {len(events)} from the page's "
                          f"own JSON ({len(payloads)} responses seen)")
        return events

    # 3. an "Add to Calendar" widget on this page. Its child spans carry the
    #    real start/end/location even when the page has no feed, no REST API
    #    and no schema.org. Confirmed on Grand Bazaar.
    events = events_from_addevent(html, src, url)
    if events:
        src["_method"] = f"browser-render {kb}kb, {len(events)} from AddEvent widget"
        return events

    # 4. the listing carries no structured data, but its detail pages might --
    #    via schema.org or their own AddEvent widgets. Confirmed on Greenlight.
    events, n_links = _events_from_detail_pages(client, html, src, url)
    if events:
        src["_method"] = f"browser-render {kb}kb, {len(events)} from {n_links} detail pages"
        return events

    src["_method"] = (f"browser-render {kb}kb but nothing extractable: "
                      f"no schema.org, {len(payloads)} json responses, "
                      f"{n_links} event links found")
    return []


def fetch_tribe(client, src):
    url = src["feed_url"]
    r = polite_get(client, url)
    r.raise_for_status()
    out = []
    for e in r.json().get("events", []):
        venue = e.get("venue") or {}
        ev = Event(
            source_id=src["id"], org=src["name"],
            title=(e.get("title") or "").strip(),
            description=re.sub(r"<[^>]+>", "", e.get("description") or "")[:800].strip(),
            start=to_iso(e.get("start_date", "")),
            end=to_iso(e.get("end_date", "")),
            all_day=bool(e.get("all_day")),
            location=", ".join(x for x in (venue.get("venue", ""),
                                           venue.get("address", "")) if x),
            url=e.get("url", ""),
            categories=list(src.get("categories", [])),
        )
        if ev.title and ev.start:
            out.append(ev)
    return out


# Strategy name -> adapter. Every entry here is either confirmed working in
# production or a thin wrapper over one that is. Aliases for resident_advisor,
# withfriends, seetickets and bandsintown were removed: each mapped to an
# adapter that returned 403 or nothing for every org that used it, so the
# registry was advertising support that did not exist. A strategy name that
# isn't here now fails loudly with "no adapter" instead of silently reporting
# zero events, which is the more useful failure. docs/PLAYBOOK.md records what
# to try for those platforms.
ADAPTERS = {
    # --- confirmed in production -------------------------------------------
    "ical": fetch_ical,                # Ridgewood Commons (35 events)
    "jsonld": fetch_jsonld,            # The Tiny Cupboard (141)
    "squarespace": fetch_squarespace,  # Friends and Lovers, Film Noir, Starr Bar
    "browser": fetch_browser,          # Market Hotel, Hive Mind, Greenlight, Elsewhere
    # Dice serves schema.org on plain HTML -- no browser needed. Confirmed on
    # Public Records, Cassette and Seventh Heaven.
    "dice": fetch_jsonld,
    # Eventbrite organizer pages build their listing in JS and have no working
    # plain-HTTP route, so they render. Confirmed on Hive Mind and Greenlight.
    "eventbrite_organizer": fetch_browser,

    # --- written but never exercised against a real source -----------------
    # Both are small and standard enough to be worth keeping for the expansion
    # past the pilot, but neither has produced an event here yet. Treat a zero
    # from these as "unverified adapter", not "org has no events".
    "google_calendar": fetch_google_calendar,   # wrapper over fetch_ical
    "tribe_events": fetch_tribe,                # The Events Calendar REST
}


# --------------------------------------------------------------------------
# dedupe
# --------------------------------------------------------------------------
def norm_title(t):
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    t = re.sub(r"\b(presents?|feat|featuring|w|with|the|a|an|live|at)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def dedupe(events):
    """Merge the same event arriving from two sources.

    A show listed on the venue's own site and on Dice is one event with two
    links, not two events. Matched on normalized title plus a start time within
    30 minutes; anything looser starts merging genuinely different shows.
    """
    buckets, merged = {}, []
    for ev in sorted(events, key=lambda e: (e.start, e.title)):
        try:
            dt = datetime.fromisoformat(ev.start)
        except ValueError:
            merged.append(ev)
            continue
        key = (norm_title(ev.title), dt.date())
        hit = None
        for cand in buckets.get(key, []):
            try:
                other = datetime.fromisoformat(cand.start)
            except ValueError:
                continue
            if abs((dt - other).total_seconds()) <= 1800:
                hit = cand
                break
        if hit:
            if len(ev.description) > len(hit.description):
                hit.description = ev.description
            if not hit.location and ev.location:
                hit.location = ev.location
            if ev.url and ev.url != hit.url and ev.url not in hit.extra_urls:
                hit.extra_urls.append(ev.url)
            for c in ev.categories:
                if c not in hit.categories:
                    hit.categories.append(c)
        else:
            buckets.setdefault(key, []).append(ev)
            merged.append(ev)
    return merged


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def ics_escape(s):
    return (s.replace("\\", "\\\\").replace(";", r"\;")
             .replace(",", r"\,").replace("\n", r"\n"))


def fold(line):
    """iCal lines must not exceed 75 octets; continuations start with a space."""
    out, cur = [], line
    while len(cur.encode("utf-8")) > 73:
        cut = 73
        while len(cur[:cut].encode("utf-8")) > 73:
            cut -= 1
        out.append(cur[:cut])
        cur = " " + cur[cut:]
    out.append(cur)
    return "\r\n".join(out)


def to_ics(events, name):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//bk-calendar//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_escape(name)}",
             "X-WR-TIMEZONE:America/New_York"]
    for ev in events:
        try:
            dt = datetime.fromisoformat(ev.start)
        except ValueError:
            continue
        if ev.all_day:
            dstart = f"DTSTART;VALUE=DATE:{dt.strftime('%Y%m%d')}"
        else:
            dstart = ("DTSTART;TZID=America/New_York:"
                      + dt.astimezone(NY).strftime("%Y%m%dT%H%M%S"))
        body = ev.description
        for u in [ev.url] + ev.extra_urls:
            if u:
                body += f"\n{u}"
        lines += ["BEGIN:VEVENT", f"UID:{ev.uid}", f"DTSTAMP:{stamp}", dstart]
        if ev.end and not ev.all_day:
            try:
                de = datetime.fromisoformat(ev.end).astimezone(NY)
                lines.append("DTEND;TZID=America/New_York:"
                             + de.strftime("%Y%m%dT%H%M%S"))
            except ValueError:
                pass
        lines.append(fold(f"SUMMARY:{ics_escape(ev.org + ' — ' + ev.title)}"))
        if body.strip():
            lines.append(fold(f"DESCRIPTION:{ics_escape(body.strip())}"))
        if ev.location:
            lines.append(fold(f"LOCATION:{ics_escape(ev.location)}"))
        if ev.url:
            lines.append(fold(f"URL:{ev.url}"))
        if ev.categories:
            lines.append(fold("CATEGORIES:" + ",".join(
                ics_escape(c) for c in ev.categories)))
        if ev.status == "cancelled":
            lines.append("STATUS:CANCELLED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def load_manual():
    """Events entered by hand, from config/manual-events.yaml.

    Tier 5 in PLAN.md: the honest floor. A lot of the best small stuff -- a
    collective's collage night, a reading group in someone's back room -- exists
    only as a flyer on Instagram and will never be machine-readable. Rather than
    pretend otherwise, they get typed in and flow through the same normalize,
    dedupe and ICS path as everything else.

    Deliberately forgiving: a malformed row is skipped with a named reason and
    the build continues. Losing the whole calendar because one hand-typed date
    had a typo would be a much worse failure than dropping that one event.
    """
    path = ROOT / "config" / "manual-events.yaml"
    if not path.exists():
        return [], "", 0
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return [], f"{type(e).__name__}: {e}", 0

    rows = cfg.get("events") or []
    out, skipped = [], []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            skipped.append(f"#{i} not a list item with fields")
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            skipped.append(f"#{i} no title")
            continue
        start = to_iso(row.get("start"))
        if not start:
            skipped.append(f"{title[:24]!r} bad/missing start")
            continue
        cats = row.get("categories") or row.get("category") or []
        if isinstance(cats, str):
            cats = [cats]
        ev = Event(
            source_id="manual",
            org=str(row.get("org") or "").strip(),
            title=title,
            description=str(row.get("description") or "").strip(),
            start=start,
            end=to_iso(row.get("end")),
            location=str(row.get("location") or "").strip(),
            url=str(row.get("url") or "").strip(),
            categories=[str(c) for c in cats],
        )
        out.append(ev)
    return out, "; ".join(skipped), len(rows)


def main():
    cfg_path = ROOT / "config" / "sources.yaml"
    if not cfg_path.exists():
        print("config/sources.yaml not found — run discovery and build it first.")
        return 1
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    sources = [s for s in cfg.get("sources", []) if s.get("strategy") != "manual"]

    health, all_events = [], []
    headers = {"User-Agent": UA, "Accept": "*/*"}

    def run_one(src):
        fn = ADAPTERS.get(src.get("strategy"))
        if not fn:
            return src, [], f"no adapter for strategy '{src.get('strategy')}'"
        with httpx.Client(headers=headers, timeout=20,
                          follow_redirects=True) as c:
            try:
                return src, fn(c, src), ""
            except Exception as e:
                return src, [], f"{type(e).__name__}: {e}"

    http_sources = [s for s in sources if s.get("strategy") != "browser"]
    browser_sources = [s for s in sources if s.get("strategy") == "browser"]

    def results():
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            yield from pool.map(run_one, http_sources)
        for s in browser_sources:        # sequential: sync Playwright isn't thread-safe
            yield run_one(s)

    for src, events, err in results():
        kept = [e for e in events if in_window(e)]
        for e in kept:
            e.compute_uid()
        all_events += kept
        health.append({"id": src["id"], "name": src["name"],
                       "strategy": src.get("strategy", ""),
                       "method": src.get("_method", ""),
                       "found": len(events), "kept": len(kept), "error": err})
        print(f"  {src['name'][:32]:32} {len(kept):4} events"
              + (f"  ⚠️ {err}" if err else ""))

    # Hand-entered events join before dedupe, so a flyer typed in by hand and
    # the same show later found by a scraper merge into one entry rather than
    # showing up twice.
    manual, manual_err, manual_total = load_manual()
    kept_manual = [e for e in manual if in_window(e)]
    for e in kept_manual:
        e.compute_uid()
    all_events += kept_manual
    if manual_total or manual_err:
        health.append({"id": "manual", "name": "Hand-entered", "strategy": "manual",
                       "method": f"{manual_total} in file", "found": len(manual),
                       "kept": len(kept_manual), "error": manual_err})
        print(f"  {'Hand-entered':32} {len(kept_manual):4} events"
              + (f"  ⚠️ {manual_err}" if manual_err else ""))

    events = sorted(dedupe(all_events), key=lambda e: e.start)

    # Refuse to publish a collapse.
    #
    # A run where the network is down, a proxy intercepts, or DNS fails looks
    # exactly like a run where every venue genuinely has nothing on: sources
    # "succeed", return nothing, and the emitter cheerfully writes an empty
    # calendar. On a cron that pushes automatically, that empties the calendar
    # of every subscriber -- the single worst outcome this project can produce,
    # and far worse than being a few hours stale.
    #
    # So: a sharp drop is treated as broken infrastructure, not as news. Bail
    # without writing anything and exit non-zero so cron surfaces it. --force
    # overrides, for the genuine case where sources were removed on purpose.
    prev_path = DATA / "events.json"
    if prev_path.exists() and "--force" not in sys.argv:
        try:
            prev_n = len(json.loads(prev_path.read_text(encoding="utf-8")))
        except Exception:
            prev_n = 0
        if prev_n >= 20 and len(events) < prev_n * 0.4:
            print(f"\nABORT: {len(events)} events, down from {prev_n} "
                  f"(<40%). Refusing to overwrite.")
            failed = [h for h in health if h["error"]]
            for h in failed[:10]:
                print(f"  {h['name'][:32]:32} {h['error'][:70]}")
            print("\nNothing was written. Investigate, then re-run "
                  "(--force to publish anyway).")
            return 1

    PUBLIC.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    (DATA / "events.json").write_text(
        json.dumps([asdict(e) for e in events], indent=2, ensure_ascii=False),
        encoding="utf-8")

    # A venue with a nightly recurring show (The Tiny Cupboard: 141 of 268
    # events from 14 distinct titles) would otherwise dominate the one feed
    # meant to represent all 30+ orgs. Capped here, in the shared feed only --
    # data/events.json and every per-category feed stay complete, and a fan of
    # that one venue is better served by its own site than a shared calendar.
    PER_SOURCE_CAP = 20
    from collections import defaultdict
    counts = defaultdict(int)
    shared = []
    for e in events:               # already sorted by start, so this keeps the soonest
        counts[e.source_id] += 1
        if counts[e.source_id] <= PER_SOURCE_CAP:
            shared.append(e)
    (PUBLIC / "calendar.ics").write_text(
        to_ics(shared, "Brooklyn Events"), encoding="utf-8")

    cats = {c for e in events for c in e.categories}
    for cat in sorted(cats):
        subset = [e for e in events if cat in e.categories]
        slug = re.sub(r"[^a-z0-9]+", "-", cat.lower()).strip("-")
        (PUBLIC / f"{slug}.ics").write_text(
            to_ics(subset, f"Brooklyn Events — {cat}"), encoding="utf-8")

    ok = sum(1 for h in health if not h["error"])
    lines = ["# Source health", "",
             f"Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · "
             f"{ok}/{len(health)} sources OK · {len(events)} events", "",
             "| Source | Strategy | Events | Status |", "|---|---|---:|---|"]
    for h in sorted(health, key=lambda x: (bool(x["error"]), -x["kept"])):
        status = f"⚠️ {h['error'][:60]}" if h["error"] else (
            "✅" if h["kept"] else "⚠️ returned nothing")
        if h.get("method"):
            status += f" ({h['method']})"
        lines.append(f"| {h['name']} | `{h['strategy']}` | {h['kept']} | {status} |")
    (DOCS / "health.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n{len(events)} events from {ok}/{len(health)} sources"
          f" -> public/calendar.ics (+{len(cats)} category feeds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
