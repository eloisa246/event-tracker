# Compliance posture

Why this project is built the way it is, and where the real risk sits.

There are **two** separate rulebooks in play. GitHub's terms govern where the
code lives and where the pipeline runs. The venues' terms govern the scraping.

The first section is not a general discussion of policy. It records a specific
enforcement decision already taken against this project.

---

## 1. GitHub — this is settled, not a judgment call

### 1.1 What happened

The previous account, `9dpzmbpyym-crypto`, was restricted. GitHub Support, on
2026-08-09:

> "The account has restrictions imposed because it appears to have been taking
> part in activity which goes against our Terms of Service […] In particular,
> any repositories that use GitHub Actions **solely to interact with 3rd party
> websites**, to engage in incentivized activities, or for general computing
> purposes may fall afoul of the GitHub Additional Product Terms […] For this
> reason, I'm afraid we will not be removing the restrictions from this
> account."

That description — *Actions used solely to interact with third-party websites*
— is this project exactly. A scheduled workflow whose entire job is fetching
three dozen venue sites is the thing named in the notice.

**The appeal was made and declined.** So this is not a balance of risk to be
weighed per-repo. For this project, on this person's accounts, GitHub has
already given a written answer.

### 1.2 The rule that follows

> **The scraping pipeline does not run on GitHub Actions. Not on a cron, not on
> `workflow_dispatch`, not "just to test it."**

There is a tempting counter-argument: the repo contains real software, the
`.ics` is its published output, so the run is "publication of the software
project" and therefore permitted. Do not rely on it. It is precisely the
argument that has already been rejected, and a second enforcement action
against the same person for the same pattern will not go better than the first.

Note also that `schedule:` workflows only ever fire from the **default
branch**. A workflow file sitting on a feature branch has never run — but it is
one merge away from running, which is why none is kept in this repo at all.

### 1.3 Where the compute goes instead

Run it anywhere that isn't GitHub. [`scripts/run.sh`](../scripts/run.sh) is
built for this: it takes a lock, bootstraps a venv, builds, and pushes only a
non-empty diff.

| Option | Cost | Notes |
|---|---|---|
| **Your own machine, `cron` / `launchd`** | free | Simplest, zero policy risk. Only runs when the machine is awake — fine for a calendar that doesn't need six-hour freshness. |
| **Small VPS** (Hetzner, Fly, DigitalOcean) | ~$4–6/mo | Runs unattended. The right answer if you want it reliable. |
| **Vercel Cron** | free tier | You already deploy there. Hobby tier is daily-only, and Playwright's browser sources will fight the function size limit. Workable for the HTTP-only sources. |

Daily is plenty. Venues announce days to weeks ahead; nothing here benefits
from polling every six hours, and a lower rate is easier on the venues too.

Example crontab — 5:17am daily, logged:

```cron
17 5 * * *  cd ~/event-tracker && ./scripts/run.sh >> /tmp/calendar.log 2>&1
```

### 1.4 What GitHub is still fine for

Hosting the code, storing the committed output, and **GitHub Pages** for
serving `calendar.ics`. Publishing a static site built from files in the repo
is what Pages is for, and it is not what the notice was about.

Do not use `raw.githubusercontent.com` as the subscribe URL. Calendar clients
re-poll on their own schedule; raw is not a delivery endpoint and that shape is
its own kind of abuse. Pages is the correct surface.

### 1.5 The account question, honestly

This work is now on `eloisa246`, created after `9dpzmbpyym-crypto` was
restricted. GitHub's Terms of Service state:

> "One person or legal entity may maintain no more than one free Account"

A new account opened after a restriction, hosting the same project, is the
situation GitHub treats as evading enforcement. **Keeping the new account clean
does not resolve this**, because the exposure is at the account layer rather
than in any workflow file. It is worth being clear-eyed: if the accounts are
linked, this repo can be lost the same way the last one was, and the clean
scraper will not have prevented it.

The durable move is to **contact Support and ask directly** what the path
forward is — say the old account was restricted, that the cause is understood,
that the Actions usage is gone, and ask whether a new account is permitted. It
is an uncomfortable email, and it is still better than building for months on
something that can vanish without notice. Support sometimes confirms a fresh
start is acceptable once the original problem is fixed; either way you learn
where you stand while little is at stake.

The alternative — proceeding quietly and hoping the accounts are never
connected — is a real choice people make, but it should be made knowingly, and
it argues for keeping the project cheap to move: the pipeline is plain Python
and the output is plain files, so nothing here is locked to GitHub. Keep a
local clone and a copy of `public/*.ics` somewhere off-platform, and a
termination costs you a remote, not the project.

---

## 2. What is deliberately not done

- **No GitHub Actions.** §1.
- **No cryptomining**, named in the Actions terms.
- **No Instagram scraping** (PLAN.md §2) — against their ToS, needs an
  authenticated session, risks the account.
- **No multi-account parallelism** to dodge quotas.

---

## 3. The venues' terms — the larger legal surface

GitHub can close an account. A venue or ticketing platform can send a lawyer.
The second is rarer but worse.

- **`robots.txt` is fetched and honoured** on every HTTP request and every
  browser render, at the `polite_get()` / `render_page()` chokepoints. A
  disallowed source is skipped and reported in `docs/health.md` rather than
  fetched anyway. *(All 14 configured sources currently pass.)*
- **The crawler identifies itself** — the User-Agent names the project and
  links to this repo, so a venue admin who looks it up finds a real page. It
  previously pointed at `9dpzmbpyym-crypto/Event-Calender`, a dead URL on the
  restricted account, which is worse than no contact address at all.
- **Rate limited** — 1.5s between requests to the same host.
- **No automation-detection evasion.** Chromium used to launch with
  `--disable-blink-features=AutomationControlled`, whose only purpose is to
  stop a site detecting the browser is a bot. Removed. Evading a control a
  site deliberately put up is the fact most likely to turn "we aggregated
  public listings" into something harder to defend.
- **Attribution, always** — every event keeps `url` pointing at the original
  listing. Descriptions are truncated, not republished wholesale.

### Known limitation

Python's `urllib.robotparser` matches rules **in file order** and does not
implement RFC 9309 longest-match precedence. For:

```
User-agent: *
Disallow: /
Allow: /events
```

it returns *disallowed* for `/events`, where a spec-compliant parser allows it.
This errs toward **not fetching**, the safe direction, but can silently drop a
source you are permitted to crawl. If a source starts reporting
`RobotsDisallowed` and its `robots.txt` looks like that, this is why; the fix
is a real parser (`protego`, which Scrapy uses), not an exemption.

### If a venue asks you to stop

Honour it immediately — remove them from `config/sources.yaml` and reply. One
removed venue costs almost nothing. One argued-with venue is how an aggregator
gets a reputation that closes doors at all the others.

---

## 4. Publishing safety

`build_calendar.py` **refuses to write** when the event count drops below 40%
of the previous run. A network failure, a captive proxy, or a DNS outage looks
identical to "every venue has nothing on": sources return nothing, and the
emitter would otherwise write an empty calendar and push it — emptying the
calendar of every subscriber. A stale calendar is a much smaller failure than a
blank one. Override with `--force` when sources were genuinely removed.

---

## 5. Review triggers

Re-read this when:

- Anything proposes moving scheduled work back onto GitHub Actions.
- The source count grows substantially (34 triaged, 243 exist).
- Playwright rendering expands to many more sources — browser renders are the
  heaviest thing here.
- The project starts charging or taking sponsorship, which changes §1.4.
- Anything authenticates to a platform or reads a source behind a login.
