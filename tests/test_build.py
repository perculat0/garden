import json
import unittest

import build


class BuildTests(unittest.TestCase):
    def test_sort_garden_items_by_date_desc_then_diid(self):
        garden = {
            "older": {"DATE": "12024-01-01", "DIID": 100},
            "newer_a": {"DATE": "12026-02-10", "DIID": 1},
            "newer_b": {"DATE": "12026-02-10", "DIID": 2},
            "no_date": {"DIID": 999},
        }

        ordered = [title for title, _entry in build.sort_garden_items(garden)]
        self.assertEqual(ordered[0], "newer_b")
        self.assertEqual(ordered[1], "newer_a")
        self.assertEqual(ordered[2], "older")
        self.assertEqual(ordered[3], "no_date")

    def test_render_index_cards_limit(self):
        entries = []
        for i in range(15):
            entries.append((f"title-{i}", {"DATE": "12026-01-01"}, f"slug-{i}"))

        html_limited = build.render_index_cards(entries, limit=10)
        html_all = build.render_index_cards(entries)

        self.assertEqual(html_limited.count('<article class="article">'), 10)
        self.assertEqual(html_all.count('<article class="article">'), 15)

    def test_note_schema_contains_article_and_publisher_logo(self):
        note_html = build.render_note_page(
            title="Hello",
            entry={
                "DATE": "12026-02-17",
                "TAGS": ["x", "y"],
                "QOTE": "hello world",
                "MEDIA_URL": "https://example.com/image.png",
            },
            slug="hello",
            site_url="https://example.com",
        )

        marker = '<script type="application/ld+json">'
        start = note_html.index(marker) + len(marker)
        end = note_html.index("</script>", start)
        payload = note_html[start:end]
        obj = json.loads(payload)

        self.assertIn("BlogPosting", obj["@type"])
        self.assertIn("Article", obj["@type"])
        self.assertEqual(obj["publisher"]["logo"]["url"], "https://example.com/sndldg.png")
        self.assertEqual(obj["datePublished"], "2026-02-17")


if __name__ == "__main__":
    unittest.main()
