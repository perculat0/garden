#!/usr/bin/env python3
import json
import mimetypes
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from atproto import Client as AtprotoClient, models
from dotenv import load_dotenv
from nostr.key import PrivateKey
from nostr.event import Event
from nostr.relay_manager import RelayManager

ALLOWED_TYPES = {
    "note",
    "quote",
    "article",
    "image",
    "video",
    "link",
    "rant",
    "dictionary",
    "research",
    "log",
}

TYPE_KIND_MAP = {
    "note": 1,
    "quote": 1,
    "rant": 1,
    "link": 1,
    "image": 1,
    "video": 1,
    "log": 1,

    "article": 30023,
    "dictionary": 30023,
    "research": 30023,
}

BLUESKY_MAX_POST_LENGTH = 300
BLUESKY_DESC_MAX_LENGTH = 300


# ========================
# CONFIG & IO
# ========================

def load_config():
    load_dotenv()
    repo_path = Path(os.environ.get("GARDEN_REPO_PATH", ".")).resolve()
    json_file = os.environ.get("GARDEN_JSON_FILE", "garden.json")
    json_path = repo_path / json_file

    nsec = os.environ.get("NOSTR_NSEC")
    if not nsec:
        raise RuntimeError("NOSTR_NSEC non impostato nel .env")

    bsky_identifier = os.environ.get("BLUESKY_IDENTIFIER", "").strip()
    if not bsky_identifier:
        raise RuntimeError("BLUESKY_IDENTIFIER non impostato nel .env")

    bsky_app_password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
    if not bsky_app_password:
        raise RuntimeError("BLUESKY_APP_PASSWORD non impostato nel .env")

    relays_env = os.environ.get("NOSTR_RELAYS", "")
    relays = [r.strip() for r in relays_env.split(",") if r.strip()]
    if not relays:
        relays = ["wss://nostr-pub.wellorder.net", "wss://relay.damus.io"]

    kind_default_env = os.environ.get("NOSTR_KIND_DEFAULT", "1")
    try:
        nostr_kind_default = int(kind_default_env)
    except ValueError:
        nostr_kind_default = 1

    min_diid_env = os.environ.get("MIN_DIID", "").strip()
    min_diid = None
    if min_diid_env:
        try:
            min_diid = int(min_diid_env)
        except ValueError:
            min_diid = None

    return (
        repo_path,
        json_path,
        nsec,
        relays,
        nostr_kind_default,
        min_diid,
        bsky_identifier,
        bsky_app_password,
    )


def load_garden(json_path: Path):
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_garden(json_path: Path, data: dict):
    tmp = json_path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(json_path)


# ========================
# HELPER
# ========================

def holocene_today() -> str:
    """Ritorna la data tipo 12025-11-18."""
    today = date.today()
    year = today.year + 10000
    return f"{year:05d}-{today.month:02d}-{today.day:02d}"


def safe_int_input(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print("Valore non valido, uso default.")
        return default


def next_diid(garden: dict) -> int:
    diids = []
    for entry in garden.values():
        if isinstance(entry, dict) and isinstance(entry.get("DIID"), int):
            diids.append(entry["DIID"])
    return (max(diids) + 1) if diids else 0

def is_media_url(url: str) -> bool:
    if not url:
        return False
    url = url.lower()
    media_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm")
    return any(url.split("?")[0].endswith(ext) for ext in media_exts)


def is_web_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https")


def is_image_url(url: str) -> bool:
    if not url:
        return False
    path = urlparse(url).path.lower()
    image_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    return any(path.endswith(ext) for ext in image_exts)


def shorten_for_bluesky(content: str, max_len: int = BLUESKY_MAX_POST_LENGTH) -> str:
    text = content.strip()
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1].rstrip() + "…"


def clean_text_line(line: str) -> str:
    line = line.strip()
    if line.startswith(">"):
        line = line[1:].strip()
    return re.sub(r"\s+", " ", line)


def entry_description_for_bluesky(entry: dict, max_len: int = BLUESKY_DESC_MAX_LENGTH) -> str:
    qote = entry.get("QOTE")
    parts = []

    if isinstance(qote, list):
        for item in qote:
            if isinstance(item, str):
                clean = clean_text_line(item)
                if clean:
                    parts.append(clean)
    elif isinstance(qote, str):
        clean = clean_text_line(qote)
        if clean:
            parts.append(clean)

    text = " ".join(parts).strip()
    if not text:
        text = "Condiviso dal mio digital garden."

    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def title_for_bluesky_card(title: str, max_len: int = 100) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def load_media_bytes(media_url: str, repo_path: Path) -> tuple[bytes | None, str | None]:
    if not media_url:
        return None, None

    if media_url.startswith("blob:"):
        return None, None

    if is_web_url(media_url):
        req = urllib.request.Request(
            media_url,
            headers={"User-Agent": "post_note.py/1.0 (+digital-garden)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                mime_type = resp.headers.get_content_type()
                if mime_type == "application/octet-stream":
                    guessed, _ = mimetypes.guess_type(media_url)
                    mime_type = guessed or mime_type
                return data, mime_type
        except (urllib.error.URLError, TimeoutError):
            return None, None

    local_path = Path(media_url)
    if not local_path.is_absolute():
        local_path = (repo_path / local_path).resolve()

    if not local_path.exists() or not local_path.is_file():
        return None, None

    try:
        data = local_path.read_bytes()
    except OSError:
        return None, None

    guessed, _ = mimetypes.guess_type(local_path.name)
    return data, guessed or "application/octet-stream"


def build_bluesky_embed(
    client: AtprotoClient,
    title: str,
    entry: dict,
    repo_path: Path,
):
    link = entry.get("LINK")
    media_url = entry.get("MEDIA_URL")

    if isinstance(link, list):
        link = next((x for x in link if isinstance(x, str) and x.strip()), None)

    if isinstance(media_url, list):
        media_url = next((x for x in media_url if isinstance(x, str) and x.strip()), None)

    thumb_blob = None
    media_uploaded = False

    if isinstance(media_url, str) and is_image_url(media_url):
        try:
            media_bytes, _ = load_media_bytes(media_url, repo_path)
            if media_bytes:
                thumb_response = client.upload_blob(media_bytes)
                thumb_blob = thumb_response.blob
                media_uploaded = True
        except Exception:
            thumb_blob = None
            media_uploaded = False

    if isinstance(link, str) and is_web_url(link):
        external = models.AppBskyEmbedExternal.External(
            title=title_for_bluesky_card(title),
            description=entry_description_for_bluesky(entry),
            uri=link,
            thumb=thumb_blob,
        )
        return (
            models.AppBskyEmbedExternal.Main(external=external),
            "external",
            media_uploaded,
        )

    if thumb_blob is not None:
        image = models.AppBskyEmbedImages.Image(
            alt=title_for_bluesky_card(title),
            image=thumb_blob,
        )
        return (
            models.AppBskyEmbedImages.Main(images=[image]),
            "images",
            media_uploaded,
        )

    return None, None, False

# ========================
# CONTENT FORMATTING
# ========================

def format_entry_content(title: str, entry: dict) -> str:
    """
    Costruisce il testo del post (Nostr/Bluesky) a partire dalla entry del garden.
    Include solo titolo, quote/testo, link e media.
    """
    lines = []

    # Titolo
    lines.append(f"{title}")

    # Quote / testo
    qote = entry.get("QOTE")
    if qote:
        if isinstance(qote, str):
            q_lines = [qote]
        else:
            q_lines = qote
        lines.append("")
        for q in q_lines:
            if isinstance(q, str) and q.strip().startswith(">"):
                lines.append(q)
            else:
                lines.append(f"> {q}")

    # Link "normale"
    link = entry.get("LINK")
    if link and not is_media_url(link):
        lines.append("")
        lines.append(f"🔗 {link}")

    # Media (immagine/video)
    media_url = entry.get("MEDIA_URL")
    if media_url:
        lines.append("")
        lines.append(media_url)

    return "\n".join(lines).strip()


# ========================
# NOSTR
# ========================

def publish_to_nostr(content: str, nsec: str, relays: list[str], kind: int = 1) -> str:
    """
    Pubblica un evento Nostr con kind selezionabile.
    Versione minimale e robusta: niente tag extra, solo testo.
    """
    private_key = PrivateKey.from_nsec(nsec)
    event = Event(private_key.public_key.hex(), content, kind=kind)
    private_key.sign_event(event)

    relay_manager = RelayManager()
    for r in relays:
        relay_manager.add_relay(r)

    relay_manager.open_connections({"cert_reqs": ssl.CERT_NONE})
    time.sleep(1.25)

    relay_manager.publish_event(event)
    time.sleep(1)

    relay_manager.close_connections()
    return event.id


def publish_to_bluesky(
    content: str,
    title: str,
    entry: dict,
    repo_path: Path,
    identifier: str,
    app_password: str,
) -> tuple[str, str, str, str | None, bool]:
    """
    Pubblica su Bluesky con app password.
    Ritorna (uri, cid, text_posted, embed_type, media_uploaded).
    """
    text_to_post = shorten_for_bluesky(content)
    client = AtprotoClient()
    client.login(identifier, app_password)
    embed, embed_type, media_uploaded = build_bluesky_embed(
        client=client,
        title=title,
        entry=entry,
        repo_path=repo_path,
    )
    if embed is not None:
        try:
            post_result = client.send_post(text_to_post, embed=embed)
        except Exception:
            post_result = client.send_post(text_to_post)
            embed_type = None
            media_uploaded = False
    else:
        post_result = client.send_post(text_to_post)

    uri = getattr(post_result, "uri", "")
    cid = getattr(post_result, "cid", "")
    return str(uri), str(cid), text_to_post, embed_type, media_uploaded


# ========================
# GIT
# ========================

def git_commit_and_push(repo_path: Path, message: str, json_path: Path):
    paths_to_add = [
        str(json_path.relative_to(repo_path)),
        "index.html",
        "archivio.html",
        "sitemap.xml",
        "notes",
    ]
    subprocess.run(["git", "-C", str(repo_path), "add", *paths_to_add], check=True)
    result = subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", message],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        subprocess.run(["git", "-C", str(repo_path), "push"], check=True)
    else:
        print("ℹ️ Nessun nuovo commit da pushare:", result.stderr.strip())


def run_build(repo_path: Path):
    build_script = repo_path / "build.py"
    if not build_script.exists():
        raise RuntimeError(f"build.py non trovato in {repo_path}")
    subprocess.run([sys.executable, str(build_script)], cwd=repo_path, check=True)


# ========================
# LOGICA: CREAZIONE NUOVO POST
# ========================

def create_entry_interactive(garden: dict, nostr_kind_default: int) -> tuple[str, dict]:
    print("=== Nuova nota per il digital garden + Nostr ===")

    # Titolo
    title = input("Titolo della nota: ").strip()
    if not title:
        raise RuntimeError("Titolo obbligatorio.")

    # TYPE (validato)
    while True:
        type_raw = input(
            "TYPE (lista separata da virgola, es: quote,article,video) [quote]: "
        ).strip()

        if not type_raw:
            types = ["quote"]
        else:
            types = [t.strip().lower() for t in type_raw.split(",") if t.strip()]

        invalid = [t for t in types if t not in ALLOWED_TYPES]
        if invalid:
            print("❌ TYPE non validi:", ", ".join(invalid))
            print("   TYPE ammessi:", ", ".join(sorted(ALLOWED_TYPES)))
            print("   Riprova.\n")
            continue

        break

    # TAGS
    tags_raw = input("TAGS (lista separata da virgola, opzionale): ").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    # LINK (es. articolo, tweet, ecc.)
    link = input("LINK (opzionale, es. articolo/pagina): ").strip()
    if not link:
        link = None

    # MEDIA_URL (immagine/video)
    media_url = input("MEDIA URL (opzionale, .png/.jpg/.jpeg/.webp/.gif/.mp4/.webm): ").strip()
    if not media_url:
        media_url = None

    # se non hai messo MEDIA_URL ma il LINK è chiaramente un media, lo uso come media
    if not media_url and link and is_media_url(link):
        media_url = link

    # DATA (solo nel JSON, NON più nel contenuto Nostr)
    default_date = holocene_today()
    date_str = input(f"DATE (formato 12025-11-18) [{default_date}]: ").strip()
    if not date_str:
        date_str = default_date

    # NOSTR_KIND dedotto dalla TYPE principale
    primary_type = types[0]
    nostr_kind = TYPE_KIND_MAP.get(primary_type, nostr_kind_default)

    # QOTE / testo
    print("Testo / QOTE (linee multiple, invio su riga vuota per terminare):")
    q_lines = []
    while True:
        line = input()
        if line == "":
            break
        q_lines.append(line)

    if not q_lines:
        qote = ""
    elif len(q_lines) == 1:
        qote = q_lines[0]
    else:
        qote = q_lines  # mantiene array come nel tuo schema

    diid = next_diid(garden)

    entry = {
        "TYPE": types,
        "TAGS": tags,
        "DATE": date_str,      # resta nel JSON
        "DONE": True,
        "DIID": diid,
        "NOSTR_KIND": nostr_kind,
    }

    if link:
        entry["LINK"] = link
    if media_url:
        entry["MEDIA_URL"] = media_url
    if qote != "":
        entry["QOTE"] = qote

    return title, entry


def should_publish(entry: dict, min_diid: int | None) -> bool:
    if not entry.get("DONE"):
        return False
    posted_to_nostr = entry.get("POSTED_TO_NOSTR", False)
    posted_to_bluesky = entry.get("POSTED_TO_BLUESKY", False)
    if posted_to_nostr and posted_to_bluesky:
        return False

    diid = entry.get("DIID")
    if min_diid is not None and isinstance(diid, int) and diid < min_diid:
        return False

    return True


# ========================
# MODALITÀ MAIN
# ========================

def mode_create_and_publish(
    repo_path,
    json_path,
    nsec,
    relays,
    nostr_kind_default,
    bsky_identifier,
    bsky_app_password,
):
    garden = load_garden(json_path)

    # 1) Creazione entry
    title, entry = create_entry_interactive(garden, nostr_kind_default)

    # 2) Format contenuto per Nostr
    content = format_entry_content(title, entry)
    print("\n--- Anteprima contenuto Nostr ---")
    print(content)
    print("---------------------------------")

    confirm = input("Pubblico su Nostr + Bluesky? [Y/n]: ").strip().lower()
    if confirm and confirm not in ("y", "yes"):
        entry["POSTED_TO_NOSTR"] = False
        entry["POSTED_TO_BLUESKY"] = False
        garden[title] = entry
        save_garden(json_path, garden)
        print("Pubblicazione social saltata. Nota salvata in data.json.")
        return

    # 3) Pubblica su Nostr
    kind = entry["NOSTR_KIND"]
    event_id = publish_to_nostr(content, nsec, relays, kind=kind)
    print(f"✓ Pubblicato su Nostr. Event ID: {event_id}")

    # 4) Pubblica su Bluesky
    bsky_uri, bsky_cid, bsky_text, bsky_embed_type, bsky_media_uploaded = publish_to_bluesky(
        content,
        title,
        entry,
        repo_path,
        bsky_identifier,
        bsky_app_password,
    )
    print(f"✓ Pubblicato su Bluesky. URI: {bsky_uri}")

    # 5) Aggiorna entry con info social e scrivi su JSON
    entry["POSTED_TO_NOSTR"] = True
    entry["NOSTR_EVENT_ID"] = event_id
    entry["POSTED_TO_BLUESKY"] = True
    entry["BLUESKY_URI"] = bsky_uri
    entry["BLUESKY_CID"] = bsky_cid
    entry["BLUESKY_TEXT"] = bsky_text
    if bsky_embed_type:
        entry["BLUESKY_EMBED_TYPE"] = bsky_embed_type
    if bsky_media_uploaded:
        entry["BLUESKY_MEDIA_UPLOADED"] = True

    garden[title] = entry
    save_garden(json_path, garden)
    run_build(repo_path)

    # 6) Git commit + push
    git_commit_and_push(
        repo_path,
        message=f"Add garden note + Nostr/Bluesky post: {title}",
        json_path=json_path,
    )
    print("✅ Garden aggiornato e pushato su git.")

def mode_publish_pending(
    repo_path,
    json_path,
    nsec,
    relays,
    min_diid,
    bsky_identifier,
    bsky_app_password,
):
    garden = load_garden(json_path)
    published_any = False

    print(f"=== Pubblico pending (MIN_DIID={min_diid}) ===")

    for title, entry in garden.items():
        if not isinstance(entry, dict):
            continue
        if not should_publish(entry, min_diid):
            continue

        kind = entry.get("NOSTR_KIND", 1)
        missing_nostr = not entry.get("POSTED_TO_NOSTR", False)
        missing_bluesky = not entry.get("POSTED_TO_BLUESKY", False)

        print(
            f"▶ Pubblico: {title} "
            f"(DIID={entry.get('DIID')} kind={kind} "
            f"nostr={missing_nostr} bluesky={missing_bluesky})"
        )

        content = format_entry_content(title, entry)
        if missing_nostr:
            event_id = publish_to_nostr(content, nsec, relays, kind=kind)
            print(f"   ✓ Nostr Event ID: {event_id}")
            entry["POSTED_TO_NOSTR"] = True
            entry["NOSTR_EVENT_ID"] = event_id
            published_any = True

        if missing_bluesky:
            bsky_uri, bsky_cid, bsky_text, bsky_embed_type, bsky_media_uploaded = publish_to_bluesky(
                content,
                title,
                entry,
                repo_path,
                bsky_identifier,
                bsky_app_password,
            )
            print(f"   ✓ Bluesky URI: {bsky_uri}")
            entry["POSTED_TO_BLUESKY"] = True
            entry["BLUESKY_URI"] = bsky_uri
            entry["BLUESKY_CID"] = bsky_cid
            entry["BLUESKY_TEXT"] = bsky_text
            if bsky_embed_type:
                entry["BLUESKY_EMBED_TYPE"] = bsky_embed_type
            if bsky_media_uploaded:
                entry["BLUESKY_MEDIA_UPLOADED"] = True
            published_any = True

    if not published_any:
        print("Niente da pubblicare: nessuna entry pending rispettando MIN_DIID.")
        return

    save_garden(json_path, garden)
    run_build(repo_path)
    git_commit_and_push(
        repo_path,
        message="Publish pending garden notes to Nostr and Bluesky",
        json_path=json_path,
    )
    print("✅ Garden aggiornato e pushato su git.")


def main():
    (
        repo_path,
        json_path,
        nsec,
        relays,
        nostr_kind_default,
        min_diid,
        bsky_identifier,
        bsky_app_password,
    ) = load_config()

    if len(sys.argv) > 1 and sys.argv[1] == "--pending":
        mode_publish_pending(
            repo_path,
            json_path,
            nsec,
            relays,
            min_diid,
            bsky_identifier,
            bsky_app_password,
        )
    else:
        mode_create_and_publish(
            repo_path,
            json_path,
            nsec,
            relays,
            nostr_kind_default,
            bsky_identifier,
            bsky_app_password,
        )


if __name__ == "__main__":
    main()
