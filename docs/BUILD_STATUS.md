# Build status

## Source depth: 22 new sources, 3 new categories (DONE, one real bug found and fixed)

Operator requests: more RSS depth (via Feedspot), check Drudge Report, more
NY Post, new categories (Business, Trump, America First), and X/influencer
tracking. Researched each rather than assuming:

- [x] **Drudge Report**: no official RSS feed exists. Checked live (page
      source has zero `<link rel="alternate" type="application/rss+xml">`
      tags, all common feed paths 404). Drudge has never offered syndication
      by design. Did not build a scraper for it -- no ToS statement permits
      one, and that's the same line this project has held for every other
      source (RSS/Atom/official API only).
- [x] **Feedspot**: legitimate, useful directory (rss.feedspot.com) -- used
      it to source real candidate feed URLs for conservative/business
      categories, then tested every candidate live before adding any,
      same discipline as every prior source-adding round.
- [x] Tested 22 candidates; 19 worked cleanly. Added: Daily Wire, Gateway
      Pundit, The Federalist, RedState, The Blaze, PJ Media (category
      `america_first`); National Review, Washington Free Beacon, Daily
      Signal (category `politics`); Yahoo Finance, Business Insider, CNBC,
      MarketWatch, Forbes Business (category `business`); NY Post Main/
      Business/US News, Fox News National (rounding out existing NY Post
      Politics). Dropped: Commentary Magazine (403 blocked), Townhall
      (404, wrong path), Human Events (200 but 0 entries).
- [x] New Google News queries for the new categories: `Trump` (priority
      tier), `MAGA`, `US economy`, `stock market`.
- [x] **Real bug found and fixed**: the bare `"America First"` query
      collided with America First Credit Union, a real unrelated business.
      Confirmed live -- 6 real clusters were nothing but credit-union press
      coverage (branch openings, a bank acquisition, a student-athlete
      sponsorship). Fixed by requiring a political co-occurrence term and
      excluding the credit union explicitly: `"America First" (Trump OR MAGA
      OR conservative OR agenda OR movement) -"credit union"`. Re-verified:
      all top results are now genuinely about the political movement.
      Dismissed the 6 stale noise clusters plus one unrelated one-off
      coincidental match on the (unchanged) `MAGA` query ("Mago Maga" brand
      coffee roaster) -- that one was a normal single coincidental hit, not
      a systemic collision, so the query itself wasn't touched.
- [x] `seeds/seed_sources.py` updated so a fresh DB rebuild includes all of
      this, not just the live-added rows.
- [x] All 22 new sources fetched cleanly on first try (zero errors).
      `/health`: 46 sources, 3168 articles, 2770 clusters.
- [x] Full 62-test suite passing throughout (no code changes needed here,
      only data/config, so no new tests -- the query fix is config, not logic).

### X/Twitter influencer tracking (Benny Johnson etc.) -- researched, not built

Checked current facts live rather than assume:

- **Zapier does NOT avoid the API cost.** As of April 2026, Zapier's X
  integration requires *your own* X Developer App credentials (Client ID/
  Secret) -- Zapier no longer maintains a shared app. It's a nicer workflow
  UI on top of your own paid API access, not a way around it.
- **X's pricing changed in Feb 2026.** The old flat $200/month Basic tier
  closed to new signups; new developers are pay-per-use (~$0.005/read, 2M
  read cap, plus a $0.20/post charge added April 2026). For a narrow use
  case -- watching a handful of named accounts -- this could plausibly be
  cheaper than $200/mo, but exact cost depends on metering details I'd want
  to nail down with you before committing.
- **Nitter (the usual free workaround) is dead.** Officially discontinued
  Feb 2024 after X removed the guest-account access it relied on; surviving
  forks are scarce, unreliable, and now require real logged-in accounts to
  run -- not something to automate against.
- **No scraper was built.** X's ToS restricts automated collection, and this
  project has held the same line for every other source (Drudge included):
  official feed/API only, or don't collect it.

Bottom line: there's no free, reliable, ToS-compliant path. The real
options are (a) pay X's new per-use API for a narrow set of accounts --
possibly cheap, needs a cost calculation once you're ready -- or (b) treat
those influencers as a manual watch for now. Did not build anything here
pending your call on (a).

## Score retuning against real time-series data (DONE, real bug found and fixed)

Pulled real distribution stats from the live DB (1735 clusters at the time)
before touching anything, rather than guessing what needed adjustment:
age range 1.4 min - 910.5 min, momentum mean=40.2/stdev=6.8, confidence
mean=33.7/stdev=8.7, and 1657/1735 clusters (95.5%) are single-source. That
compression is real-world-correct, not a bug -- most individual news items
genuinely are single-source in a 23-source feed; artificially spreading
those scores would be fabricating differentiation that isn't there.

**Real bug found**: `official_source_presence` in `app/scoring.py` was
hardcoded to `0.0` with a comment saying "no Tier-1 feeds seeded yet" --
true when written (Phase 1b), false since Phase 1e added FBI National Press
Releases as a genuine Tier-1 source. Checked directly: 288 real clusters
contain that source, and every one was capped at confidence=32.5, identical
to any ordinary uncorroborated single-source story, despite the original
spec explicitly listing "Official source available" as a confidence factor.

- [x] Fixed: `official_source_presence = 20.0 if any(a.source_tier == 1 for
      a in articles) else 0.0`, raising confidence's ceiling from 80 to 100
      for genuinely officially-confirmed stories.
- [x] `scripts/recompute_all_scores.py`: re-runs `compute_scores` for every
      existing cluster in place (status/verification_status/membership
      untouched) -- needed because `_recompute_cluster` only fires when a
      *new* article attaches, so the 288 mostly-single-source FBI clusters
      would otherwise carry the stale pre-fix score forever, never getting
      a second article to trigger a refresh.
- [x] One existing test (`test_confidence_and_viral_scores_are_not_mechanically_coupled`)
      had used `source_tier=1` as a stand-in for "some high tier" -- with the
      fix, that incidentally exercised the new official-source path and
      failed for the *right* reason (confidence correctly went to 52.5, a
      real behavior change, not a regression). Fixed to use tier=2, and
      added `test_official_source_presence_increases_confidence` as the
      real regression guard.
- [x] **Verified against real data end to end**: captured before-state for
      5 real FBI clusters (confidence=32.5 each), ran the recompute
      (1780 clusters processed, 1715 had score changes -- most just from
      real elapsed time shifting recency bands, not the fix itself), captured
      after-state (confidence=52.5 each, +20 exactly as designed), confirmed
      zero out-of-bounds scores across all 1780 clusters, and confirmed the
      new value renders correctly on the real story detail page
      (`/stories/512` shows confidence=52), not just in the database.
- [x] Checked for other similarly-stale hardcoded assumptions elsewhere in
      `scoring.py`/`clustering.py` -- found none; the AI-dependent sub-scores
      are correctly left unstubbed (Phase 3, not faked as zeros).
- [x] Full 62-test suite passing throughout.

## Fuller covered-story tracking (DONE, verified live)

Per the original spec's covered-story fields (platform, post URL, post ID,
format, headline used, editor, notes) -- previously "Mark Covered" only
stamped `covered_at`, nothing else.

- [x] New `covered_posts` table (`app/models.py`): one row per Mark-Covered
      **event**, not one row per cluster. A story can be Covered, reopen on
      a new development (the Phase 1c reopen fix), and get Covered again
      later -- each of those is its own row, so history isn't lost to the
      second event overwriting the first.
- [x] `mark_covered()` helper (`app/main.py`) extracted so the logic is
      testable directly, same pattern as `_optional_int` -- `main.py`'s
      routes can't be unit-tested in isolation (own `SessionLocal()`, no
      DI), so pulling the actual behavior into a plain function keeps it
      testable without needing `httpx`.
- [x] Detail page: "Mark Covered" is now a small form (platform, post URL,
      post ID, format, editor, notes -- all optional) instead of a bare
      button, plus a "Coverage history" table below it listing every past
      Mark-Covered event for that story.
- [x] 4 new tests (`tests/test_covered_posts.py`): full-metadata record
      creation, headline_used defaults to canonical_headline when omitted,
      history survives the reopen-on-new-development transition, multiple
      covered events accumulate rather than overwrite.
- [x] Verified against the live server + real data: marked a real story
      Covered with full metadata via the actual form endpoint, confirmed
      the detail page renders the platform/post-link/format/editor/notes
      correctly AND confirmed the underlying DB row directly (not just the
      rendered HTML). Marked the same story Covered a second time and
      confirmed both events appear in history (Facebook + Instagram,
      distinct notes), proving the accumulate-don't-overwrite design against
      real data, not just the unit test.
- [x] Full 61-test suite passing.

## Content handoff adapter: News Desk -> First Signal News pipeline (DONE, verified against the real destination pipeline's code)

Closes the loop the original spec called for ("add a thin adapter script
that converts handoff JSON into that same shape") -- until now, "Send to
First Signal Pipeline" wrote a JSON file nothing consumed.

- [x] Investigated the ACTUAL destination format by reading the First Signal
      News repo's code directly, rather than assuming: `batch_from_scrape.py`
      reads `--input memory/scrape-results.json`, a JSON list/dict of posts
      shaped `{"text", "url"/"post_url", "image_url", ...}`, taken in INPUT
      ORDER (it does not re-rank). This corrected an assumption from the
      original Phase 1 spec write-up that `references.xlsx` held ready-to-use
      curated posts -- the real code (`scrape.py`) treats it as a list of
      page URLs to scrape, same shape as `competitors.txt`. The real handoff
      target is `batch_from_scrape.py`'s input, which skips scraping+ranking
      entirely (News Desk already did discovery + multi-source verification
      + ranking, better than a single competitor page would).
- [x] `scripts/adapter_to_first_signal.py`: reads `handoff/<date>/<cluster_id>.json`
      (one file, one date, or everything), strips the Google News outlet
      suffix from headlines, sorts by News Desk's own viral score (substituting
      for the engagement-based ranking `rank_competitors.py` would normally
      provide), and writes the destination shape.
- [x] **Design decision, documented in the script**: every handed-off story
      defaults to an image candidate (not TOBI). The destination pipeline
      never fetches `image_url`'s content -- the photo is always AI-generated,
      never a reused source image (per that pipeline's own IP-safety rule) --
      so `image_url` is a routing flag, not real image data. Set to the
      genuine primary-source URL rather than a fabricated placeholder.
- [x] `--out` is a required argument with no default pointing at the real
      pipeline's `memory/scrape-results.json` -- confirmed that file holds
      real production data (321KB, last written from an actual scrape run)
      before writing any code, specifically to avoid clobbering it.
- [x] **Verified against the real destination pipeline's own code, not just
      shape-matched JSON**: sent 3 real live clusters through the actual
      `/stories/{id}/handoff` endpoint, ran the adapter, then imported
      `classify_post`, `is_image_text_viable`, `stamp_provenance`, and
      `detect_figure` directly from `batch_from_scrape.py` and ran them
      against the adapter's output. All 3 passed the viability check, routed
      to Template B, got `_headline_source="scraped_source"` (correct
      provenance tagging), and one (`Trump tariffs`) was auto-detected as
      rendering "Donald Trump, US president" as a real figure -- proving the
      output is genuinely consumable by the pipeline as it exists today, not
      merely structurally similar.
- [x] 9 new tests (`tests/test_adapter.py`): suffix-stripping (including the
      length-safety-guard edge case my first test draft got wrong), no-source
      fallback doesn't fabricate a URL, viral-score ordering, loading by date
      vs. by cluster id, and a full `main()` round-trip. Full suite: **57 passed**.
- [x] `scripts/adapter_to_first_signal.py` is deliberately standalone (no
      cross-repo import from `app/entities.py`) since the two pipelines are
      separately deployed and maintained.

## Watchlist view (DONE, verified live against real data)

Per the original spec's left-sidebar design (Watchlist as its own nav item)
and its "Watchlist stories should continue receiving updates / recalculate
momentum / recalculate confidence / show the latest new information"
requirements:

- [x] `GET /watchlist` -- dedicated page, forced to `status=Watchlist`,
      reusing the same filter/sort/chip machinery as the main Wire (category,
      source, verification, score-range filters + quick chips all still
      work; the status dropdown and "Breaking" chip are hidden since status
      is already fixed here). Refactored the shared query+render logic out
      of `wire()` into `_wire_response()` so both routes share one
      implementation rather than duplicating the filter-building code.
- [x] Momentum/confidence recalculation was **already automatic** for every
      cluster regardless of status (`_recompute_cluster` runs on every new
      article, watchlisted or not) -- nothing new needed there, just needed
      surfacing properly in a dedicated view.
- [x] New "Updated" column (age of `latest_update_at`, distinct from the
      existing "Age" column which tracks `first_detected_at`) with a green
      highlight + dot when a story updated within the last 15 minutes --
      lightweight stand-in for the spec's "trigger an alert when meaningful
      changes occur," without building a separate alerts/notifications
      system. Added to both Wire and Watchlist tables.
- [x] "Watchlist" added to the top nav.
- [x] Verified against live, real data: watchlisted a genuinely 2-hour-old
      cluster (FDA Taylor Farms) and a genuinely 1-minute-old cluster (White
      House/Patel investigation) via the real `/stories/{id}/status`
      endpoint. Confirmed the old one shows "2h" with no highlight and the
      fresh one shows "1m" WITH the green highlight+dot -- not just that
      the feature renders, but that the freshness math is actually correct
      against real timestamps. Also confirmed the status dropdown and
      Breaking chip are genuinely absent from the rendered Watchlist page
      HTML (not just visually assumed), and the page title reads
      "Watchlist". Full 48-test suite passing throughout.

## Bug fix: filter form 422'd on any submission with a blank field

Operator report: selected a category, clicked Apply, got a raw FastAPI 422
JSON error for `source_id`/`min_viral`/`min_confidence`. Root cause: those
three route params were typed `int | None = None`. FastAPI/Pydantic only
supplies the `None` default when a query param is entirely ABSENT from the
URL -- an unselected `<select>` ("Any source") and a blank `<input
type=number>` both submit as `field=""`, which is PRESENT-but-empty, and
Pydantic correctly refuses to parse `""` as an int. Since the filter form
submits all its fields together, leaving any one on its default blank state
(which is the normal case -- nobody fills in every field every time) 422'd
the whole request.

Fixed: those three params now come in as `str | None`, parsed by a new
`_optional_int()` helper (`app/main.py`) that treats `""` the same as
"not provided." Added `test_optional_int_parses_blank_form_fields_as_none`
(also checks `"0"` correctly parses to `0`, not `None`, since it's a
non-empty string). Verified live: replayed the exact failing request
(`category=politics` with every other field blank) -- 200 OK instead of
422, and the result count matches a direct DB query for the same filter
combination. Full 48-test suite passing.

## Wire page: filters + quick-filter chips (DONE, verified live against real data)

Per the original spec's dashboard design (category / score range / status /
source / time range filters + quick-filter buttons), added to `app/main.py`'s
`wire()` route and `app/render.py`'s `render_wire_page`:

- [x] Filter form: category, status, source, verification status (dropdowns
      populated from real distinct values in the DB), min viral score, min
      confidence score (number inputs). Submits via GET so filtered views are
      bookmarkable/shareable URLs, consistent with the sort toggle.
- [x] Quick-filter chips: All, Last 15m / 1h / 3h, High Viral (>=70), High
      Confidence (>=70), Breaking, Needs Verification (maps to
      `verification_status=single_source` rather than the manually-set
      "Needs Verification" status, since that's actually populated in real
      data), Not Covered. Each is a full preset (sort preserved, other
      filters reset) rather than a cumulative toggle -- simpler and more
      predictable than stacking with whatever else was active.
- [x] Verified against live data, not just eyeballed HTML -- every filter
      checked against a direct DB query for the same condition: category
      (crime: 108 == 108), source (NPR News: 12 == 12), time window (last
      1h: 61 == 61), min_viral (>=70: 46 == 46, importantly under the 200-row
      display cap so this proves filtering is real, not just the cap), and
      a combined category+min_viral query (108 == 108). Dropdown
      selected-state round-trips correctly (`category=crime` in the URL ->
      that option renders `selected`).
- [x] Full 47-test suite still passing.

## Wire page: sort toggle (default Latest) + real "Scan complete" banner (DONE, verified live)

- [x] Default sort changed from viral-score-only to **Latest** (`latest_update_at`
      desc) per operator feedback -- freshest stories were sinking to the
      bottom because they hadn't accumulated a high viral score yet. Added a
      **Highest Viral** toggle (`/?sort=viral`) to switch back, with the
      active choice visually highlighted. Verified: default view's Age
      column reads 1m, 2m, 2m, 2m, 3m... (correctly ascending); `?sort=viral`
      matches the DB's `ORDER BY viral_score DESC` exactly (93, 90, 88, 80,
      79, 78, 78 -- confirmed via direct DB query, not just eyeballing HTML).
- [x] Real "Scan complete: N new stories found across M sources" banner,
      not just "scan started." `_scan_state` now tracks a
      `completed_unacknowledged` flag + `last_result` summary, set once by
      `run_full_scan()` and consumed (shown once, then cleared) the next
      time the Wire page renders -- so it appears exactly once, not on every
      subsequent auto-refresh. Only the manual "Scan Now" action sets this;
      the automatic background polls stay silent (a banner every 3 minutes
      would be noise). Verified with a tight poll loop against the live
      server: banner was absent while scanning, appeared exactly once the
      instant the scan finished ("0 new stories found across 23 sources, 2
      source(s) failed"), and was gone again on the very next page load.
- [x] Full 47-test suite still passing.

## Bug fix: no network timeout on feed fetches (the REAL cause of "stuck scanning")

Operator report: auto-refresh fix didn't help -- "Scan Now" still showed
"Scanning..." with no updates, latest story ~38 minutes old. The auto-refresh
was masking, not fixing, a real bug: `feedparser.parse(url)` has no network
timeout at all. Confirmed live: BBC World News hung long enough to hit a
Windows socket timeout (`WinError 10060`), and because `run_full_scan()` /
`poll_tier()` fetch sources sequentially, that one hang blocked every other
source queued behind it -- for however long the OS default timeout takes
(observed: multiple minutes, matching "it's been minutes").

Fixed in `app/collectors/rss.py`: added `_fetch_feed()`, which fetches via
`urllib.request.urlopen(..., timeout=FEED_FETCH_TIMEOUT_SECONDS)` (15s,
`app/config.py`) and hands the bytes to `feedparser.parse()` instead of
letting feedparser do its own unbounded network call. Verified live against
the actual hanging BBC feed: old behavior had no bound; new behavior fails
in 18s with a clean `<urlopen error timed out>` instead of stalling everything
behind it.

Side effect caught during verification: the fetch needs a `User-Agent`
header (bare urllib gets blocked more often than feedparser's own UA), and
the first bot-labeled UA I used ("AIMNewsDesk/1.0") got a 403 from Politico
that hadn't been there before. Switched to a standard browser UA string --
normal practice for RSS aggregators fetching publicly-published feeds, not
bypassing auth or a bot challenge. Confirmed Politico's remaining flakiness
(alternates between 403 / connection-reset / success across identical
back-to-back requests) is the source's own server being unreliable, not
something fixable here -- already handled gracefully (error recorded,
scan moves on).

Full 47-test suite passing throughout (test_collectors.py updated to mock
the new `_fetch_feed` instead of `feedparser.parse` directly, plus a new
regression test for the timeout-not-a-hang behavior).

## Bug fix: Wire page never auto-refreshed (found immediately after Phase 1f shipped)

Operator report: clicked "Scan Now", page showed "Scanning..." for minutes with
no change. Root cause: the Wire page had zero auto-refresh -- the original
Phase 1a bare-feed page had a `<meta http-equiv="refresh">` tag, but it got
dropped when render.py was rewritten for the Phase 1b Wire/detail pages and
never replaced. The backend was actually fine the whole time (verified via
`/health` and server logs: the scan completed in seconds, same as always) --
the browser just rendered one static snapshot at click time and had no reason
to ever reload. "Scanning..." was frozen, not stuck.

Fixed: `_page_head()` in `app/render.py` takes an `extra_meta` param; the Wire
page passes a `<meta http-equiv="refresh">` tag that's 5s while a scan is
actually running (`_scan_state["running"]`) and 20s otherwise. Verified live:
fired `/scan-now`, confirmed the page showed `content="5"` + disabled
"Scanning…" button immediately after, then re-checked ~12s later and confirmed
it had auto-flipped back to `content="20"` + enabled "Scan Now" with "Last
scan: 0m ago" -- no manual reload involved either time.

## Phase 1f — manual "Scan Now" + last-scan indicator (DONE, verified live)

- [x] Wire page now shows "Last scan: Xm ago" (max `last_fetch_at` across
      enabled sources) so it's visible whether the background scheduler is
      actually running, not just assumed.
- [x] `POST /scan-now` + a "Scan Now" button on the Wire page: triggers an
      immediate fetch across all enabled sources via FastAPI
      `BackgroundTasks`, so the request returns instantly (~0.1s, verified)
      instead of the browser hanging for however long 23 sources take to
      fetch. An in-memory `_scan_state["running"]` flag makes a second click
      while a scan is in flight a no-op instead of a second overlapping
      fetch pass (verified: fired two requests back-to-back, only one
      sequential pass through the source list appeared in the logs).
- [x] Verified live: triggered a real scan, watched all 23 sources process
      in the background log, confirmed genuinely new stories landed
      (CBS +3, several Google News queries +1-6 each) and `/health` counts
      increased accordingly.

## Phase 1e — more sources + six clustering bug fixes (DONE, exhaustively verified)

Added 11 real RSS sources (ABC, CBS, NBC, The Hill, Washington Examiner,
Washington Times, Al Jazeera, NY Post, Newsmax, Breitbart, FBI National Press
Releases — Tier 1 official source) after testing 15 candidates live and
dropping 4 dead ones (USA Today, DOJ, White House, AP-via-rsshub). 23 total
sources now in `seeds/seed_sources.py`. Also added `POST /sources/{id}/fetch`
("Fetch now" button) so newly added sources don't wait for the next
scheduled poll.

Adding these sources surfaced real clustering bugs that hadn't shown up with
the original 12 — more outlets meant more chances for coincidental weak
overlaps. Found and fixed six, each with its own regression test in
`tests/test_clustering.py` / `tests/test_entities.py`:

1. **Generic political entities** ("Trump", "U.S.") getting full match
   credit when shared alone → an unrelated Supreme Court/asylum story
   merged into an Iran-strikes cluster. Fix: `GENERIC_ENTITIES` blocklist.
2. **Place names double-counted as entities** ("Miami") → three unrelated
   Miami-based stories (a citizenship case, the Tate brothers arrest, an
   FBI robbery release) merged. Fix: `KNOWN_LOCATIONS` exclusion.
3. **Cluster entity-pool inflation** — matching against an ever-growing
   accumulated pool meant clusters got easier to (mis-)match the more they
   grew. Fix: `_attach` no longer merges new entities/keywords into the
   cluster; matching is against the fixed seed article only.
4. **Batch-specific common terms** ("World Cup", "Spain" during World Cup
   week) — not generic in the abstract, but common for that news cycle, so
   a fixed blocklist could never anticipate them. Fix: `entity_frequency`
   dynamically downweights any entity shared by 4+ other active clusters.
5. **Title-Case press-release headlines** (FBI/DOJ convention capitalizes
   nearly every word) → "Sentenced"/"Prison" read as named entities, merging
   an unrelated Sinaloa cartel case with a Gambian torture case. Fix:
   `extract_entities` skips capitalization-based extraction entirely when
   ≥60% of a headline's words are capitalized.
6. **Hyphenated outlet names leaking past suffix-stripping** ("Yakima
   Herald-Republic" — the old regex explicitly excluded hyphens from the
   suffix match) → outlet-name fragments extracted as fake entities matched
   between ANY two unrelated stories from that outlet. Fix: suffix regex no
   longer excludes hyphens.

Additionally: the additive weighted-sum match formula itself was replaced
with explicit rule-gates (2+ specific shared entities, OR 1 specific entity
+ real headline-text corroboration, OR very similar headline text alone) —
bugs 1-2 kept recurring in different forms specifically because an additive
formula lets several independently-weak signals add up to "just enough."
Location was also dropped from the match decision entirely (still extracted
and shown to editors) after it contributed to two of the six bugs.

**Verification**: 46-test suite, all passing. Rebuilt the live DB from
scratch after each fix and did a complete review (not a sample) of every
cluster with 2+ sources — 40 clusters, all independently confirmed
topically coherent, zero remaining bad merges found.

## Phase 1a — bare deduplicated feed (DONE, verified against live data)

- [x] Repo scaffolded (`app/`, `scripts/`, `seeds/`, `docs/`)
- [x] SQLite DB via SQLAlchemy 2.x (`DATABASE_URL` swaps to Postgres/Supabase later, no code change)
- [x] `sources`, `raw_articles`, `normalized_articles` tables
- [x] Generic RSS/Atom collector (`app/collectors/rss.py`)
- [x] Google News RSS collector (`app/collectors/google_news.py`, reuses the RSS parser)
- [x] URL canonicalization (tracking params stripped), headline normalization, content/url/headline hashing (`app/normalize.py`)
- [x] Level 1 exact dedup (URL / content / headline hash) + Level 2 near-dup (Jaccard + RapidFuzz) (`app/dedup.py`)
- [x] Per-source error handling — a broken feed logs to `source.last_error`, doesn't stop the batch
- [x] One-shot collector run (`scripts/run_once.py`) and a continuous FastAPI + APScheduler server (`app/main.py`)
- [x] Plain HTML feed view at `/`, JSON health check at `/health`
- [x] Verified against live internet feeds, not seed/fixture data (see run below)

### Last verified run (2026-07-20)

12 seeded sources (6 RSS + 6 Google News keyword queries), one collection pass:

```
TOTAL: fetched=729 new_raw=717 canonical_stories=673 duplicates_caught=44
```

11/12 sources succeeded. Politico's feed (`politicopicks.xml`) failed with a
malformed-XML parse error — real-world feed quality issue, handled gracefully
(logged to `source.last_error`, rest of the batch unaffected). `/health`
confirms: `{"sources":12,"sources_with_errors":1,"raw_articles":717,"canonical_stories":673}`.

### Known non-goals for this checkpoint (see the Phase 1 spec doc for the full list)

No clustering, no viral/confidence/momentum scoring, no auth, no branded
Next.js dashboard, no Docker/Postgres (SQLite for now — this dev machine has
no Docker or Postgres installed). The plain HTML page is a placeholder for
the real dashboard.

## Phase 1b — clustering, scoring, detail panel, handoff (DONE, verified against live data)

- [x] `story_clusters` + `story_cluster_articles` tables
- [x] Layered rules clustering: headline token similarity + entity/location overlap, no semantic step (`app/clustering.py`)
- [x] Duplicates inherit their canonical article's cluster directly (skip re-scoring identical wording)
- [x] Best-effort entity/keyword/location extraction, no ML model (`app/entities.py`)
- [x] Momentum score, preliminary rules-only viral score, confidence score (`app/scoring.py`) — all three kept genuinely independent, viral score explicitly labeled "preliminary" in the UI
- [x] `verification_status` describes SOURCE CORROBORATION only (`single_source` / `developing_coverage` / `multi_source`) — never "verified", to avoid implying a factual-truth check that doesn't exist
- [x] First Signal Wire list (sorted by viral score) + story detail panel with entities/keywords/source list/actions (`app/main.py`, `app/render.py`)
- [x] Status actions (Mark Breaking / Watchlist / Covered / Dismiss) — automatic New→Developing transition only, rest are editor-set per spec
- [x] Content handoff endpoint: `POST /stories/{id}/handoff` writes `handoff/<date>/<cluster_id>.json` — no AI generation, no caption/image logic
- [x] Verified against live data: clustering, scoring, status change, and handoff all tested against the real feed, not fixtures

### Bug caught and fixed during this pass: incorrect cluster merge

First clustering run merged an unrelated Supreme Court/asylum-seekers story into
an Iran-strikes cluster. Root cause: the match score gave full credit for 2+
shared entities regardless of how generic those entities were — the two
articles shared only "Trump" and "U.S.", both of which appear in nearly every
US political headline. Fixed by downweighting a fixed set of `GENERIC_ENTITIES`
(Trump, Biden, White House, Congress, U.S., etc.) in the match score — shared
generic-only entities now contribute a small fraction of what a shared
*specific* entity (e.g. "Hormuz", "Aoun") contributes. Re-verified after the
fix: the false merge is gone, and a genuine multi-source cluster (4 differently
worded articles about the same Iran-Lebanon ceasefire talks, sharing "Lebanon"
+ "Hezbollah" + "Aoun") still clusters correctly. See `app/entities.py`
(`GENERIC_ENTITIES`, `_ENTITY_BLOCKLIST`) and `app/clustering.py`
(`_score_against_cluster`).

### Last verified run (2026-07-20)

Same 12 sources, fresh DB: 672 canonical stories grouped into 621 story
clusters, 29 with 2+ independent sources. Top cluster (Iran strikes, 4
sources, viral=90/confidence=80/momentum=97) spot-checked — all 4 source
rows are genuinely about the same event. `POST /stories/169/status` and
`POST /stories/169/handoff` both tested directly via HTTP (browser click
simulation is unreliable in this environment — screenshots also
consistently time out here, unrelated to the app) and confirmed: status
badge updated to "Breaking", handoff JSON written with all 4 sources,
scores, entities, and timestamps intact.

## Phase 1c — test suite + covered-story reopen fix (DONE)

- [x] **Bug fix**: covered/dismissed clusters never reopened on new coverage.
      The Phase 1 spec's Definition of Done promised "a later development
      reopens it rather than getting silently dropped," but `_recompute_cluster`
      only ever handled New -> Developing. Fixed in `app/clustering.py`:
      when a new article attaches to a cluster whose status is Covered or
      Dismissed, status flips back to Developing and `covered_at` clears.
      Guarded by `test_covered_story_reopens_on_new_development`.
- [x] 35-test pytest suite covering the Phase 1 spec's testing list: URL/headline
      normalization, exact + near-duplicate detection (including the lookback
      window boundary), entity/keyword/location extraction, clustering
      (including a precise regression test reconstructing the generic-entity
      merge bug above), momentum/viral/confidence score behavior, source-fetch
      failure handling (malformed feed, network exception, already-collected
      URL), and Wire-page status filtering.
- [x] `python -m pytest tests/` -> **35 passed, exit code 0** (paste of full
      run in the session log; one test assertion was itself wrong on first
      run -- `test_exact_headline_match_is_a_duplicate` asserted the wrong
      dedup level because two empty descriptions made `content_hash` and
      `headline_hash` collide; fixed by giving the two test articles distinct
      descriptions so the levels are actually distinguishable. Not an app bug.)

## Phase 1d — source management UI + merge/split cluster actions (DONE, verified against live data)

- [x] Sources page (`GET /sources`): lists every source with last-fetch time
      and last error; inline edit form per row (category, credibility tier,
      polling tier, enabled) plus an "Add a source" form (RSS URL or Google
      News keyword query -> built into a search URL via the existing
      `build_google_news_url` helper). Disabling a source removes it from
      the polling schedule without deleting its collected history.
- [x] `merge_clusters` / `split_cluster` (`app/clustering.py`) + routes
      `POST /stories/{id}/merge` and `POST /stories/{id}/split` — the manual
      correction path for when rules-based clustering misfires (over-merge
      or under-merge), per the spec's "editors need this from day one" note.
      Merge unions entities/keywords/location and deletes the absorbed
      cluster; split re-extracts entities/keywords from the moved articles'
      original headlines rather than leaving the new cluster's tags empty.
- [x] 5 new tests (`tests/test_merge_split.py`): merge moves all articles +
      unions entities, self-merge rejected, split extracts selected articles
      into a new cluster, split-everything rejected, splitting an article
      that isn't actually in the cluster rejected. Full suite: **40 passed**.
- [x] Verified against the live server + real DB (not fixtures): added a
      real source (Reuters World, RSS) via `POST /sources`, edited it via
      `POST /sources/{id}/update` including the unchecked-checkbox ->
      `enabled=False` case, merged two real unrelated single-article
      clusters into one (World Cup + Paramount/Warner Bros — confirms
      entity union: `["World Cup","Court","Paramount","Warner Bros"]`,
      source cluster correctly 404s after merge), and split one article out
      of a real 9-article Alaska-pilot Supreme Court cluster (379: 9->8
      articles, new cluster 648: 1 article, status "New").
- [x] Note: FastAPI routes in `app/main.py` open their own `SessionLocal()`
      rather than taking an injected session, so route-level tests would
      need a refactor (or `httpx`, not installed here) to run against an
      isolated DB. Scoped out of this round — verified via direct HTTP
      calls against the live server instead, which is what's shown above.

## Next: Phase 1e

- [ ] Auth (Supabase Auth) + roles — needs the user to provide/create a Supabase
      project; account creation is not something to do unprompted
- [ ] Swap SQLite -> Postgres/Supabase once available in the target environment
- [ ] Next.js frontend once Node.js is available in the target environment
- [ ] Tune clustering/scoring thresholds against a longer stretch of real
      (non-bulk-backfilled) data — momentum in particular looks artificially
      uniform right now since all seed data landed in one burst
- [ ] Hard delete for sources (currently disable-only; a real DELETE would
      need to decide what happens to that source's existing raw_articles)
- [ ] Route-level tests for `app/main.py` (needs session dependency-injection
      refactor + `httpx`, see the note above)
