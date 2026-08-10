#!/usr/bin/env python3
"""Pick the starter set of orgs to wire up first.

Ranks orgs by how likely they are to publish a real, recurring public events
calendar, then takes a spread across categories so the pilot exercises several
different source types rather than ten copies of the same one.

Writes data/shortlist.csv. Change TARGET or the weights and re-run.
"""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = 34
PER_CATEGORY_CAP = 6          # keeps one category from eating the shortlist

# Venues that obviously belong in the pilot but rank low only because their
# spreadsheet description is terse. Pinned so the wording of a blurb doesn't
# decide whether a major venue is included.
ALWAYS_INCLUDE = ["Elsewhere", "Nowadays", "Market Hotel", "Public Records"]

CATEGORY_WEIGHT = {
    "Music Venues & Education": 10,
    "Events Boards & Bulletins": 9,
    "Literary & Book Communities": 8,
    "Games & Game Nights": 8,
    "Creative Collectives & Communities": 7,
    "Arts, Music & Creative Classes": 7,
    "Bars & Third Places": 6,
    "LGBTQ+ & Identity-Based Groups": 6,
    "Political & Social Justice Orgs": 6,
    "Outdoor & Wellness Communities": 5,
    "Mutual Aid & Volunteering": 5,
    "Social Clubs": 4,
    "Animal Welfare & Rescue": 3,
    "Shopping & Local Retail": 2,
}
# words that signal "this place runs scheduled public events"
SIGNALS = re.compile(
    r"live (music|show|band)|shows?\b|djs?\b|dance part|nightlife|comedy|"
    r"open mic|readings?\b|book club|screenings?|film|workshops?|classes|"
    r"performances?|concerts?|game night|trivia|karaoke|market|pop-?up|"
    r"exhibitions?|talks?|panels?|meetups?|events?\b", re.I)

def score(o):
    s = CATEGORY_WEIGHT.get(o["category"], 3)
    text = f"{o['engagement']} {o['description']} {o['notes']} {o['subcategory']}"
    s += min(len(SIGNALS.findall(text)), 6) * 2      # capped so one field can't dominate
    if o["instagram_handle"]:
        s += 1                                       # we have a lead to work from
    if o["address"]:
        s += 1                                       # a physical venue with a schedule
    return s

def main():
    orgs = json.loads((ROOT / "data" / "orgs.json").read_text(encoding="utf-8"))
    ranked = sorted(orgs, key=score, reverse=True)

    picked, per_cat = [], {}
    pinned = {n.lower() for n in ALWAYS_INCLUDE}
    for o in ranked:
        if o["name"].lower() in pinned:
            picked.append(o)
            per_cat[o["category"]] = per_cat.get(o["category"], 0) + 1
    for o in ranked:
        if o["name"].lower() in pinned:
            continue
        if len(picked) >= TARGET:
            break
        c = o["category"]
        if per_cat.get(c, 0) >= PER_CATEGORY_CAP:
            continue
        per_cat[c] = per_cat.get(c, 0) + 1
        picked.append(o)

    fields = ["name", "instagram_handle", "category", "engagement", "address", "website"]
    out = ROOT / "data" / "shortlist.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for o in picked:
            w.writerow({k: o.get(k, "") for k in fields})

    print(f"{len(picked)} orgs -> data/shortlist.csv\n")
    for c, n in sorted(per_cat.items(), key=lambda x: -x[1]):
        print(f"  {n:3}  {c}")
    print()
    for o in picked:
        print(f"  {o['name'][:30]:30} {o['instagram_handle'][:24]:24} {o['category'][:30]}")

if __name__ == "__main__":
    main()
