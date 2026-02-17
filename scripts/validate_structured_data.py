#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


def extract_json_ld(html: str) -> list[dict]:
    pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        flags=re.I | re.S,
    )
    objects = []
    for raw in pattern.findall(html):
        payload = raw.strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON-LD payload: {exc}") from exc
        if isinstance(parsed, list):
            objects.extend(x for x in parsed if isinstance(x, dict))
        elif isinstance(parsed, dict):
            objects.append(parsed)
    return objects


def has_type(obj: dict, type_name: str) -> bool:
    value = obj.get("@type")
    if isinstance(value, str):
        return value == type_name
    if isinstance(value, list):
        return type_name in value
    return False


def require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def validate_index(path: Path):
    html = path.read_text(encoding="utf-8")
    objs = extract_json_ld(html)
    require(objs, f"{path}: no JSON-LD found")

    person = next((o for o in objs if has_type(o, "Person")), None)
    website = next((o for o in objs if has_type(o, "WebSite")), None)

    require(person is not None, f"{path}: missing Person JSON-LD")
    require(website is not None, f"{path}: missing WebSite JSON-LD")
    same_as = person.get("sameAs")
    require(isinstance(same_as, list) and len(same_as) >= 4, f"{path}: Person.sameAs must contain at least 4 URLs")
    publisher = website.get("publisher", {})
    logo = publisher.get("logo", {}) if isinstance(publisher, dict) else {}
    logo_url = logo.get("url") if isinstance(logo, dict) else None
    require(isinstance(logo_url, str) and logo_url.strip(), f"{path}: WebSite.publisher.logo.url missing")


def validate_note(path: Path):
    html = path.read_text(encoding="utf-8")
    objs = extract_json_ld(html)
    require(objs, f"{path}: no JSON-LD found")

    article = next(
        (
            o
            for o in objs
            if has_type(o, "BlogPosting") or has_type(o, "Article")
        ),
        None,
    )
    require(article is not None, f"{path}: missing BlogPosting/Article JSON-LD")
    require(article.get("headline"), f"{path}: missing headline")
    require(article.get("url"), f"{path}: missing url")
    author = article.get("author")
    require(isinstance(author, dict) and author.get("name"), f"{path}: missing author.name")
    publisher = article.get("publisher")
    require(isinstance(publisher, dict) and publisher.get("name"), f"{path}: missing publisher.name")
    logo = publisher.get("logo")
    require(isinstance(logo, dict) and logo.get("url"), f"{path}: missing publisher.logo.url")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate JSON-LD structured data for index and note pages."
    )
    parser.add_argument("--index", default="index.html", help="Index HTML path")
    parser.add_argument("--notes-dir", default="notes", help="Notes directory path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index_path = Path(args.index)
    notes_dir = Path(args.notes_dir)

    validate_index(index_path)
    note_files = sorted(notes_dir.glob("*.html"))
    require(note_files, f"{notes_dir}: no note pages found")
    for note in note_files:
        validate_note(note)

    print(f"Structured data valid: index + {len(note_files)} notes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        raise SystemExit(1)
