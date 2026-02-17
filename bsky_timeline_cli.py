#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv

DEFAULT_PDS = "https://bsky.social"
DEFAULT_REFRESH_SECONDS = 15
DEFAULT_LIMIT = 30

NSFW_LABELS = {
    "sexual",
    "porn",
    "nudity",
    "graphic-media",
    "explicit",
    "adult",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Mostra la timeline Bluesky in CLI: solo testo, solo persone che segui, "
            "filtro NSFW, refresh periodico."
        )
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
        help=f"Numero massimo di post per refresh (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--pds",
        default=os.environ.get("BLUESKY_PDS", DEFAULT_PDS),
        help=f"Base URL PDS Bluesky (default: {DEFAULT_PDS})",
    )
    return parser.parse_args()


def request_json(
    method: str,
    url: str,
    token: str | None = None,
    payload: dict | None = None,
) -> dict:
    headers = {"User-Agent": "bsky_timeline_cli.py/1.0"}
    body = None

    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url=url, method=method.upper(), headers=headers, data=body)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_session(pds: str, identifier: str, app_password: str) -> dict:
    url = f"{pds.rstrip('/')}/xrpc/com.atproto.server.createSession"
    return request_json(
        method="POST",
        url=url,
        payload={"identifier": identifier, "password": app_password},
    )


def fetch_following_dids(pds: str, did: str, access_jwt: str) -> set[str]:
    follows: set[str] = set()
    cursor = None

    while True:
        params = {"actor": did, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        query = urllib.parse.urlencode(params)
        url = f"{pds.rstrip('/')}/xrpc/app.bsky.graph.getFollows?{query}"
        data = request_json("GET", url, token=access_jwt)

        for profile in data.get("follows", []):
            did_value = profile.get("did")
            if isinstance(did_value, str) and did_value:
                follows.add(did_value)

        cursor = data.get("cursor")
        if not cursor:
            break

    return follows


def fetch_timeline(pds: str, access_jwt: str, limit: int) -> list[dict]:
    query = urllib.parse.urlencode({"limit": max(1, min(limit, 100))})
    url = f"{pds.rstrip('/')}/xrpc/app.bsky.feed.getTimeline?{query}"
    data = request_json("GET", url, token=access_jwt)
    return data.get("feed", [])


def extract_label_values(node: object) -> set[str]:
    values: set[str] = set()

    if isinstance(node, dict):
        labels = node.get("labels")
        if isinstance(labels, list):
            for item in labels:
                if isinstance(item, dict):
                    val = item.get("val")
                    if isinstance(val, str) and val:
                        values.add(val.lower())
                elif isinstance(item, str):
                    values.add(item.lower())
    return values


def is_nsfw(feed_item: dict) -> bool:
    label_values: set[str] = set()
    post = feed_item.get("post", {})
    author = post.get("author", {})
    record = post.get("record", {})

    label_values |= extract_label_values(feed_item)
    label_values |= extract_label_values(post)
    label_values |= extract_label_values(author)
    label_values |= extract_label_values(record)

    return bool(label_values.intersection(NSFW_LABELS))


def is_text_only_post(feed_item: dict) -> bool:
    if feed_item.get("reason"):
        return False

    post = feed_item.get("post")
    if not isinstance(post, dict):
        return False

    if post.get("embed") is not None:
        return False

    record = post.get("record")
    if not isinstance(record, dict):
        return False

    if record.get("$type") != "app.bsky.feed.post":
        return False

    text = record.get("text")
    return isinstance(text, str) and bool(text.strip())


def format_post(feed_item: dict) -> str | None:
    post = feed_item.get("post", {})
    author = post.get("author", {})
    record = post.get("record", {})

    handle = author.get("handle") or author.get("did") or "unknown"
    text = (record.get("text") or "").strip()
    indexed_at = post.get("indexedAt")

    if not text:
        return None

    when = indexed_at or "n/a"
    return f"[{when}] @{handle}\n{text}"


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def render(posts: list[str], refreshed_at: datetime, refresh_seconds: int) -> None:
    clear_screen()
    print("Bluesky Timeline CLI")
    print(f"Refresh: {refresh_seconds}s | Aggiornato: {refreshed_at.astimezone().isoformat(timespec='seconds')}")
    print("-" * 72)
    if not posts:
        print("Nessun post che rispetta i filtri.")
        return

    for idx, post in enumerate(posts, start=1):
        print(f"{idx}. {post}")
        print("-" * 72)


def main() -> int:
    args = parse_args()
    refresh_seconds = max(1, args.refresh)
    load_dotenv()

    identifier = os.environ.get("BLUESKY_IDENTIFIER", "").strip()
    app_password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
    if not identifier or not app_password:
        print("Errore: BLUESKY_IDENTIFIER o BLUESKY_APP_PASSWORD mancanti nel file .env")
        return 1

    try:
        session = create_session(args.pds, identifier, app_password)
    except urllib.error.HTTPError as exc:
        print(f"Errore login Bluesky HTTP {exc.code}: {exc.reason}")
        return 1
    except Exception as exc:
        print(f"Errore login Bluesky: {exc}")
        return 1

    access_jwt = session.get("accessJwt", "")
    did = session.get("did", "")
    if not access_jwt or not did:
        print("Errore: sessione Bluesky non valida (manca accessJwt/did).")
        return 1

    try:
        following_dids = fetch_following_dids(args.pds, did, access_jwt)
    except Exception as exc:
        print(f"Errore recupero following: {exc}")
        return 1

    if not following_dids:
        print("Attenzione: lista following vuota. Non verranno mostrati post.")

    print("Ctrl+C per uscire.")
    time.sleep(0.8)

    try:
        while True:
            try:
                items = fetch_timeline(args.pds, access_jwt, args.limit)
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    session = create_session(args.pds, identifier, app_password)
                    access_jwt = session.get("accessJwt", "")
                    items = fetch_timeline(args.pds, access_jwt, args.limit)
                else:
                    raise

            posts_to_show: list[str] = []
            for item in items:
                post = item.get("post", {})
                author = post.get("author", {})
                author_did = author.get("did")

                if not isinstance(author_did, str) or author_did not in following_dids:
                    continue
                if is_nsfw(item):
                    continue
                if not is_text_only_post(item):
                    continue

                formatted = format_post(item)
                if formatted:
                    posts_to_show.append(formatted)

            render(posts_to_show, datetime.now(timezone.utc), refresh_seconds)
            time.sleep(refresh_seconds)
    except KeyboardInterrupt:
        print("\nUscita.")
        return 0
    except Exception as exc:
        print(f"\nErrore runtime: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
