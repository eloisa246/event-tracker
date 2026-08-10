#!/usr/bin/env python3
"""Find each org's website by generating candidate domains and testing them.

The spreadsheet gives Instagram handles, not websites, and a website is what
discovery needs. Searching for 209 orgs by hand is the obvious approach and
the wrong one: it is slow, and it was already done for the first 34.

Most small venues own the domain matching their own name or handle
(@babysallright -> babysallright.com), so candidates can be generated and
tested directly. A request to a candidate domain is cheap; a human search is
not. What can't be guessed falls back to a human, with a much shorter list.

The verification step is the part that matters. A domain resolving proves
nothing -- parked domains, squatters and unrelated businesses all return 200.
A candidate is only accepted when the page itself identifies the org.

Usage:  python scripts/find_websites.py [--limit N] [--min-score N]
Writes data/website_candidates.csv for review; never edits websites.csv
directly, since a wrong domain silently poisons a source.
"""
import argparse, csv, json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

UA = ("brooklyn-event-calendar/0.1 (+https://github.com/"
      "9dpzmbpyym-crypto/Event-Calender) events-aggregator Mozilla/5.0")
# .club earns its place: Elsewhere is elsewhere.club, and a .com-only list
# would have missed one of the largest venues on the list outright.
TLDS = (".com", ".org", ".nyc", ".club", ".co", ".net")
MAX_CANDIDATES = 12
WORKERS = 8
TIMEOUT = 12

_last_hit, _lock = {}, threading.Lock()


def polite_get(client, url):
    """One request per host per second; candidates are all different hosts."""
    host = urlparse(url).netloc
    with _lock:
        wait = 1.0 - (time.monotonic() - _last_hit.get(host, 0))
        _last_hit[host] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)
    return client.get(url)


def norm(s):
    """Lowercase alphanumerics only -- for comparing names to page text."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def candidates(org):
    """Domains this org plausibly owns, most likely first.

    The Instagram handle leads because it is the org's own chosen identifier
    and matched the domain for most of the first 34 (@babysallright ->
    babysallright.com). Name-derived spellings follow.
    """
    seeds, seen = [], set()

    handle = (org.get("instagram_handle") or "").lstrip("@").strip().lower()
    # a handle like "cafeconlibros_bk" also suggests "cafeconlibros"
    if handle:
        seeds.append(re.sub(r"[^a-z0-9]", "", handle))
        base = re.split(r"[._]", handle)[0]
        if len(base) >= 5:
            seeds.append(re.sub(r"[^a-z0-9]", "", base))

    name = org.get("name") or ""
    flat = re.sub(r"[^a-z0-9]", "", name.lower())
    dashed = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")
    seeds += [flat, dashed]
    # drop a leading "the", which venues usually omit from their domain
    if name.lower().startswith("the "):
        seeds.append(re.sub(r"[^a-z0-9]", "", name[4:].lower()))

    clean = []
    for seed in seeds:
        if seed and len(seed) >= 4 and seed not in seen:
            seen.add(seed)
            clean.append(seed)

    # Breadth-first across TLDs, not depth-first per seed: every seed's .com
    # is tried before any seed's .nyc, because the TLD is far more predictive
    # than the spelling. Depth-first spent the candidate budget on
    # <handle>.nyc and <handle>.co before ever reaching <name>.com.
    out = []
    for tld in TLDS:
        for seed in clean:
            out.append(f"https://{seed}{tld}")
            if len(out) >= MAX_CANDIDATES:
                return out
    return out


TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
PARKED = re.compile(
    r"domain (is )?(for sale|may be for sale|parked)|buy this domain|"
    r"godaddy|namecheap|sedo\.com|hugedomains|this domain is available|"
    r"under construction|coming soon", re.I)


# Every org on this list is in or around New York. A page with the right name
# and no New York connection anywhere is a different organisation with the
# same name -- which is the single most common false positive:
#   The Ten Bells   -> the East London pub, not the Lower East Side bar
#   Sunrise/Sunset  -> a sunrise-time almanac site, not the Brooklyn bar
#   Happy Medium    -> a consultancy, not the Brooklyn games cafe
# All three matched their name in <title> perfectly.
LOCALITY = re.compile(
    r"\bbrooklyn\b|\bnew york\b|\bnyc\b|\bmanhattan\b|\bqueens\b|\bbronx\b|"
    r"\bstaten island\b|\bbushwick\b|\bridgewood\b|\bwilliamsburg\b|"
    r"\bgreenpoint\b|\bbed[- ]?stuy\b|\bcrown heights\b|\bpark slope\b|"
    r"\bgowanus\b|\bflatbush\b|\bred hook\b|\bastoria\b|"
    # A zip only counts next to "NY". A bare 1[01]\d{3} matches any number
    # from 10000-11999, which inline JS config and CSS pixel values are full
    # of -- it matched "10800" in a script tag on a London pub's site and
    # certified it as a New York organisation.
    r"\bN\.?Y\.?\s*,?\s*1[01]\d{3}\b", re.I)

# Locality is judged on visible text only. Scripts and stylesheets are dense
# with numbers and foreign words and produce matches that mean nothing.
SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)


def visible_text(html):
    return re.sub(r"<[^>]+>", " ", SCRIPT_STYLE.sub(" ", html))


def verify(html, org):
    """Confidence that this page really belongs to this org.

    A resolving domain proves nothing: parked pages, squatters and unrelated
    businesses all answer 200. Two things together are what separate a real
    find from a plausible-looking wrong one -- the org's own name, and some
    evidence the page is about a New York organisation at all.
    """
    if PARKED.search(html[:4000]):
        return 0, "parked/for-sale page"
    title = TITLE.search(html)
    title_txt = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else ""
    name_n = norm(org["name"])
    handle_n = norm((org.get("instagram_handle") or "").lstrip("@"))
    body = html[:200000]
    body_n = norm(body)
    local = bool(LOCALITY.search(visible_text(body)))

    # A title that is just the domain is a placeholder, not a real site.
    if title_txt and norm(title_txt) == norm(urlparse_host(title_txt)):
        return 1, f"title is just the domain (placeholder?): {title_txt[:50]!r}"

    in_title = bool(name_n and name_n in norm(title_txt))
    in_body = bool(name_n and len(name_n) >= 6 and name_n in body_n)
    handle_in_body = bool(handle_n and len(handle_n) >= 6 and handle_n in body_n)

    if in_title and local:
        return 3, f"name in <title> + NY locality: {title_txt[:55]!r}"
    if in_title:
        return 2, f"name in <title> but NO New York signal: {title_txt[:45]!r}"
    if (in_body or handle_in_body) and local:
        return 2, "name/handle in body + NY locality"
    if in_body or handle_in_body:
        return 1, "name/handle in body, no New York signal"
    if title_txt:
        return 1, f"resolves but unconfirmed: {title_txt[:55]!r}"
    return 1, "resolves but unconfirmed"


def urlparse_host(text):
    """Return text unchanged unless it looks like a bare domain name."""
    return text if re.fullmatch(r"[\w.-]+\.[a-z]{2,}", text.strip(), re.I) else ""


def probe_org(org):
    headers = {"User-Agent": UA, "Accept": "text/html,*/*"}
    best = None
    with httpx.Client(headers=headers, timeout=TIMEOUT,
                      follow_redirects=True) as c:
        for url in candidates(org):
            try:
                r = polite_get(c, url)
            except Exception:
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                continue
            score, why = verify(r.text, org)
            final = str(r.url)
            if best is None or score > best["score"]:
                best = {"name": org["name"], "instagram": org.get("instagram_handle", ""),
                        "category": org.get("category", ""), "website": final,
                        "score": score, "evidence": why}
            if score >= 3:                      # confirmed, stop probing
                break
    if best is None:
        best = {"name": org["name"], "instagram": org.get("instagram_handle", ""),
                "category": org.get("category", ""), "website": "",
                "score": 0, "evidence": "no candidate domain resolved"}
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60,
                    help="how many orgs to probe this run")
    args = ap.parse_args()

    orgs = json.loads((DATA / "orgs.json").read_text(encoding="utf-8"))
    done = set()
    wpath = DATA / "websites.csv"
    if wpath.exists():
        done = {r["name"] for r in csv.DictReader(wpath.open(encoding="utf-8"))}
    prev = {}
    cpath = DATA / "website_candidates.csv"
    if cpath.exists():
        prev = {r["name"]: r for r in csv.DictReader(cpath.open(encoding="utf-8"))}

    todo = [o for o in orgs if o["name"] not in done and o["name"] not in prev]
    todo = todo[:args.limit]
    if not todo:
        print("nothing left to probe")
        return 0

    print(f"probing {len(todo)} orgs ({len(prev)} already probed, {len(done)} live)")
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, res in enumerate(pool.map(probe_org, todo), 1):
            results.append(res)
            mark = {3: "CONFIRMED", 2: "likely", 1: "weak", 0: "-"}[res["score"]]
            print(f"  [{i}/{len(todo)}] {mark:9} {res['name'][:32]:32} {res['website'][:52]}")

    rows = list(prev.values()) + results
    fields = ["name", "instagram", "category", "website", "score", "evidence"]
    with cpath.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    got = sum(1 for r in results if int(r["score"]) >= 2)
    print(f"\n{got}/{len(results)} confirmed or likely -> "
          f"data/website_candidates.csv")
    print("Review, then promote the good ones into data/websites.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
