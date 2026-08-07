# AIM News Desk (Phase 1a — bare deduplicated feed)

Internal news scanner for American Icon Media. This checkpoint proves the
ingestion + normalization + dedup pipeline against live RSS/Google News data.
No clustering, scoring, auth, or branded dashboard yet — see
[docs/BUILD_STATUS.md](docs/BUILD_STATUS.md) for what's built vs. deferred,
and the Phase 1 spec doc for the full plan.

## Setup

```
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py
python seeds/seed_sources.py
```

## Run

One-shot collection pass (fastest way to see it work):
```
python scripts/run_once.py
```

Continuous server (polls on a schedule, serves a live table):
```
python -m uvicorn app.main:app --reload
```
Then open http://localhost:8000 (table) or http://localhost:8000/health (JSON status).

## Sending stories to the First Signal News content pipeline

Clicking "Send to First Signal Pipeline" on a story's detail page writes a
JSON record to `handoff/<date>/<cluster_id>.json` -- headline, all source
URLs, scores, entities. That alone doesn't feed the FB pipeline; run the
adapter to convert handoff records into the shape `batch_from_scrape.py`
expects (`--input`, a JSON list of `{"text", "url", "image_url", ...}`):

```
python scripts/adapter_to_first_signal.py --date 2026-07-21 --out "<first-signal-repo>/memory/from_newsdesk.json"
```

Then, from the First Signal News pipeline's own directory:
```
python batch_from_scrape.py --input memory/from_newsdesk.json
```

`--out` is required on purpose -- it never defaults to that pipeline's real
`memory/scrape-results.json`, which is live production state from its normal
scrape+rank flow. Every handed-off story is treated as an image candidate
(routes to Template A/B, not TOBI): the destination pipeline never actually
fetches `image_url`'s content -- the photo is always AI-generated -- so this
is a routing signal, not a real image reference, and it's set to the genuine
source URL rather than a fabricated one. See the script's docstring for the
full reasoning. Verified against the real pipeline's own `classify_post` /
`is_image_text_viable` / `stamp_provenance` functions, not just checked for
matching JSON shape.

## Notes on this environment

Built on a machine with no Node.js, Docker, or Postgres installed, so:
- Storage is SQLite (`DATABASE_URL` in `.env`) instead of Postgres/Supabase.
  Swapping later is a connection-string change only — the SQLAlchemy models
  don't change.
- The feed view is plain server-rendered HTML instead of the planned Next.js
  dashboard. It exists to prove the pipeline, not as the final UI.
