"""Tests for build.py.  Run: python3 -B -m unittest discover -s tests -t ."""

import datetime as dt
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import build

REPO = Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 12, 5)
BASE = "https://example.org/songsbyjoel/"


def links_data():
    return {
        "schema_version": 1,
        "streaming": [
            {"id": "spotify", "label": "Spotify", "url": "https://open.spotify.com/artist/x"},
            {"id": "bandcamp", "label": "Bandcamp", "url": "https://joel.bandcamp.com"},
        ],
        "social": [{"id": "instagram", "label": "Instagram", "url": "https://instagram.com/x"}],
        "merch_url": "https://shop.songsbyjoel.com",
    }


def release(rid, date, **extra):
    item = {"id": rid, "title": rid.title(), "type": "single", "release_date": date,
            "cover": "assets/covers/test.svg", "links": {"spotify": f"https://open.spotify.com/track/{rid}"}}
    item.update(extra)
    return item


def show(sid, date, **extra):
    item = {"id": sid, "date": date, "venue": f"Venue {sid}", "city": "Helsingborg",
            "country": "SE", "tickets": {"type": "free"}}
    item.update(extra)
    return item


class Fixture:
    """A throwaway project folder: data/, assets/, and the real templates/."""

    def __init__(self, links=None, releases=None, shows=None):
        self.dir = Path(tempfile.mkdtemp(prefix="songsbyjoel-test-"))
        (self.dir / "data").mkdir()
        (self.dir / "assets" / "covers").mkdir(parents=True)
        (self.dir / "assets" / "style.css").write_text("body{}")
        (self.dir / "assets" / "covers" / "test.svg").write_text("<svg/>")
        self.write("links.json", links if links is not None else links_data())
        self.write("releases.json", {"schema_version": 1, "releases": releases or []})
        self.write("shows.json", {"schema_version": 1, "shows": shows or []})

    def write(self, name, data):
        text = data if isinstance(data, str) else json.dumps(data)
        (self.dir / "data" / name).write_text(text, encoding="utf-8")

    def load(self):
        return build.load_data(self.dir / "data", assets_root=self.dir)

    def build(self, today=TODAY, base_url=BASE):
        out = self.dir / "_site"
        build.build(data_dir=self.dir / "data", templates_dir=REPO / "templates",
                    assets_dir=self.dir / "assets", out_dir=out, base_url=base_url, today=today)
        return out

    def page(self, rel, **kw):
        return (self.build(**kw) / rel).read_text(encoding="utf-8")

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class FixtureTest(unittest.TestCase):
    def make(self, **kw):
        fx = Fixture(**kw)
        self.addCleanup(fx.cleanup)
        return fx

    def assertInvalid(self, fx, *expected):
        with self.assertRaises(build.ValidationError) as ctx:
            fx.load()
        message = str(ctx.exception)
        for part in expected:
            self.assertIn(part, message)
        return message


class TestRealData(unittest.TestCase):
    def test_repo_data_builds(self):
        out = Path(tempfile.mkdtemp(prefix="songsbyjoel-real-"))
        self.addCleanup(shutil.rmtree, out, True)
        build.build(out_dir=out / "_site", today=TODAY)
        for rel in ("index.html", "music/index.html", "shows/index.html", "404.html",
                    "sitemap.xml", "robots.txt", "assets/style.css", "assets/share.png"):
            self.assertTrue((out / "_site" / rel).is_file(), rel)
        self.assertEqual((out / "_site" / "CNAME").read_text(), "songsbyjoel.com\n")
        self.assertIn('href="/shows/"', (out / "_site" / "404.html").read_text())

    def test_check_command(self):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(build.main(["--check"]), 0)
        self.assertIn("Data OK", out.getvalue())


class TestShows(FixtureTest):
    def test_upcoming_and_past_split_and_order(self):
        shows = [
            show("far", "2027-03-01"),
            show("today", "2026-12-05", time="20:00"),
            show("old", "2026-01-10"),
            show("yesterday", "2026-12-04"),
            show("soon", "2026-12-20"),
        ]
        data, _ = self.make(shows=shows).load()
        upcoming, past = build.split_shows(data["shows"], TODAY)
        self.assertEqual([s["id"] for s in upcoming], ["today", "soon", "far"])
        self.assertEqual([s["id"] for s in past], ["yesterday", "old"])

    def test_shows_page(self):
        fx = self.make(shows=[show("past", "2026-11-01"), show("next", "2026-12-24", time="19:30"),
                              show("paid", "2027-01-15", tickets={"type": "link", "url": "https://tickets.example.org/a"})])
        html = fx.page("shows/index.html")
        upcoming, past = html.split("Past shows")
        self.assertLess(upcoming.index("show-next"), upcoming.index("show-paid"))
        self.assertNotIn("show-past", upcoming)
        self.assertIn("show-past", past)
        self.assertIn("<details", html)
        self.assertIn("Free, no tickets needed", html)
        self.assertNotIn("Free, no tickets needed", past)
        self.assertRegex(html, r'href="https://tickets\.example\.org/a"[^>]*>Tickets</a>')
        self.assertIn('datetime="2026-12-24T19:30"', html)

    def test_no_shows(self):
        html = self.make().page("shows/index.html")
        self.assertIn("No upcoming shows right now", html)
        self.assertNotIn("Past shows", html)

    def test_only_past_shows(self):
        html = self.make(shows=[show("old", "2025-05-05")]).page("shows/index.html")
        self.assertIn("No upcoming shows right now", html)
        self.assertIn("Past shows", html)

    def test_home_latest_release_buttons_first(self):
        links = {"bandcamp": "https://x.bandcamp.com/track/a", "apple_music": "https://music.apple.com/se/album/a/1",
                 "spotify": "https://open.spotify.com/album/79h1TX1O8Bu82rtGW6mkVz"}
        services = links_data()
        services["streaming"].append({"id": "apple_music", "label": "Apple Music", "url": "https://music.apple.com/se/artist/x/1"})
        html = self.make(links=services, releases=[release("a", "2026-12-01", links=links)]).page("index.html")
        latest = html.split('id="latest-heading"')[1].split("</section>")[0]
        # Spotify and Apple Music come first as primary buttons, before the player and other services.
        self.assertLess(latest.index('class="is-primary"><a class="button" href="https://open.spotify.com/album/79h1TX1O8Bu82rtGW6mkVz"'),
                        latest.index("Bandcamp"))
        self.assertIn('class="is-primary"><a class="button" href="https://music.apple.com/se/album/a/1"', latest)
        self.assertLess(latest.index("Bandcamp"), latest.index('class="player"'))
        self.assertIn('fetchpriority="high"', latest)

    def test_home_merch(self):
        html = self.make().page("index.html")
        merch = html.split('id="merch-heading"')[1].split("</section>")[0]
        self.assertIn('href="https://shop.songsbyjoel.com/products/walking-billboard-tee"', merch)
        self.assertIn("Walking Billboard Tee", merch)
        self.assertNotIn("kr", merch)

    def test_next_show_on_home(self):
        fx = self.make(shows=[show("later", "2027-01-01"), show("next", "2026-12-05")])
        html = fx.page("index.html")
        self.assertIn("show-next", html)
        self.assertNotIn("show-later", html)
        self.assertIn('href="./shows/"', html)

    def test_shows_schema_v2_end_time_and_tour(self):
        fx = self.make()
        fx.write("shows.json", {"schema_version": 2, "shows": [
            show("tour", "2026-12-24", time="19:00", end_time="21:30", tour="Some <Tour>")]})
        html = fx.page("shows/index.html")
        self.assertIn('<span class="hours">19:00-21:30</span>', html)
        self.assertIn('<p class="tour">Some &lt;Tour&gt;</p>', html)

    def test_show_card_text(self):
        fx = self.make(shows=[show("home", "2026-12-24", venue="Hall", city="Lund"),
                              show("away", "2027-01-15", venue="Club", city="Copenhagen", country="DK")])
        html = fx.page("shows/index.html")
        self.assertIn('Hall, <span class="place">Lund</span></h3>', html)
        self.assertIn(">Thu 24 Dec</time>", html)
        self.assertIn('Club, <span class="place">Copenhagen, Denmark</span>', html)
        self.assertIn(">Fri 15 Jan 2027</time>", html)

    def test_shows_schema_v2_fields_checked(self):
        fx = self.make()
        fx.write("shows.json", {"schema_version": 2, "shows": [show("s", "2026-12-24", end_time="21:00")]})
        self.assertInvalid(fx, 'field "end_time"', 'start "time"')
        fx = self.make()
        fx.write("shows.json", {"schema_version": 2, "shows": [show("s", "2026-12-24", time="19:00", end_time="late")]})
        self.assertInvalid(fx, 'field "end_time"', "HH:MM")
        # Version 1 does not know the new fields.
        self.assertInvalid(self.make(shows=[show("s", "2026-12-24", tour="x")]), 'unknown field "tour"')

    def test_home_without_shows_has_no_next_show(self):
        self.assertNotIn("Next show", self.make().page("index.html"))


class TestReleases(FixtureTest):
    def test_future_release_hidden_and_latest_chosen(self):
        releases = [release("old", "2025-06-01"), release("newest", "2026-12-05"),
                    release("future", "2026-12-06"), release("middle", "2026-03-01")]
        fx = self.make(releases=releases)
        data, _ = fx.load()
        self.assertEqual(build.latest_release(data["releases"], TODAY)["id"], "newest")
        self.assertEqual([r["id"] for r in build.visible_releases(data["releases"], TODAY)],
                         ["newest", "middle", "old"])
        home = fx.page("index.html")
        self.assertIn("release-newest", home)
        self.assertNotIn("release-old", home)
        music = fx.page("music/index.html")
        self.assertNotIn("release-future", music)
        self.assertNotIn("Future", music)
        order = [m.group(1) for m in re.finditer(r'id="release-([a-z-]+)"', music)]
        self.assertEqual(order, ["newest", "middle", "old"])

    def test_future_release_appears_on_release_day(self):
        fx = self.make(releases=[release("future", "2026-12-06")])
        self.assertNotIn("release-future", fx.page("index.html", today=TODAY))
        self.assertIn("release-future", fx.page("index.html", today=dt.date(2026, 12, 6)))

    def test_only_existing_links_shown_in_service_order(self):
        rel = release("song", "2026-01-01", links={"bandcamp": "https://joel.bandcamp.com/track/song",
                                                   "spotify": "https://open.spotify.com/track/song"})
        html = self.make(releases=[rel]).page("music/index.html")
        card = html[html.index('id="release-song"'):]
        self.assertLess(card.index(">Spotify<"), card.index(">Bandcamp<"))
        rel = release("solo", "2026-01-01", links={"bandcamp": "https://joel.bandcamp.com/track/solo"})
        card = self.make(releases=[rel]).page("index.html")
        card = card[card.index('id="release-solo"'):card.index("</article>")]
        self.assertNotIn("Spotify", card)

    def test_no_releases(self):
        self.assertIn("New music is on its way", self.make().page("index.html"))


class TestSpotifyPlayer(FixtureTest):
    TRACK = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"

    def test_embed_url(self):
        self.assertEqual(build.spotify_embed(self.TRACK),
                         ("https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT", 152))
        self.assertEqual(build.spotify_embed(
            "https://open.spotify.com/intl-sv/album/4cOdK2wGLETKBW3PvgPWqT?si=abc"),
            ("https://open.spotify.com/embed/album/4cOdK2wGLETKBW3PvgPWqT", 352))
        for url in (None, "", "https://example.com/PLACEHOLDER-release-spotify",
                    "https://open.spotify.com/track/short", "http://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
                    "https://evil.example/open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"):
            self.assertIsNone(build.spotify_embed(url), url)

    def test_player_on_home_only_and_loads_nothing_up_front(self):
        fx = self.make(releases=[release("song", "2026-01-01", links={"spotify": self.TRACK})])
        home = fx.page("index.html")
        self.assertIn('class="player"', home)
        self.assertIn('data-embed="https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT"', home)
        self.assertIn(f'class="player-start" href="{self.TRACK}"', home)
        self.assertNotIn("<iframe", home)
        self.assertNotIn("embed/track/4cOdK2wGLETKBW3PvgPWqT", fx.page("music/index.html"))

    def test_no_player_without_embeddable_link(self):
        rel = release("solo", "2026-01-01", links={"bandcamp": "https://joel.bandcamp.com/track/solo"})
        self.assertNotIn("embed/track/", self.make(releases=[rel]).page("index.html"))


class TestConsent(FixtureTest):
    def test_banner_on_every_page_hidden_until_js(self):
        fx = self.make()
        for rel in ("index.html", "music/index.html", "shows/index.html", "404.html"):
            html = fx.page(rel)
            self.assertIn('<div class="consent" role="region" aria-labelledby="consent-heading" hidden>', html, rel)
            self.assertIn('data-consent="yes">Allow</button>', html, rel)
            self.assertIn('data-consent="no">No thanks</button>', html, rel)
            self.assertIn('class="cookie-settings" type="button" hidden', html, rel)
            self.assertNotIn("<iframe", html, rel)


class TestPlaylist(FixtureTest):
    EMBED = 'data-embed="https://open.spotify.com/embed/playlist/1STR4IBNDJNFmZtll9Xwew" data-height="352"'

    def test_playlist_on_home_and_music(self):
        fx = self.make()
        for rel in ("index.html", "music/index.html"):
            html = fx.page(rel)
            self.assertIn("The Joel Collection", html, rel)
            self.assertIn(self.EMBED, html, rel)
            self.assertIn(f'class="player-start" href="{build.PLAYLIST_URL}"', html, rel)
            self.assertNotIn("Save on Spotify", html, rel)
            self.assertNotIn("<iframe", html, rel)
            self.assertNotIn("si=", html, rel)

    def test_playlist_not_on_shows(self):
        self.assertNotIn("The Joel Collection", self.make().page("shows/index.html"))


class TestValidation(FixtureTest):
    def test_missing_field(self):
        rel = release("song", "2026-01-01")
        del rel["title"]
        self.assertInvalid(self.make(releases=[rel]),
                           "data/releases.json", 'releases[0] (id "song")', 'missing field "title"')

    def test_bad_date(self):
        self.assertInvalid(self.make(shows=[show("s", "2026-13-01")]),
                           "data/shows.json", 'shows[0] (id "s")', 'field "date"', "2026-13-01", "YYYY-MM-DD")
        self.assertInvalid(self.make(shows=[show("s", "5/12/2026")]), 'field "date"')

    def test_bad_url(self):
        links = links_data()
        links["streaming"][1]["url"] = "http://joel.bandcamp.com"
        self.assertInvalid(self.make(links=links), "data/links.json", 'streaming[1] (id "bandcamp")',
                           'field "url"', "https://")
        links["streaming"][1]["url"] = "not a url"
        self.assertInvalid(self.make(links=links), 'field "url"')

    def test_unknown_schema_version(self):
        fx = self.make()
        fx.write("shows.json", {"schema_version": 3, "shows": []})
        self.assertInvalid(fx, "data/shows.json", "schema_version", "3")
        fx = self.make()
        fx.write("releases.json", {"schema_version": 2, "releases": []})
        self.assertInvalid(fx, "data/releases.json", "schema_version", "2")

    def test_missing_schema_version(self):
        fx = self.make()
        fx.write("links.json", {k: v for k, v in links_data().items() if k != "schema_version"})
        self.assertInvalid(fx, "data/links.json", 'missing field "schema_version"')

    def test_broken_json(self):
        fx = self.make()
        fx.write("shows.json", '{"schema_version": 1, "shows": [}')
        self.assertInvalid(fx, "data/shows.json", "invalid JSON", "line 1")

    def test_ticket_link_needs_url(self):
        self.assertInvalid(self.make(shows=[show("s", "2026-12-24", tickets={"type": "link"})]),
                           'shows[0] (id "s")', '"url"')
        self.assertInvalid(self.make(shows=[show("s", "2026-12-24", tickets={"type": "paid"})]),
                           'tickets.type')

    def test_bad_type_time_country_and_unknown_field(self):
        self.assertInvalid(self.make(releases=[release("r", "2026-01-01", type="mixtape")]), 'field "type"')
        self.assertInvalid(self.make(shows=[show("s", "2026-12-24", time="8pm")]), 'field "time"')
        self.assertInvalid(self.make(shows=[show("s", "2026-12-24", country="Sweden")]), 'field "country"')
        self.assertInvalid(self.make(shows=[show("s", "2026-12-24", venu="typo")]), 'unknown field "venu"')

    def test_cover_must_exist_in_covers(self):
        self.assertInvalid(self.make(releases=[release("r", "2026-01-01", cover="assets/covers/nope.jpg")]),
                           'field "cover"', "does not exist")
        self.assertInvalid(self.make(releases=[release("r", "2026-01-01", cover="../secret.jpg")]),
                           'field "cover"', "assets/covers/")

    def test_release_link_must_be_known_service(self):
        rel = release("r", "2026-01-01", links={"tidal": "https://tidal.com/x"})
        self.assertInvalid(self.make(releases=[rel]), 'unknown service "tidal"')

    def test_duplicate_ids(self):
        self.assertInvalid(self.make(shows=[show("s", "2026-12-24"), show("s", "2026-12-25")]),
                           'duplicate id "s"')

    def test_all_problems_reported_at_once(self):
        fx = self.make(shows=[show("a", "bad")], releases=[release("b", "2026-01-01", type="x")])
        message = self.assertInvalid(fx, "data/shows.json", "data/releases.json")
        self.assertGreaterEqual(len(message.splitlines()), 2)

    def test_invalid_data_does_not_touch_existing_build(self):
        fx = self.make()
        out = fx.build()
        before = (out / "index.html").read_text()
        fx.write("shows.json", {"schema_version": 1, "shows": [show("s", "nope")]})
        with self.assertRaises(build.ValidationError):
            fx.build()
        self.assertEqual((out / "index.html").read_text(), before)

    def test_placeholder_urls_warn_but_pass(self):
        links = links_data()
        links["streaming"][0]["url"] = "https://example.com/PLACEHOLDER"
        _, warnings = self.make(links=links).load()
        self.assertTrue(any("placeholder" in w for w in warnings))


class TestEscaping(FixtureTest):
    def test_html_in_data_is_escaped(self):
        evil = '<script>alert("x")</script>'
        links = links_data()
        links["streaming"][0]["label"] = evil
        rel = release("song", "2026-01-01", title=f'Song {evil} & "more"')
        shw = show("s", "2026-12-24", venue=evil, city="A&B", note=evil,
                   tickets={"type": "link", "url": 'https://t.example.org/?a=1&b="2"'})
        fx = self.make(links=links, releases=[rel], shows=[shw])
        out = fx.build()
        for rel_path in ("index.html", "music/index.html", "shows/index.html"):
            html = (out / rel_path).read_text()
            self.assertNotIn("<script>", html, rel_path)
            self.assertIn("&lt;script&gt;", html, rel_path)
        shows_html = (out / "shows/index.html").read_text()
        self.assertIn("A&amp;B", shows_html)
        self.assertIn("?a=1&amp;b=&quot;2&quot;", shows_html)
        self.assertIn("&amp; &quot;more&quot;", (out / "music/index.html").read_text())


class TestPagesAndMenu(FixtureTest):
    PAGES = {"index.html": ("./", "home"), "music/index.html": ("../", "music"),
             "shows/index.html": ("../", "shows"), "404.html": ("/songsbyjoel/", None)}

    def test_menu_on_every_page(self):
        out = self.make().build()
        for rel, (root, current) in self.PAGES.items():
            html = (out / rel).read_text()
            nav = html[html.index('<nav aria-label="Main">'):html.index("</nav>")]
            hrefs = re.findall(r'<a href="([^"]+)"', nav)
            labels = re.findall(r">(\w+)</a>", nav)
            self.assertEqual(labels, ["Music", "Merch", "Shows"], rel)
            self.assertEqual(hrefs, [f"{root}music/", "https://shop.songsbyjoel.com", f"{root}shows/"], rel)
            self.assertIn(f'<a class="logo" href="{root}"', html, rel)
            self.assertNotIn("target=", nav, rel)  # Merch opens in the same tab
            marked = re.findall(r'href="([^"]+)" aria-current="page"', html)
            if current == "home":
                self.assertEqual(marked, ["./"], rel)
            elif current:
                self.assertEqual(marked, [f"{root}{current}/"], rel)
            else:
                self.assertEqual(marked, [], rel)

    def test_meta_tags(self):
        out = self.make().build()
        for rel, canonical in (("index.html", BASE), ("music/index.html", BASE + "music/"),
                               ("shows/index.html", BASE + "shows/")):
            html = (out / rel).read_text()
            self.assertIn(f'<link rel="canonical" href="{canonical}">', html)
            self.assertIn(f'<meta property="og:url" content="{canonical}">', html)
            for tag in ('name="description"', 'property="og:title"', 'property="og:image"',
                        'name="twitter:card"', 'name="twitter:image"', 'rel="icon"', "<title>"):
                self.assertIn(tag, html, f"{rel}: {tag}")
            self.assertIn(f'content="{BASE}assets/share.png"', html)
            self.assertEqual(html.count("<h1"), 1, rel)

    def test_sitemap_robots_and_cname(self):
        out = self.make().build()
        self.assertIn(f"<loc>{BASE}music/</loc>", (out / "sitemap.xml").read_text())
        self.assertIn(f"Sitemap: {BASE}sitemap.xml", (out / "robots.txt").read_text())
        self.assertFalse((out / "CNAME").exists())
        out = self.make().build(base_url="https://songsbyjoel.com")
        self.assertEqual((out / "CNAME").read_text().strip(), "songsbyjoel.com")
        self.assertIn('href="/music/"', (out / "404.html").read_text())

    def test_build_is_deterministic(self):
        fx = self.make(releases=[release("a", "2026-01-01"), release("b", "2026-01-01")],
                       shows=[show("x", "2026-12-24"), show("y", "2026-12-24")])
        first = {p.relative_to(fx.dir / "_site"): p.read_bytes()
                 for p in fx.build().rglob("*") if p.is_file()}
        second = {p.relative_to(fx.dir / "_site"): p.read_bytes()
                  for p in fx.build().rglob("*") if p.is_file()}
        self.assertEqual(first, second)

    def test_refuses_to_empty_unknown_folder(self):
        fx = self.make()
        out = fx.dir / "_site"
        out.mkdir()
        (out / "important.txt").write_text("keep me")
        with self.assertRaises(SystemExit):
            fx.build()
        self.assertTrue((out / "important.txt").exists())


if __name__ == "__main__":
    unittest.main()
