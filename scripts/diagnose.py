#!/usr/bin/env python3
"""Render a source and dump exactly what it serves, unfiltered.

build_calendar.py's browser adapter only keeps responses that already look
like events. That's right for production, but it means a source returning
zero tells you nothing about *why*. This is the manual-inspection step: render
the page, record every response the browser made (not just the JSON ones,
not just the ones that matched an event shape), and write it out so a human
can look at what's actually there -- the same way Bandsintown's REST API and
Squarespace's ?format=json were found, by looking rather than guessing.

Usage: python scripts/diagnose.py [source-id ...]
  No arguments: every source currently at 0 events in the latest health data.

Writes data/diagnostics/<id>.json (full) and docs/diagnostics.md (readable).
Not part of the build; run by hand via the diagnose workflow when a source
needs real investigation.
"""
import json, re, sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
DIAG_DIR = ROOT / "data" / "diagnostics"

UA = ("brooklyn-event-calendar/0.1 (+https://github.com/"
      "eloisa246/event-tracker) events-aggregator")
MAX_BODY = 6000          # chars kept per JSON body -- enough to see the shape
MAX_RESPONSES = 80


def zero_sources():
    disc = ROOT / "data" / "discovery.json"
    events = ROOT / "data" / "events.json"
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
    ids = [s["id"] for s in cfg["sources"]]
    if not events.exists():
        return ids
    have = {e["source_id"] for e in json.loads(events.read_text())}
    return [i for i in ids if i not in have]


SCRIPT_JSON = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>\s*(\{.*?\}|\[.*?\])\s*</script>',
                         re.S | re.I)


def embedded_script_json(html, min_len=500, limit=5):
    """Script tags whose content is substantial JSON, not a tiny config blob.

    SSR frameworks (Next.js __NEXT_DATA__, Nuxt __NUXT__, and plenty of
    unlabelled equivalents) bake the page's data straight into the HTML
    instead of fetching it client-side, which is invisible to network
    capture. This is the same signal, read from the markup instead.
    """
    out = []
    for m in SCRIPT_JSON.finditer(html):
        blob = m.group(1)
        if len(blob) < min_len:
            continue
        try:
            json.loads(blob)
        except Exception:
            continue                      # not actually valid JSON
        out.append({"length": len(blob), "preview": blob[:MAX_BODY]})
        if len(out) >= limit:
            break
    return out


def org_context(body, term, window=500, limit=3):
    """Snippets of `body` around each mention of `term`, first `limit` only.

    Works on any body/term pair, not just an org's own name in a JSON payload
    -- also used to find third-party "Add to Calendar" widget markup
    (AddEvent, Add to Calendar Button) in the raw HTML once a page is known
    to contact one of those domains. Those widgets commonly embed each
    event's title/date/location as HTML attributes or nested spans right on
    the button, invisible to every JSON-based check here.
    """
    if not term or len(term) < 4:
        return []
    out, pos = [], 0
    low, low_term = body.lower(), term.lower()
    for _ in range(limit):
        i = low.find(low_term, pos)
        if i < 0:
            break
        out.append(body[max(0, i - window // 2): i + window // 2])
        pos = i + len(term)
    return out


def diagnose_one(src, mobile=False):
    from playwright.sync_api import sync_playwright
    url = src["feed_url"]
    result = {"id": src["id"], "name": src["name"], "url": url,
             "responses": [], "hosts": set(), "html_title": "",
             "html_len": 0, "calendar_ish_classes": [], "error": ""}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"])
        try:
            # Imported from the builder, never redefined here -- see the note
            # on BROWSER_CONTEXT. A diagnostic that renders differently from
            # the build describes a page the build never sees.
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from build_calendar import BROWSER_CONTEXT

            if mobile:
                # A resized desktop window is not the same thing as a phone --
                # some sites pick an entirely different embedded widget based
                # on the request's own device signals, not just viewport
                # width, so viewport alone can miss it. Playwright's device
                # profile matches viewport, user agent and touch support the
                # way a real phone actually presents.
                profile = pw.devices["iPhone 13"]
                page = browser.new_page(locale=BROWSER_CONTEXT["locale"],
                                        timezone_id=BROWSER_CONTEXT["timezone_id"],
                                        **profile)
            else:
                page = browser.new_page(**BROWSER_CONTEXT)

            def on_response(resp):
                if len(result["responses"]) >= MAX_RESPONSES:
                    return
                try:
                    ct = (resp.headers or {}).get("content-type", "")
                    host = urlparse(resp.url).netloc
                    result["hosts"].add(host)
                    entry = {"url": resp.url[:300], "status": resp.status,
                             "content_type": ct[:80]}
                    if "json" in ct.lower():
                        try:
                            body = resp.text()
                            entry["json_preview"] = body[:MAX_BODY]
                            entry["json_len"] = len(body)
                            # A payload can be large enough that the org's own
                            # data is well past the preview window (Ridgewood
                            # Commons: 1MB). Show what surrounds each mention
                            # of the org's own name instead of only the start.
                            mentions = org_context(body, src["name"])
                            if mentions:
                                entry["org_name_context"] = mentions
                        except Exception:
                            pass
                    result["responses"].append(entry)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(2000)
            html = page.content()
            result["html_title"] = page.title()
            result["html_len"] = len(html)
            # class/id names mentioning event/calendar -- points at the widget
            # even when no network request or schema.org gives it away.
            hits = re.findall(
                r'(?:class|id)=["\']([^"\']*(?:event|calendar|show|listing|'
                r'schedule)[^"\']*)["\']', html, re.I)
            result["calendar_ish_classes"] = sorted(set(hits))[:20]
            # third-party embeds are a common answer: an <iframe src=...>
            iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
            result["iframes"] = iframes[:10]
            # A site with zero network JSON but a calendar widget on the page
            # (Abrons: contacts cdn.sanity.io yet shows no JSON response) is
            # likely server-rendering its data straight into a <script> block
            # rather than fetching it client-side. Surface any script tag
            # whose content looks like real JSON, not just tiny config blobs.
            result["embedded_script_json"] = embedded_script_json(html)
            # FullCalendar and similar widgets often embed their event data as
            # a plain JS array literal inside the init call (events: [...]),
            # which is not standalone JSON and so embedded_script_json()
            # correctly declines to parse it as such. For a page small enough
            # that this is cheap, keep every <script> body verbatim so a human
            # can read the real init code instead of guessing at another
            # regex for a shape that hasn't been seen yet.
            # 120kb covers a typical WordPress event page. The previous 60kb
            # ceiling silently skipped a 68kb page that was the whole point of
            # the run, and a skipped capture looks identical to a page with no
            # scripts in the output.
            if len(html) < 120000:
                result["all_script_bodies"] = [
                    s[:4000] for s in re.findall(
                        r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S | re.I)
                    if len(s.strip()) > 40]
            # A third-party "Add to Calendar" widget's own domain shows up in
            # hosts contacted well before any of the above would catch it --
            # its event data usually lives as HTML attributes on the button,
            # not a script tag or a network response.
            #
            # Picking this marker took two wrong guesses, both instructive:
            #   "addevent"    -- matched the widget's own CSS (many url()
            #                    references to its CDN) and burned the match
            #                    limit on boilerplate before reaching a button.
            #   "data-start=" -- looked event-specific but collides with
            #                    character-offset attributes some content
            #                    editors put on every <p> tag, so it matched
            #                    three paragraphs of body copy instead.
            # The button's class attribute is the only unambiguous form: CSS
            # writes the selector dot-prefixed (.addeventatc) while HTML writes
            # it quote-prefixed (class="addeventatc"), so leading with the
            # quote skips the stylesheet entirely.
            for widget, marker in (("addevent", '"addeventatc'),
                                   ("addtocalendar", "atc_event")):
                if any(widget in h for h in result["hosts"]):
                    ctx = org_context(html, marker, window=800, limit=8)
                    if ctx:
                        result.setdefault("widget_markup", {})[widget] = ctx
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
        finally:
            browser.close()

    result["hosts"] = sorted(result["hosts"])
    return result


def main():
    args = sys.argv[1:]
    mobile = "--mobile" in args
    if mobile:
        args = [a for a in args if a != "--mobile"]
    # --url lets a one-off address be checked directly -- e.g. a WordPress REST
    # discovery root -- without inventing a fake config/sources.yaml entry.
    if args and args[0] == "--url":
        url = args[1]
        name = args[2] if len(args) > 2 else url
        targets = [{"id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                   "name": name, "feed_url": url}]
    else:
        ids = args or zero_sources()
        cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
        by_id = {s["id"]: s for s in cfg["sources"]}
        targets = [by_id[i] for i in ids if i in by_id]
        missing = [i for i in ids if i not in by_id]
        if missing:
            print(f"not in config/sources.yaml, skipping: {missing}")
    if not targets:
        print("nothing to diagnose")
        return 0

    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    md = ["# Source diagnostics", "",
         "Unfiltered network capture for sources that need manual "
         "investigation. Not part of the build.", ""]

    for src in targets:
        print(f"diagnosing {src['name']} ({src['feed_url']})"
              f"{' [mobile]' if mobile else ''} ...", flush=True)
        r = diagnose_one(src, mobile=mobile)
        suffix = "-mobile" if mobile else ""
        (DIAG_DIR / f"{src['id']}{suffix}.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

        md += [f"## {r['name']}", "", f"`{r['url']}`", "",
              f"- title: {r['html_title']!r}",
              f"- html: {r['html_len']//1024}kb",
              f"- hosts contacted: {', '.join(r['hosts'][:15])}",
              f"- error: {r['error'] or 'none'}", ""]
        json_resps = [x for x in r["responses"] if "json_preview" in x]
        md.append(f"**{len(r['responses'])} responses total, "
                  f"{len(json_resps)} JSON**")
        if json_resps:
            md.append("")
            for x in json_resps[:10]:
                md.append(f"- `{x['url']}` ({x['json_len']} bytes)")
                for ctx in x.get("org_name_context", []):
                    md.append(f"  - org name found nearby: `...{ctx}...`")
        if r["iframes"]:
            md += ["", "**iframes:**"] + [f"- `{f}`" for f in r["iframes"]]
        if r["calendar_ish_classes"]:
            md += ["", "**calendar/event-ish class names in the DOM:**"]
            md += [f"- `{c}`" for c in r["calendar_ish_classes"][:12]]
        if r.get("embedded_script_json"):
            md += ["", "**JSON embedded directly in <script> tags "
                       "(no network request needed to see it):**"]
            for s in r["embedded_script_json"]:
                md.append(f"- {s['length']} bytes: `{s['preview'][:200]}...`")
        if r.get("all_script_bodies"):
            md += ["", f"**every <script> body verbatim (page is small: "
                       f"{r['html_len']//1024}kb) -- see the full JSON file "
                       f"for complete text:**"]
            for i, s in enumerate(r["all_script_bodies"][:8]):
                md.append(f"- script {i}: `{s[:200]}...`" if len(s) > 200
                          else f"- script {i}: `{s}`")
        if r.get("widget_markup"):
            for widget, snippets in r["widget_markup"].items():
                md += ["", f"**raw markup around \"{widget}\" mentions "
                           f"({len(snippets)} found):**"]
                for s in snippets:
                    md.append(f"- `{s}`")
        md.append("")
        n_embedded = len(r.get("embedded_script_json") or [])
        print(f"  {len(r['responses'])} responses, {len(json_resps)} JSON, "
              f"{len(r['hosts'])} hosts, {len(r['iframes'])} iframes, "
              f"{n_embedded} embedded script JSON blocks")

    (ROOT / "docs" / "diagnostics.md").write_text("\n".join(md) + "\n",
                                                   encoding="utf-8")
    print(f"\nwrote data/diagnostics/*.json and docs/diagnostics.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
