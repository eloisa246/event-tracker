#!/usr/bin/env python3
"""Turn discovery results into a draft config/sources.yaml.

Discovery says how each org's events can be reached; this writes that out in
the shape the build pipeline consumes. Orgs that still need hand-written
selectors or a browser are written out commented, so they're visible and easy
to enable once someone does the work rather than silently dropped.

Never overwrites an existing sources.yaml without --force: once a human has
corrected a strategy by hand, a rerun of discovery must not undo it.
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, CONFIG = ROOT / "data", ROOT / "config"

# Discovery method -> build adapter.
#
# Resident Advisor, See Tickets, Withfriends and Bandsintown are deliberately
# absent. Each 403'd or returned nothing for every org that tried it, and
# their adapters have been removed from build_calendar.py. Leaving them mapped
# here would regenerate config pointing at strategies that no longer exist.
# Unmapped methods fall into the commented "needs work" section instead, which
# is the honest place for them -- see docs/PLAYBOOK.md for what to try.
STRATEGY = {
    "calendar-feed": "ical",
    "ics-in-page": "ical",
    "google-calendar-embed": "google_calendar",
    "the-events-calendar-rest": "tribe_events",
    "schema.org-events": "jsonld",
    "eventbrite-linked": "eventbrite_organizer",
    "eventbrite-fallback": "eventbrite_organizer",
    "eventbrite-curated": "eventbrite_organizer",
    "dice-linked": "dice",
    "dice-fallback": "dice",
    "dice-curated": "dice",
    "luma-linked": "ical",
    "luma-curated": "ical",
}


def _check_strategies_exist():
    """Fail loudly if this file names a strategy the builder can't run.

    These two files drifted apart once already: adapters were deleted for
    never working while the mappings that produced them stayed behind, which
    would quietly emit config the build cannot execute.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from build_calendar import ADAPTERS
    except Exception as e:                 # missing deps shouldn't block the run
        print(f"  (skipped adapter cross-check: {type(e).__name__})")
        return
    unknown = sorted(set(STRATEGY.values()) - set(ADAPTERS))
    if unknown:
        raise SystemExit(
            f"STRATEGY maps to strategies with no adapter in build_calendar.py: "
            f"{unknown}. Either add the adapter or drop the mapping.")

BUILDABLE = {"0-feed", "1-platform", "2-jsonld"}


def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def q(s):
    """Quote a YAML scalar safely enough for the values we emit."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing sources.yaml")
    ap.add_argument("--merge", action="store_true",
                    help="append newly discovered sources, leaving existing "
                         "entries exactly as they are")
    args = ap.parse_args()

    disc_path = DATA / "discovery.json"
    if not disc_path.exists():
        print("data/discovery.json not found — run discovery first.")
        return 1
    _check_strategies_exist()
    results = json.loads(disc_path.read_text(encoding="utf-8"))["results"]

    out_path = CONFIG / "sources.yaml"

    # Merge is the mode that matters once the config has been touched by a
    # human. Nearly every live source carries a correction discovery could not
    # have made -- a venue's own calendar chosen over its ticketing page, a
    # strategy swapped after a real failure -- and regenerating would silently
    # revert all of it. Merge only ever appends orgs not already present.
    if args.merge and out_path.exists():
        import yaml
        existing_text = out_path.read_text(encoding="utf-8")
        cfg = yaml.safe_load(existing_text) or {}
        current = cfg.get("sources") or []
        have = {s.get("id") for s in current}
        # Parked orgs are deliberate decisions, most of them expensive to
        # reach -- a confirmed Cloudflare block, a recurring market that isn't
        # discrete events, a duplicate of another org's listing. They were
        # recorded only in YAML comments at first, which no script can read,
        # and the very first merge re-added two of them.
        parked = {p.get("id") for p in (cfg.get("parked") or [])}
        have |= parked
        added, skipped = [], []
        for r in results:
            strategy = STRATEGY.get(r.get("method") or "")
            if r.get("tier") not in BUILDABLE or not strategy:
                continue
            sid = slugify(r["name"])
            if sid in parked:
                skipped.append(r["name"])
                continue
            if sid in have:
                continue
            current.append({
                "id": sid, "name": r["name"], "strategy": strategy,
                "feed_url": r.get("feed_url") or r.get("events_url")
                            or r.get("website") or "",
                "categories": [],
            })
            have.add(sid)
            added.append((r["name"], strategy))
        cfg["sources"] = current
        header = existing_text.split("defaults:")[0]
        out_path.write_text(
            header + "\n" + yaml.safe_dump(cfg, sort_keys=False,
                                           allow_unicode=True, width=100),
            encoding="utf-8")
        print(f"merged {len(added)} new sources ({len(current)} total)")
        if skipped:
            print(f"  skipped {len(skipped)} parked: {', '.join(skipped)}")
        for name, s in sorted(added, key=lambda x: x[1]):
            print(f"    {s:22} {name}")
        return 0

    if out_path.exists() and not args.force:
        print(f"{out_path.relative_to(ROOT)} already exists — refusing to "
              f"overwrite hand-corrected config. Use --merge to append new "
              f"sources, or --force to regenerate and lose hand corrections.")
        return 1

    ready, needs_work = [], []
    for r in results:
        strategy = STRATEGY.get(r.get("method") or "")
        if r.get("tier") in BUILDABLE and strategy:
            ready.append((r, strategy))
        else:
            needs_work.append(r)

    lines = [
        "# Sources the calendar builds from.",
        "#",
        "# Generated by scripts/make_sources.py from data/discovery.json, then",
        "# corrected by hand. Discovery guesses; this file is the decision.",
        "#",
        f"# {len(ready)} sources active, {len(needs_work)} still need work "
        "(listed commented out at the bottom).",
        "",
        "defaults:",
        "  timezone: America/New_York",
        "  window_days: 180",
        "",
        "sources:",
    ]
    for r, strategy in sorted(ready, key=lambda x: x[0]["name"]):
        lines.append(f"  - id: {slugify(r['name'])}")
        lines.append(f"    name: {q(r['name'])}")
        lines.append(f"    strategy: {strategy}")
        if r.get("feed_url"):
            lines.append(f"    feed_url: {q(r['feed_url'])}")
        elif r.get("events_url") or r.get("website"):
            lines.append(f"    feed_url: {q(r.get('events_url') or r['website'])}")
        if r.get("platforms"):
            lines.append(f"    # seen on: {', '.join(r['platforms'])}")
        lines.append("    categories: []")
        lines.append("")

    if needs_work:
        lines += [
            "# " + "-" * 68,
            "# NOT YET BUILDING. Each of these needs either CSS selectors or a",
            "# browser render. Uncomment and fill in once that work is done.",
            "# " + "-" * 68,
        ]
        for r in sorted(needs_work, key=lambda x: x["name"]):
            url = r.get("feed_url") or r.get("events_url") or r.get("website") or ""
            lines += [
                f"#  - id: {slugify(r['name'])}",
                f"#    name: {q(r['name'])}",
                f"#    strategy: css        # tier {r.get('tier')} — {r.get('method')}",
                f"#    url: {q(url)}",
                "#    selectors:",
                '#      item:  ""',
                '#      title: ""',
                '#      date:  ""',
                '#      url:   ""',
                "",
            ]

    CONFIG.mkdir(exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_path.relative_to(ROOT)}")
    print(f"  {len(ready)} sources ready to build")
    print(f"  {len(needs_work)} need selectors or a browser")
    for r, s in sorted(ready, key=lambda x: x[1]):
        print(f"    {s:22} {r['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
