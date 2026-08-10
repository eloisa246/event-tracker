#!/usr/bin/env python3
"""Turn whatever is in inbox/ into one clean org list.

Reads the org spreadsheet(s) and any pasted guide markdown, normalizes the
columns, merges duplicates, and writes data/orgs.csv + data/orgs.json.

Inputs are never modified. Re-run any time inbox/ changes.
"""
import csv, json, re, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX, DATA = ROOT / "inbox", ROOT / "data"

def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")

def clean(v):
    return "" if v is None else str(v).strip()

# Trailing words that decorate a name without changing which place it is, so
# "Rough Trade NYC" and "Rough Trade" collapse to one record.
NAME_SUFFIXES = {"nyc", "ny", "bk", "brooklyn", "newyork", "shop", "store",
                 "cafe", "coffee", "bar", "studio", "cinema", "bookstore",
                 "theater", "theatre", "inc", "llc"}

def canonical_name(s):
    """Aggressively normalized key for spotting the same place named two ways."""
    s = s.replace("’", "'").replace("‘", "'").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\bnew york\b", "newyork", s)
    s = re.sub(r"\bn\b", "and", s)              # "Bread N Wine" -> "Bread And Wine"
    words = re.sub(r"[^a-z0-9\s]", " ", s).split()
    while len(words) > 1 and words[-1] in NAME_SUFFIXES:
        words.pop()
    return "".join(words)

def norm_handle(h):
    h = clean(h).lstrip("@").strip()
    return f"@{h}" if h else ""

def ig_url(h):
    return f"https://www.instagram.com/{h.lstrip('@')}/" if h else ""

# ---------- spreadsheets ----------
def read_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        # header = first row containing a cell equal to "name"
        hi = next((i for i, r in enumerate(rows)
                   if any(clean(c).lower() == "name" for c in r)), 0)
        hdr = [clean(c).lower() for c in rows[hi]]
        for r in rows[hi + 1:]:
            rec = {hdr[i]: clean(v) for i, v in enumerate(r) if i < len(hdr) and hdr[i]}
            if rec.get("name"):
                rec["_sheet"] = ws.title
                out.append(rec)
    return out

def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.lower().strip(): clean(v) for k, v in row.items() if k}
                for row in csv.DictReader(f)]

# ---------- pasted guides ----------
COMMENT_BLOCK = re.compile(r"<!--.*?-->", re.S)      # instructions live in here
SENTINEL = re.compile(r"^PASTE BELOW THIS LINE\s*$", re.I | re.M)

ADDRESS = re.compile(
    r"^\d+[\w-]*\s+\S|"                                    # "486 Halsey St", "56-06 Cooper Ave"
    r"\b(st|street|ave|avenue|rd|road|blvd|pl|place|ct|ln|lane|way|"
    r"pkwy|plaza|sq|square|broadway|bowery)\b\.?,?\s*$|"    # ends in a street type
    r"\b(brooklyn|queens|manhattan|bronx|nyc|ny)\b\s*,?\s*(\d{5})?\s*$",  # ends in a borough
    re.I)
# leading emoji / bullets / decoration before a name
DECOR = re.compile(r"^[^\w(\[]+", re.UNICODE)
# inline separators: " · ", " — ", " | ", " - ", or 2+ spaces
INLINE_SPLIT = re.compile(r"\s+[·—–|]\s+|\s+-\s+|\s{2,}")

def looks_like_prose(name):
    """Guide lines are place names. Sentences are leftover template text."""
    return len(name) > 70 or name.endswith((".", ":")) or name.count(" ") > 9

def parse_guide_block(lines, section, src):
    """A block is one place: first line is the name, the rest are address/notes.

    Handles both shapes people actually paste:
        Human Relations              |  Bar Lunatico · 486 Halsey St · live music
        1067 Flushing Ave, Brooklyn  |
        does poetry readings         |
    """
    head = DECOR.sub("", lines[0].strip())
    parts = [p.strip(" ,·—–|") for p in INLINE_SPLIT.split(head) if p.strip(" ,·—–|")]
    if not parts:
        return None
    name, rest = parts[0], parts[1:]

    address, notes = "", []
    for chunk in rest + [DECOR.sub("", l.strip()) for l in lines[1:]]:
        if not chunk:
            continue
        if not address and ADDRESS.search(chunk):
            address = chunk
        else:
            notes.append(chunk)

    if len(name) < 2 or name.lower() in {"guide", "name"} or looks_like_prose(name):
        return None
    return {"name": name, "address": address, "notes": " · ".join(notes),
            "grouped category": section, "_source_file": src}

# ---------- Apple Maps app paste ----------
# Copying a guide out of the Maps app yields repeating blocks of:
#     Name / Place type / [$$] / [Open|Closed Now] / [hours] / [address]
# Blank lines between places are common but NOT reliable, so the parser keys off
# line *kind* instead: metadata attaches to the current place, and the next
# plain-text line after a place already has a name and type starts a new one.
MAPS_HOURS = re.compile(
    r"\d{1,2}:\d{2}\s*(AM|PM)?\s*[–—-]\s*\d{1,2}:\d{2}\s*(AM|PM)|open\s*24\s*hours", re.I)
# Apple Maps uses a closed vocabulary here. Match it exactly rather than by
# prefix — a loose pattern eats real venue names ("Open Sesame"), and one
# missed status silently shifts every place after it by one line.
MAPS_STATUS = re.compile(
    r"^(open|open now|open 24 hours|closed|closed now|closed today|"
    r"closing soon|opening soon|temporarily closed|permanently closed)$"
    r"|^(opens|closes)\s+(at\s+)?\d", re.I)
MAPS_PRICE = re.compile(r"^\$+$")
# A street address must start with a number AND name a street type. Requiring
# only the leading number misreads venues like "1804 Books" as an address,
# which silently shifts every place after it.
MAPS_ADDRESS = re.compile(
    r"^\d+[\w-]*\s+.*\b(st|street|ave|avenue|rd|road|blvd|boulevard|pl|place|"
    r"ct|ln|lane|way|pkwy|parkway|plaza|sq|square|broadway|bowery|dr|drive|"
    r"ter|terrace)\b\.?,?\s*$", re.I)

def _maps_kind(s):
    if MAPS_PRICE.match(s):        return "price"
    if MAPS_HOURS.search(s):       return "hours"
    if MAPS_STATUS.match(s):       return "status"
    if MAPS_ADDRESS.match(s):      return "address"
    return "text"

def looks_like_maps_paste(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 10:
        return False
    meta = sum(1 for l in lines if _maps_kind(l) in ("hours", "status", "price"))
    return meta / len(lines) > 0.25

def find_guide_titles(lines):
    """One pasted file can hold several guides, each introduced by its title.

    A title is a lowercase line standing alone between blank lines. Place names
    are followed immediately by their place type, so a lowercase venue like
    "curry leaf indian cuisine" is not mistaken for a title.
    """
    titles = {}
    for i, l in enumerate(lines):
        s = l.strip()
        if not s or not s.islower() or len(s.split()) < 2:
            continue
        before_blank = i == 0 or not lines[i - 1].strip()
        after_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
        if before_blank and after_blank:
            titles[i] = s
    return titles

def read_maps_paste(text, title, src):
    out, cur = [], None

    def flush():
        nonlocal cur
        if cur and cur["name"]:
            notes = [x for x in (cur["type"], cur["price"]) if x]
            out.append({"name": cur["name"], "address": cur["address"],
                        "notes": " · ".join(notes), "subcategory": cur["type"],
                        "grouped category": title, "_source_file": src})
        cur = None

    lines = text.splitlines()
    titles = find_guide_titles(lines)
    for idx, raw in enumerate(lines):
        if idx in titles:                  # a new guide starts here
            flush()
            title = titles[idx]
            continue
        s = DECOR.sub("", raw.strip())
        if not s:
            continue
        kind = _maps_kind(s)
        if kind == "text":
            if cur is None:
                cur = {"name": s, "type": "", "price": "", "address": ""}
            elif not cur["type"]:
                cur["type"] = s                    # line right after a name
            else:
                flush()                            # a new place begins
                cur = {"name": s, "type": "", "price": "", "address": ""}
        else:
            if cur is None:
                continue                           # stray metadata, no place yet
            if kind == "address" and not cur["address"]:
                cur["address"] = s
            elif kind == "price" and not cur["price"]:
                cur["price"] = s
            # hours/status are deliberately dropped — they go stale immediately
    flush()
    return out

def read_guides():
    out = []
    for p in sorted((INBOX / "guides").glob("*.md")):
        src = str(p.relative_to(ROOT))
        section = p.stem
        text = COMMENT_BLOCK.sub("", p.read_text(encoding="utf-8"))
        # only content after the sentinel is user-pasted data
        parts = SENTINEL.split(text)
        text = parts[-1] if len(parts) > 1 else text

        if looks_like_maps_paste(text):
            # titles are detected inline, so multiple guides in one file work
            out += read_maps_paste(text, p.stem, src)
            continue

        block = []
        def flush():
            if block:
                rec = parse_guide_block(block, section, src)
                if rec:
                    out.append(rec)
                block.clear()

        for line in text.splitlines():
            line = line.rstrip()
            if line.strip().startswith("##"):
                flush()
                section = line.strip().lstrip("#").strip() or p.stem
                continue
            if not line.strip() or line.strip().startswith((">", "|", "---", "===")):
                flush()
                continue

            stripped = DECOR.sub("", line.strip())
            # A line continues the previous place only if it is *nothing but* an
            # address. "Books Are Magic — 225 Smith St" also ends in a street
            # type, so require a bare address with no inline separator.
            is_bare_address = (stripped[:1].isdigit()
                               and bool(ADDRESS.search(stripped))
                               and not INLINE_SPLIT.search(stripped))
            # a lowercase line right after a name is a note ("does poetry readings")
            is_note = bool(block) and stripped[:1].islower()
            if block and not is_bare_address and not is_note:
                flush()                      # this line is a new place name
            block.append(line)
        flush()
    return out

# ---------- normalize + merge ----------
FIELDS = ["slug", "name", "instagram_handle", "instagram_url", "website",
          "description", "location", "engagement", "category", "subcategory",
          "address", "notes", "source_files", "tier", "feed_url", "feed_status"]

def normalize(rec, src):
    name = rec.get("name", "")
    if not name or name.lower().startswith("group:"):
        return None
    h = norm_handle(rec.get("instagram handle") or rec.get("instagram") or "")
    return {
        "slug": slugify(name),
        "name": name,
        "instagram_handle": h,
        "instagram_url": rec.get("instagram link") or ig_url(h),
        "website": rec.get("website link (adding soon!)") or rec.get("website") or "",
        "description": rec.get("description", ""),
        "location": rec.get("city/location", ""),
        "engagement": rec.get("type of engagement", ""),
        "category": rec.get("grouped category", ""),
        "subcategory": rec.get("subcategory", ""),
        "address": rec.get("address", ""),
        "notes": rec.get("notes", ""),
        "source_files": src,
        "tier": "",          # filled by discovery
        "feed_url": "",
        "feed_status": "unknown",
    }

def load_aliases():
    """config/aliases.yaml: hand-declared same/not-same name pairs."""
    f = ROOT / "config" / "aliases.yaml"
    if not f.exists():
        return {}
    import yaml
    doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    alias = {}
    for group in doc.get("same") or []:
        primary = group[0]
        for other in group[1:]:
            alias[canonical_name(other)] = canonical_name(primary)
    return alias

def main():
    aliases = load_aliases()
    raw = []
    for p in sorted((INBOX / "orgs").iterdir()):
        src = str(p.relative_to(ROOT))
        if p.suffix.lower() in {".xlsx", ".xlsm"}:
            raw += [(r, src) for r in read_xlsx(p)]
        elif p.suffix.lower() in {".csv", ".tsv"}:
            raw += [(r, src) for r in read_csv(p)]
    raw += [(r, r.get("_source_file", "guide")) for r in read_guides()]

    merged, by_slug, by_canon = {}, {}, {}

    def absorb(cur, n, src):
        for f in FIELDS:                        # fill blanks, never overwrite
            if not cur.get(f) and n.get(f):
                cur[f] = n[f]
        if src not in cur["source_files"]:
            cur["source_files"] += f"; {src}"

    for rec, src in raw:
        n = normalize(rec, src)
        if not n:
            continue
        # Match on Instagram handle first, then the name slug, then the
        # canonical name, so a venue named in both the spreadsheet and a guide
        # becomes one record even when the two spellings differ.
        key = n["instagram_handle"].lower() or n["slug"]
        canon = canonical_name(n["name"])
        canon = aliases.get(canon, canon)
        if key in merged:
            absorb(merged[key], n, src)
        elif n["slug"] in by_slug:
            absorb(by_slug[n["slug"]], n, src)
        elif canon and canon in by_canon:
            absorb(by_canon[canon], n, src)
        else:
            merged[key] = n
            by_slug.setdefault(n["slug"], n)
            if canon:
                by_canon.setdefault(canon, n)

    orgs = sorted(merged.values(), key=lambda o: (o["category"], o["name"]))
    DATA.mkdir(exist_ok=True)
    with open(DATA / "orgs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(orgs)
    (DATA / "orgs.json").write_text(json.dumps(orgs, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(orgs)} orgs -> data/orgs.csv, data/orgs.json")
    print(f"  with website:   {sum(1 for o in orgs if o['website'])}")
    print(f"  with instagram: {sum(1 for o in orgs if o['instagram_handle'])}")
    cats = {}
    for o in orgs:
        cats[o["category"]] = cats.get(o["category"], 0) + 1
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {v:4}  {k or '(uncategorized)'}")

if __name__ == "__main__":
    main()
