#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
import textwrap
import time
from datetime import datetime
from typing import Any

from atproto import Client as AtprotoClient
from dotenv import load_dotenv

DEFAULT_REFRESH_SECONDS = 15
DEFAULT_LIMIT = 30
MAX_API_LIMIT = 100
FOLLOW_CACHE_CYCLES = 20

NSFW_KEYWORDS = {
    "adult",
    "nsfw",
    "porn",
    "sexual",
    "nudity",
    "graphic-media",
    "gore",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mostra la timeline Bluesky in CLI (solo testo, solo follow, no NSFW)."
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Intervallo refresh in secondi (default: {DEFAULT_REFRESH_SECONDS})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Numero massimo post da mostrare per refresh (default: {DEFAULT_LIMIT})",
    )
    return parser.parse_args()


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _extract_text(record: Any) -> str:
    text = _get_attr(record, "text", "")
    if isinstance(text, str):
        return text.strip()
    return ""


def _iter_labels(value: Any) -> list[str]:
    labels = _get_attr(value, "labels", []) or []
    out = []
    for item in labels:
        val = _get_attr(item, "val", "")
        if isinstance(val, str) and val.strip():
            out.append(val.strip().lower())
    return out


def _is_nsfw(feed_item: Any) -> bool:
    post = _get_attr(feed_item, "post")
    author = _get_attr(post, "author")

    label_values = []
    label_values.extend(_iter_labels(feed_item))
    label_values.extend(_iter_labels(post))
    label_values.extend(_iter_labels(author))

    for label in label_values:
        if label in NSFW_KEYWORDS:
            return True
        for keyword in NSFW_KEYWORDS:
            if keyword in label:
                return True
    return False


def _is_text_only(feed_item: Any) -> bool:
    post = _get_attr(feed_item, "post")
    if post is None:
        return False

    if _get_attr(post, "embed") is not None:
        return False

    record = _get_attr(post, "record")
    text = _extract_text(record)
    return bool(text)


def _format_post_line(index: int, author_name: str, handle: str, created_at: str) -> str:
    return f"[{index:02d}] {author_name} (@{handle}) - {created_at}"


def _format_timestamp(raw_ts: str) -> str:
    if not isinstance(raw_ts, str) or not raw_ts:
        return "n/a"

    parsed = raw_ts
    if parsed.endswith("Z"):
        parsed = parsed[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(parsed)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw_ts


def _fetch_following_dids(client: AtprotoClient, actor_did: str) -> set[str]:
    follows: set[str] = set()
    cursor = None

    while True:
        kwargs: dict[str, Any] = {"actor": actor_did, "limit": MAX_API_LIMIT}
        if cursor:
            kwargs["cursor"] = cursor

        response = client.app.bsky.graph.get_follows(**kwargs)
        entries = _get_attr(response, "follows", []) or []

        for entry in entries:
            did = _get_attr(entry, "did", "")
            if isinstance(did, str) and did:
                follows.add(did)

        cursor = _get_attr(response, "cursor")
        if not cursor:
            break

    return follows


def _fetch_timeline_posts(
    client: AtprotoClient,
    following_dids: set[str],
    limit: int,
) -> list[dict[str, str]]:
    response = client.app.bsky.feed.get_timeline(limit=min(limit, MAX_API_LIMIT))
    feed = _get_attr(response, "feed", []) or []

    posts: list[dict[str, str]] = []
    seen_uris: set[str] = set()

    for item in feed:
        if _is_nsfw(item) or not _is_text_only(item):
            continue

        post = _get_attr(item, "post")
        author = _get_attr(post, "author")
        author_did = _get_attr(author, "did", "")
        if author_did not in following_dids:
            continue

        uri = _get_attr(post, "uri", "")
        if uri in seen_uris:
            continue

        seen_uris.add(uri)
        handle = _get_attr(author, "handle", "unknown")
        display_name = _get_attr(author, "display_name", "") or handle
        record = _get_attr(post, "record")
        text = _extract_text(record)
        created_at = _format_timestamp(_get_attr(record, "created_at", ""))

        posts.append(
            {
                "display_name": str(display_name),
                "handle": str(handle),
                "text": text,
                "created_at": created_at,
            }
        )

    return posts


def _render(posts: list[dict[str, str]], refresh_seconds: int, following_count: int) -> None:
    print("\033[2J\033[H", end="")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Bluesky Timeline CLI | aggiornato: {now}")
    print(
        f"Filtro: testo-only, solo account seguiti ({following_count}), no NSFW | refresh: {refresh_seconds}s"
    )
    print("-" * 80)

    if not posts:
        print("Nessun post valido trovato in questo refresh.")
        return

    term_width = shutil.get_terminal_size((100, 20)).columns
    body_width = max(40, term_width - 4)

    for idx, post in enumerate(posts, start=1):
        print(_format_post_line(idx, post["display_name"], post["handle"], post["created_at"]))
        wrapped = textwrap.fill(post["text"], width=body_width, initial_indent="    ", subsequent_indent="    ")
        print(wrapped)
        print()


def main() -> int:
    args = parse_args()
    if args.refresh < 1:
        print("Errore: --refresh deve essere >= 1")
        return 1

    if args.limit < 1:
        print("Errore: --limit deve essere >= 1")
        return 1

    load_dotenv()

    identifier = os.environ.get("BLUESKY_IDENTIFIER", "").strip()
    app_password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
    if not identifier or not app_password:
        print("Errore: BLUESKY_IDENTIFIER o BLUESKY_APP_PASSWORD non impostati nel .env")
        return 1

    client = AtprotoClient()
    client.login(identifier, app_password)

    me = client.app.bsky.actor.get_profile(actor=identifier)
    my_did = _get_attr(me, "did", "")
    if not my_did:
        print("Errore: impossibile recuperare il DID dell'account autenticato")
        return 1

    cycle = 0
    following_dids = _fetch_following_dids(client, my_did)

    while True:
        try:
            if cycle % FOLLOW_CACHE_CYCLES == 0 and cycle != 0:
                following_dids = _fetch_following_dids(client, my_did)

            posts = _fetch_timeline_posts(client, following_dids, args.limit)
            _render(posts, args.refresh, len(following_dids))

            cycle += 1
            time.sleep(args.refresh)
        except KeyboardInterrupt:
            print("\nUscita richiesta dall'utente.")
            return 0
        except Exception as exc:
            print(f"\nErrore durante il refresh: {exc}")
            time.sleep(args.refresh)


if __name__ == "__main__":
    sys.exit(main())
