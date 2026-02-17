# Digital Garden + Nostr/Bluesky Toolkit

A personal digital garden served as a static website, with Python automation to publish entries to Nostr and Bluesky.

This repository now includes a static SEO build pipeline:
- prerendered homepage content in `index.html`
- full prerendered archive in `archivio.html`
- one HTML page per note in `notes/`
- generated `sitemap.xml`

## Repository Structure

- `data.json`: canonical content database (`title -> entry object`)
- `build.py`: static build generator (index prerender + note pages + sitemap)
- `index.html`: main page template + prerendered note content
- `archivio.html`: generated full archive page with all notes prerendered
- `notes/`: generated static pages, one per note (`notes/<slug>.html`)
- `sitemap.xml`: generated sitemap for crawlers
- `tests/test_build.py`: unit tests for sorting, limits and schema generation
- `scripts/validate_structured_data.py`: JSON-LD validation precheck
- `.github/workflows/ci.yml`: CI + scheduled structured-data validation
- `css/style.css`: UI styling
- `js/`: frontend app (filters, masonry, lightbox, nav, helpers)
- `post_note.py`: interactive note creation + publish to Nostr/Bluesky + auto build + git commit/push
- `post_simple.py`: simple text publish to Nostr/Bluesky + auto build
- `note.py`: unified CLI wrapper for `post_note.py` / `post_simple.py`
- `bluesky_timeline.py`, `bsky_timeline_cli.py`: Bluesky timeline CLIs
- `.env_example`: required environment variables
- `.well-known/nostr.json`, `nostr.json`: Nostr mappings
- `CNAME`: custom domain used by static hosting

## What Changed (SEO Build Step)

Before:
- note content was loaded client-side from `data.json` after page load

Now:
- `build.py` prerenders content directly into `index.html`
- `build.py` creates `notes/<slug>.html` for every entry
- `build.py` creates `sitemap.xml` using `GARDEN_SITE_URL` or `CNAME`
- `build.py` ensures `index.html` has `meta name="robots" content="index, follow"`

This makes the site much more crawler-friendly.

## Data Model (`data.json`)

Each top-level key is the note title. Value is an object with fields like:

Core fields:
- `TYPE` (array of strings)
- `TAGS` (array of strings)
- `DATE` (Holocene format like `12025-02-17`)
- `QOTE` (string or array)
- `DONE` (boolean)
- `DIID` (integer ID)

Optional content fields:
- `LINK` (string or array)
- `MEDIA_URL` (string or array; remote image/video/url)
- `TERM`, `NOTE`, `PROG`, `AUTH`, `PROJ`, `FILE`, `WIDE`, `SEEN`

Publishing metadata (added by automation):
- `NOSTR_KIND`, `POSTED_TO_NOSTR`, `NOSTR_EVENT_ID`
- `POSTED_TO_BLUESKY`, `BLUESKY_URI`, `BLUESKY_CID`, `BLUESKY_TEXT`
- `BLUESKY_EMBED_TYPE`, `BLUESKY_MEDIA_UPLOADED`

## Build Pipeline (`build.py`)

Default run:
```bash
python build.py
```

What it does:
1. Reads `data.json`
2. Sorts entries by `DATE` descending (fallback `DIID` descending)
3. Generates stable slugs from note titles
4. Writes `notes/<slug>.html` for each entry
5. Removes stale generated note pages
6. Replaces content inside `<main>...</main>` in `index.html` with the latest 10 prerendered cards
7. Generates `archivio.html` with all prerendered cards
8. Updates robots meta to `index, follow`
9. Generates `sitemap.xml` if a site URL is available

Optional args:
```bash
python build.py --data data.json --index-template index.html --archive archivio.html --notes-dir notes --sitemap sitemap.xml --site-url https://example.com
```

Site URL resolution priority:
1. `--site-url`
2. `GARDEN_SITE_URL` env var
3. `CNAME` (`https://<cname>`)

## Publishing Workflows

### `post_note.py` (interactive)

Main flow:
1. Prompt for title/types/tags/link/media/date/text
2. Publish to Nostr
3. Publish to Bluesky
4. Update `data.json`
5. Run `build.py` automatically
6. Git add/commit/push (`data.json`, `index.html`, `notes/`, `sitemap.xml`)

Pending mode:
```bash
python post_note.py --pending
```
Publishes entries with `DONE=true` and missing social publication, then runs build + git push.

### `post_simple.py`

Examples:
```bash
python post_simple.py "Hello world"
python post_simple.py --target bluesky "Only on Bluesky"
python post_simple.py --target nostr "Only on Nostr"
```

After posting, it now runs `build.py` automatically.

## Unified CLI (`note.py`)

Use one command entrypoint for publishing scripts.

Examples:
```bash
python note.py --post-note
python note.py --post-note --pending
python note.py --post-simple "Hello world"
python note.py --post-simple --target nostr "Only on Nostr"
```

`note.py` forwards extra arguments to the selected underlying script.

## Frontend Runtime Behavior

Even with prerendered HTML, frontend JS still runs for:
- filtering/navigation
- masonry layout
- lightbox and UI interactions

So you get both:
- crawlable initial HTML
- interactive client-side UX

## Structured Data

- `index.html` includes JSON-LD for `Person` and `WebSite`
- each `notes/<slug>.html` includes JSON-LD for `BlogPosting`/`Article`, plus `publisher.logo` (`sndldg.png`)

## Tests and CI

Run local tests:
```bash
python -m unittest discover -s tests -v
```

Run structured-data validation precheck:
```bash
python scripts/validate_structured_data.py --index index.html --notes-dir notes
```

GitHub Actions (`.github/workflows/ci.yml`) runs on:
- push
- pull request
- manual trigger
- schedule (weekly, Monday)

The scheduled job performs a Rich Results precheck by validating generated JSON-LD structure.

## Environment Configuration

Copy `.env_example` to `.env`.

Required:
- `NOSTR_NSEC`
- `BLUESKY_IDENTIFIER`
- `BLUESKY_APP_PASSWORD`

Common optional:
- `GARDEN_REPO_PATH` (default `.`)
- `GARDEN_JSON_FILE` (default `garden.json`, typically set to `data.json`)
- `NOSTR_RELAYS`
- `NOSTR_KIND_DEFAULT`
- `MIN_DIID`
- `BLUESKY_PDS` (for `bsky_timeline_cli.py`)
- `GARDEN_SITE_URL` (used by `build.py` for canonical/sitemap URLs)

## Local Run

Frontend:
- serve with a static HTTP server (not `file://`)

Python dependencies:
- `python-dotenv`
- `atproto`
- `nostr` package providing:
  - `nostr.key`
  - `nostr.event`
  - `nostr.relay_manager`

## Notes and Constraints

- `post_note.py` remains interactive-first
- `git push` is automatic when commit succeeds
- Nostr relay connections currently use `ssl.CERT_NONE`
- `build.py` mutates `index.html` and generated artifacts (`notes/`, `sitemap.xml`)
- frontend filtering remains hash-based and client-side
