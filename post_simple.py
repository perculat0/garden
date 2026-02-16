#!/usr/bin/env python3
import argparse
import os
import ssl
import sys
import time

from atproto import Client as AtprotoClient
from dotenv import load_dotenv
from nostr.event import Event
from nostr.key import PrivateKey
from nostr.relay_manager import RelayManager

BLUESKY_MAX_POST_LENGTH = 300


def shorten_for_bluesky(text: str, max_len: int = BLUESKY_MAX_POST_LENGTH) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def publish_to_nostr(text: str, nsec: str, relays: list[str]) -> str:
    private_key = PrivateKey.from_nsec(nsec)
    event = Event(private_key.public_key.hex(), text, kind=1)
    private_key.sign_event(event)

    relay_manager = RelayManager()
    for relay in relays:
        relay_manager.add_relay(relay)

    relay_manager.open_connections({"cert_reqs": ssl.CERT_NONE})
    time.sleep(1.25)
    relay_manager.publish_event(event)
    time.sleep(1)
    relay_manager.close_connections()

    return event.id


def publish_to_bluesky(text: str, identifier: str, app_password: str) -> str:
    client = AtprotoClient()
    client.login(identifier, app_password)
    post = client.send_post(text)
    return str(getattr(post, "uri", ""))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pubblica un semplice messaggio testuale su Bluesky/Nostr."
    )
    parser.add_argument("text", nargs="?", help="Testo del messaggio")
    parser.add_argument(
        "--target",
        choices=("both", "bluesky", "nostr"),
        default="both",
        help="Dove pubblicare il messaggio (default: both)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv()

    text = (args.text or "").strip()
    if not text:
        text = input("Messaggio da pubblicare: ").strip()
    if not text:
        print("Errore: testo vuoto.")
        return 1

    if args.target in ("both", "nostr"):
        nsec = os.environ.get("NOSTR_NSEC", "").strip()
        if not nsec:
            print("Errore: NOSTR_NSEC non impostato nel .env")
            return 1

        relays_env = os.environ.get("NOSTR_RELAYS", "")
        relays = [r.strip() for r in relays_env.split(",") if r.strip()]
        if not relays:
            relays = ["wss://relay.primal.net", "wss://relay.damus.io"]

        event_id = publish_to_nostr(text, nsec, relays)
        print(f"✓ Nostr pubblicato. Event ID: {event_id}")

    if args.target in ("both", "bluesky"):
        identifier = os.environ.get("BLUESKY_IDENTIFIER", "").strip()
        app_password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
        if not identifier or not app_password:
            print("Errore: BLUESKY_IDENTIFIER o BLUESKY_APP_PASSWORD non impostati nel .env")
            return 1

        text_for_bsky = shorten_for_bluesky(text)
        uri = publish_to_bluesky(text_for_bsky, identifier, app_password)
        print(f"✓ Bluesky pubblicato. URI: {uri}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
