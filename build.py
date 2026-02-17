#!/usr/bin/env python3
import argparse
import hashlib
import html
import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build static SEO pages from data.json."
    )
    parser.add_argument("--data", default="data.json", help="Input JSON file")
    parser.add_argument(
        "--index-template",
        default="index.html",
        help="Index HTML template to update",
    )
    parser.add_argument(
        "--archive",
        default="archivio.html",
        help="Archive HTML output file with all notes",
    )
    parser.add_argument("--notes-dir", default="notes", help="Notes output directory")
    parser.add_argument("--sitemap", default="sitemap.xml", help="Sitemap output file")
    parser.add_argument(
        "--site-url",
        default="",
        help="Public site base URL (e.g. https://example.com)",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid JSON root in {path}: expected object")
    return data


def discover_site_url(repo_path: Path, provided: str) -> str:
    if provided.strip():
        return provided.strip().rstrip("/")
    env_url = os.environ.get("GARDEN_SITE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    cname = repo_path / "CNAME"
    if cname.exists():
        domain = cname.read_text(encoding="utf-8").strip()
        if domain:
            return f"https://{domain}".rstrip("/")
    return ""


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if slug:
        return slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"note-{digest}"


def coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str) and x.strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def date_sort_key(value) -> tuple:
    if not isinstance(value, str):
        return (0, 0, 0)
    m = re.match(r"^(\d{4,5})-(\d{2})-(\d{2})$", value.strip())
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def entry_sort_key(item):
    _title, entry = item
    diid = entry.get("DIID")
    if isinstance(diid, int):
        return (2, diid)
    return (1, date_sort_key(entry.get("DATE")))


def strip_quote_prefix(line: str) -> str:
    text = line.strip()
    if text.startswith(">"):
        return text[1:].strip()
    return text


def collect_text_lines(entry: dict) -> list[str]:
    lines = []
    for field in ("QOTE", "NOTE", "PROG", "TERM"):
        for v in coerce_list(entry.get(field)):
            clean = strip_quote_prefix(v)
            if clean:
                lines.append(clean)
    return lines


def summarize_text(entry: dict, limit: int = 260) -> str:
    text = " ".join(collect_text_lines(entry)).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def holocene_to_iso(date_value: str) -> str | None:
    if not isinstance(date_value, str):
        return None
    m = re.match(r"^(\d{4,5})-(\d{2})-(\d{2})$", date_value.strip())
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))
    day = int(m.group(3))
    if year >= 10000:
        year -= 10000
    if year < 1 or month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def entry_title(title: str) -> str:
    return html.escape(title, quote=True)


def render_index_cards(entries: list[tuple[str, dict, str]], limit: int | None = None) -> str:
    render_entries = entries if limit is None else entries[:limit]
    chunks = []
    for title, entry, slug in render_entries:
        title_html = entry_title(title)
        note_href = f"notes/{quote(slug)}.html"
        type_text = ", ".join(coerce_list(entry.get("TYPE")))
        tags_text = ", ".join(coerce_list(entry.get("TAGS")))
        date_text = html.escape(str(entry.get("DATE", "")), quote=True)
        summary = html.escape(summarize_text(entry), quote=True)
        link = entry.get("LINK")
        media = entry.get("MEDIA_URL")

        chunks.append('<article class="article">')
        chunks.append(
            f'<header class="article-title"><a class="article-link" href="{note_href}">{title_html}</a></header>'
        )
        chunks.append('<div class="article-containerlower">')
        if date_text:
            chunks.append(
                f'<div class="article-row"><strong>Date:</strong> <span>{date_text}</span></div>'
            )
        if type_text:
            chunks.append(
                f'<div class="article-row"><strong>Type:</strong> <span>{html.escape(type_text)}</span></div>'
            )
        if tags_text:
            chunks.append(
                f'<div class="article-row"><strong>Tags:</strong> <span>{html.escape(tags_text)}</span></div>'
            )
        if summary:
            chunks.append(f"<blockquote>{summary}</blockquote>")
        if isinstance(link, str) and link.strip():
            safe_link = html.escape(link.strip(), quote=True)
            chunks.append(
                f'<div class="article-row"><a class="article-link" href="{safe_link}" rel="noopener noreferrer">Source</a></div>'
            )
        if isinstance(media, str) and media.strip() and re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", media.strip(), re.I):
            safe_media = html.escape(media.strip(), quote=True)
            chunks.append(
                f'<div class="article-row"><img class="article-image-img" src="{safe_media}" alt="{title_html}"></div>'
            )
        chunks.append("</div>")
        chunks.append("</article>")
    return "\n".join(chunks)


def inject_main_content(index_html: str, rendered: str) -> str:
    pattern = re.compile(r"(<main\b[^>]*>)(.*?)(</main>)", flags=re.S | re.I)
    def repl(match: re.Match) -> str:
        return f"{match.group(1)}\n<!-- Generated by build.py -->\n{rendered}\n{match.group(3)}"

    updated, count = pattern.subn(repl, index_html, count=1)
    if count != 1:
        raise RuntimeError("Could not find a single <main>...</main> block in index template.")
    return updated


def ensure_indexable_meta(index_html: str) -> str:
    pattern = re.compile(
        r'<meta\s+name=["\']robots["\']\s+content=["\'][^"\']*["\']\s*/?>',
        flags=re.I,
    )
    replacement = '<meta name="robots" content="index, follow">'
    updated, count = pattern.subn(replacement, index_html, count=1)
    if count:
        return updated
    head_close = re.search(r"</head>", index_html, flags=re.I)
    if not head_close:
        return index_html
    pos = head_close.start()
    return index_html[:pos] + "  " + replacement + "\n" + index_html[pos:]


def render_note_page(title: str, entry: dict, slug: str, site_url: str) -> str:
    page_title = f"{title} | Digital Garden"
    escaped_title = html.escape(title, quote=True)
    escaped_page_title = html.escape(page_title, quote=True)
    escaped_desc = html.escape(summarize_text(entry, limit=300) or title, quote=True)
    note_path = f"/notes/{quote(slug)}.html"
    canonical = f"{site_url}{note_path}" if site_url else note_path
    canonical_html = html.escape(canonical, quote=True)
    article_text = " ".join(collect_text_lines(entry)).strip()
    iso_date = holocene_to_iso(str(entry.get("DATE", "")).strip())
    author_name = os.environ.get("GARDEN_AUTHOR_NAME", "Perculato").strip() or "Perculato"
    logo_url = f"{site_url}/sndldg.png" if site_url else "/sndldg.png"
    schema_obj = {
        "@context": "https://schema.org",
        "@type": ["BlogPosting", "Article"],
        "headline": title,
        "description": summarize_text(entry, limit=300) or title,
        "mainEntityOfPage": canonical,
        "url": canonical,
        "author": {
            "@type": "Person",
            "name": author_name,
            "url": site_url or canonical,
        },
        "publisher": {
            "@type": "Organization",
            "name": author_name,
            "logo": {
                "@type": "ImageObject",
                "url": logo_url,
            },
        },
    }
    if iso_date:
        schema_obj["datePublished"] = iso_date
        schema_obj["dateModified"] = iso_date
    tags = coerce_list(entry.get("TAGS"))
    if tags:
        schema_obj["keywords"] = ", ".join(tags)
    if article_text:
        schema_obj["articleBody"] = article_text
    media = entry.get("MEDIA_URL")
    if isinstance(media, str) and media.strip() and re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", media.strip(), re.I):
        schema_obj["image"] = media.strip()
    schema_json = html.escape(json.dumps(schema_obj, ensure_ascii=False), quote=False)

    details = []
    date_value = entry.get("DATE")
    if date_value:
        details.append(f"<p><strong>Date:</strong> {html.escape(str(date_value))}</p>")
    types = coerce_list(entry.get("TYPE"))
    if types:
        details.append(f"<p><strong>Type:</strong> {html.escape(', '.join(types))}</p>")
    tags = coerce_list(entry.get("TAGS"))
    if tags:
        details.append(f"<p><strong>Tags:</strong> {html.escape(', '.join(tags))}</p>")
    link = entry.get("LINK")
    if isinstance(link, str) and link.strip():
        safe_link = html.escape(link.strip(), quote=True)
        details.append(
            f'<p><strong>Source:</strong> <a href="{safe_link}" rel="noopener noreferrer">{safe_link}</a></p>'
        )
    media = entry.get("MEDIA_URL")
    if isinstance(media, str) and media.strip():
        safe_media = html.escape(media.strip(), quote=True)
        details.append(
            f'<p><strong>Media:</strong> <a href="{safe_media}" rel="noopener noreferrer">{safe_media}</a></p>'
        )
        if re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", media.strip(), re.I):
            details.append(f'<p><img src="{safe_media}" alt="{escaped_title}"></p>')

    text_blocks = []
    for line in collect_text_lines(entry):
        text_blocks.append(f"<p>{html.escape(line)}</p>")

    details_html = "\n".join(details)
    body_html = "\n".join(text_blocks) or "<p>No text content available.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escaped_page_title}</title>
  <meta name="description" content="{escaped_desc}">
  <link rel="canonical" href="{canonical_html}">
  <meta property="og:title" content="{escaped_page_title}">
  <meta property="og:description" content="{escaped_desc}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{canonical_html}">
  <script type="application/ld+json">{schema_json}</script>
  <link rel="stylesheet" href="../css/style.css">
</head>
<body>
  <nav><a href="../index.html">Home</a></nav>
  <div class="container">
    <main>
      <article class="article">
        <header class="article-title">{escaped_title}</header>
        <div class="article-containerlower">
          {details_html}
          {body_html}
        </div>
      </article>
    </main>
  </div>
</body>
</html>
"""


def render_sitemap(entries: list[tuple[str, dict, str]], site_url: str) -> str:
    if not site_url:
        return ""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    lines.append("  <url>")
    lines.append(f"    <loc>{html.escape(site_url + '/')}</loc>")
    lines.append("  </url>")
    for _title, _entry, slug in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{html.escape(site_url + '/notes/' + quote(slug) + '.html')}</loc>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    repo_path = Path.cwd()
    data_path = (repo_path / args.data).resolve()
    index_path = (repo_path / args.index_template).resolve()
    archive_path = (repo_path / args.archive).resolve()
    notes_dir = (repo_path / args.notes_dir).resolve()
    sitemap_path = (repo_path / args.sitemap).resolve()

    garden = load_json(data_path)
    sorted_items = sorted(garden.items(), key=entry_sort_key, reverse=True)

    used_slugs = set()
    entries = []
    for title, entry in sorted_items:
        if not isinstance(entry, dict):
            continue
        base = slugify(title)
        slug = base
        i = 2
        while slug in used_slugs:
            slug = f"{base}-{i}"
            i += 1
        used_slugs.add(slug)
        entries.append((title, entry, slug))

    notes_dir.mkdir(parents=True, exist_ok=True)

    site_url = discover_site_url(repo_path, args.site_url)
    expected_files = set()
    for title, entry, slug in entries:
        note_html = render_note_page(title, entry, slug, site_url)
        note_file = notes_dir / f"{slug}.html"
        note_file.write_text(note_html, encoding="utf-8")
        expected_files.add(note_file.resolve())

    for old in notes_dir.glob("*.html"):
        if old.resolve() not in expected_files:
            old.unlink()

    index_source = index_path.read_text(encoding="utf-8")
    rendered_index = render_index_cards(entries, limit=10)
    updated_index = inject_main_content(index_source, rendered_index)
    updated_index = ensure_indexable_meta(updated_index)
    index_path.write_text(updated_index, encoding="utf-8")

    rendered_archive = render_index_cards(entries)
    archive_html = inject_main_content(index_source, rendered_archive)
    archive_html = ensure_indexable_meta(archive_html)
    archive_path.write_text(archive_html, encoding="utf-8")

    sitemap = render_sitemap(entries, site_url)
    if sitemap:
        sitemap_path.write_text(sitemap, encoding="utf-8")

    print(
        f"Build completed: index={index_path.name}, notes={len(entries)} pages in {notes_dir.name}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
