# Digital Garden + Nostr/Bluesky Toolkit

A personal digital garden served as a static website, with Python automation to publish entries to Nostr and Bluesky.

This repository combines:
- a client-side garden UI (`index.html`, `css/`, `js/`, `data.json`)
- publishing tools for Nostr + Bluesky (`post_note.py`, `post_simple.py`)
- Bluesky timeline CLI viewers (`bluesky_timeline.py`, `bsky_timeline_cli.py`)

## Repository Structure

- `index.html`: main page for the garden.
- `data.json`: canonical content database (title -> entry object).
- `css/style.css`: all UI styling (menu, masonry cards, lightbox, overlays).
- `js/main.js`: app bootstrap and render pipeline.
- `js/grid.js`: HTML generation for cards + media handling + masonry layout integration.
- `js/wrap.js`: filtering and statistics logic.
- `js/nav.js`: left menu rendering (counts, type/tag filters).
- `js/util.js`: icons and helpers (URL/media/type checks).
- `js/theme.js`: theme loader/persistence via `localStorage`.
- `js/lightbox.js`: click-to-zoom image viewer.
- `js/seer.js`: lightweight timing profiler.
- `js/imagesloaded.js`, `js/masonry.js`: bundled third-party libs.
- `post_note.py`: interactive entry creation + publish to Nostr and Bluesky + git commit/push.
- `post_simple.py`: publish a plain text message to Nostr/Bluesky.
- `bluesky_timeline.py`: Bluesky timeline CLI (atproto client version).
- `bsky_timeline_cli.py`: Bluesky timeline CLI (raw XRPC HTTP version).
- `.env_example`: required environment variables.
- `sw.js`, `manifest.json`: basic PWA/offline cache setup.
- `.well-known/nostr.json` and `nostr.json`: NIP-05 style Nostr mapping.
- `CNAME`: custom domain for static hosting.

## Data Model (`data.json`)

Each top-level key is the note title. The value is an object with fields such as:

Core fields:
- `TYPE` (array of strings)
- `TAGS` (array of strings)
- `DATE` (Holocene format like `12025-02-17`)
- `QOTE` (string or array)
- `DONE` (boolean)
- `DIID` (integer ID)

Optional content fields:
- `LINK` (string or array)
- `MEDIA_URL` (string or array; remote image/video or URL)
- `TERM`, `NOTE`, `PROG`, `AUTH`, `PROJ`, `FILE`, `WIDE`, `SEEN`

Publishing metadata fields (added by automation):
- `NOSTR_KIND`, `POSTED_TO_NOSTR`, `NOSTR_EVENT_ID`
- `POSTED_TO_BLUESKY`, `BLUESKY_URI`, `BLUESKY_CID`, `BLUESKY_TEXT`
- `BLUESKY_EMBED_TYPE`, `BLUESKY_MEDIA_UPLOADED`

## Frontend Behavior

### Rendering flow
1. `main.start()` fetches `data.json`.
2. `wrap.stats()` computes totals, types, tags, terms, done count.
3. `nav.display()` builds filter/navigation menu.
4. `wrap.filter()` applies hash-based filters (`#type-x`, `#tag-y`, `#done-true`, `#term`, etc.).
5. `grid.buildAllArticles()` renders card HTML.
6. Masonry layout is applied and recalculated as images load.

### Supported card content
- Title, type icons, done status
- Date, author, tags, projects
- Multi-line quote/note/progress/term blocks
- Links (single or multiple)
- Local media files from `content/media/`
- Remote media through `MEDIA_URL`:
  - image extensions render `<img>`
  - video extensions render `<video controls>`
  - other URLs are rendered as clickable links

### UI features
- Left fixed navigation with aggregate counts
- Hash routing filters (no backend required)
- Lightbox for image expansion
- Theme persistence via `localStorage`
- Service worker cache for core assets

## Python Automation

## `post_note.py` (main workflow)

Interactive mode (default):
1. Prompts for title, `TYPE`, tags, link, media URL, date, and multi-line text.
2. Auto-generates next `DIID`.
3. Determines `NOSTR_KIND` from `TYPE` (`note/quote/link/...` -> kind 1, `article/dictionary/research` -> kind 30023).
4. Builds post text from title + quote/text + link + media.
5. Publishes to Nostr.
6. Publishes to Bluesky (300-char text cap; optional external/image embed).
7. Writes social metadata back to `data.json`.
8. Runs `git add`, `git commit`, and `git push`.

Pending mode:
- `python post_note.py --pending`
- Publishes entries where `DONE=true` and at least one of Nostr/Bluesky is missing.
- Optional `MIN_DIID` gate prevents older entries from being republished.

Bluesky embed logic:
- If `LINK` is a web URL, it builds an external card embed.
- If `MEDIA_URL` is an image, it tries to upload it as thumbnail.
- If embed upload fails, it falls back to plain text post.

## `post_simple.py`

Minimal publisher for plain text posts.

Examples:
- `python post_simple.py "Hello world"`
- `python post_simple.py --target bluesky "Only on Bluesky"`
- `python post_simple.py --target nostr "Only on Nostr"`

## Bluesky Timeline CLIs

### `bluesky_timeline.py` (atproto SDK)
- Auth via app password.
- Fetches accounts you follow.
- Polls timeline every `--refresh` seconds.
- Shows only:
  - posts from followed DIDs
  - text-only posts (no embeds)
  - non-NSFW labeled content

### `bsky_timeline_cli.py` (raw HTTP/XRPC)
- Same user-facing behavior via direct HTTP calls.
- Supports custom `--pds` endpoint.
- Handles token refresh on 401 by recreating session.

## Environment Configuration

Copy `.env_example` to `.env` and set credentials.

Required:
- `NOSTR_NSEC`
- `BLUESKY_IDENTIFIER`
- `BLUESKY_APP_PASSWORD`

Common optional:
- `GARDEN_REPO_PATH` (default `.`)
- `GARDEN_JSON_FILE` (default `garden.json`; in this repo usually set to `data.json`)
- `NOSTR_RELAYS`
- `NOSTR_KIND_DEFAULT`
- `MIN_DIID`
- `BLUESKY_PDS` (for `bsky_timeline_cli.py`)

## Local Run

Frontend:
- Serve with any static server (for service worker behavior, use HTTP server instead of opening `file://`).

Python tools:
- Install dependencies from your Python environment:
  - `python-dotenv`
  - `atproto`
  - `nostr` package used by scripts (`nostr.key`, `nostr.event`, `nostr.relay_manager`)

## Notes and Current Constraints

- `post_note.py` is interactive-first and assumes a clean publish path (no dry-run mode).
- `git push` is automatic when commit succeeds.
- Nostr relay connections disable certificate checks (`ssl.CERT_NONE`), which is practical but less strict.
- Frontend filtering is hash-based and client-only; there is no backend API.
- Some legacy Electron add-overlay code is still present in `js/add.js` but is only active when `window.showAdd` is enabled.

## Bluesky Share Summary (<=300 chars)

A static digital garden with Masonry UI, tag/type filters, and lightbox media. Includes Python tools to create notes, publish to Nostr + Bluesky, sync metadata back to JSON, and monitor a filtered Bluesky timeline from the terminal.
