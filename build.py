#!/usr/bin/env python3
"""Build songsbyjoel.com: data/ + templates/ + assets/ -> _site/.

Only the Python standard library is used.

    python3 build.py                     # validate and build to _site/
    python3 build.py --check             # validate only (used by Backstage)
    python3 build.py --base-url URL      # site root, e.g. https://songsbyjoel.com/
    python3 build.py --today 2026-12-01  # pretend it is another day
    python3 build.py --out DIR           # build somewhere else
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import string
import sys
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent

# Where the site lives. In GitHub Actions it is taken from the Pages settings instead.
DEFAULT_BASE_URL = "https://songsbyjoel.com/"
CUSTOM_DOMAIN = "songsbyjoel.com"
TIMEZONE = "Europe/Stockholm"
SUPPORTED_SCHEMA_VERSIONS = (1,)
# shows.json version 2 adds the optional fields "end_time" and "tour". Version 1 still works.
SHOWS_SCHEMA_VERSIONS = (1, 2)

SITE_NAME = "Joel"
SHARE_IMAGE = "assets/share.png"
SHARE_IMAGE_SIZE = (1200, 630)
PLACEHOLDER_MARK = "example.com"

RELEASE_TYPES = {"single": "Single", "ep": "EP", "album": "Album"}
COVER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".svg")
HOME_COUNTRY = "SE"
COUNTRY_NAMES = {
    "SE": "Sweden", "DK": "Denmark", "NO": "Norway", "FI": "Finland",
    "IS": "Iceland", "DE": "Germany", "NL": "Netherlands", "GB": "United Kingdom",
    "IE": "Ireland", "FR": "France", "ES": "Spain", "IT": "Italy", "PL": "Poland",
    "US": "United States", "CA": "Canada",
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

NAV = [("music", "Music"), ("merch", "Merch"), ("shows", "Shows")]
# Same bag icon as the shop header (16x16 path).
BAG_ICON = (
    "M7.99999 1.5C7.40211 1.5 6.83677 1.72464 6.4264 2.11207C6.0175 2.49812 5.79646 3.0122 5.79646 3.53846V4.46154"
    "H10.2035V3.53846C10.2035 3.0122 9.98249 2.49812 9.57359 2.11207C9.16322 1.72464 8.59788 1.5 7.99999 1.5Z"
    "M11.7035 4.46154V3.53846C11.7035 2.58564 11.3022 1.68119 10.6033 1.02137C9.90591 0.362928 8.96875 0 7.99999 0"
    "C7.03123 0 6.09408 0.362928 5.39666 1.02137C4.69777 1.68119 4.29646 2.58564 4.29646 3.53846V4.46154H2.96808"
    "C2.09126 4.46154 1.34979 5.11042 1.23353 5.97949L0.15814 14.018C0.0177587 15.0673 0.833995 16 1.89269 16"
    "H14.1073C15.166 16 15.9822 15.0673 15.8419 14.018L14.7665 5.97949C14.6502 5.11042 13.9087 4.46154 13.0319 4.46154"
    "H11.7035ZM2.96808 5.96154C2.84282 5.96154 2.73689 6.05424 2.72028 6.17839L1.64489 14.2169C1.62484 14.3668"
    " 1.74145 14.5 1.89269 14.5H14.1073C14.2586 14.5 14.3752 14.3668 14.3551 14.2169L13.2797 6.17839C13.2631 6.05424"
    " 13.1572 5.96154 13.0319 5.96154H2.96808Z"
)

# Joel's Spotify playlist with all his songs, shown on the home and music pages.
PLAYLIST_TITLE = "The Joel Collection"
PLAYLIST_URL = "https://open.spotify.com/playlist/1STR4IBNDJNFmZtll9Xwew"

ID_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
SPOTIFY_RE = re.compile(
    r"^https://open\.spotify\.com/(?:intl-[a-z]{2}(?:-[a-z]{2,4})?/)?"
    r"(track|album|playlist|artist)/([A-Za-z0-9]{22})(?:[/?#].*)?$")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised with a list of human readable problems."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


class Checker:
    """Collects problems for one data file."""

    def __init__(self, filename):
        self.filename = filename
        self.problems = []
        self.warnings = []

    def fail(self, where, message):
        prefix = f"data/{self.filename}"
        if where:
            prefix += f": {where}"
        self.problems.append(f"{prefix}: {message}")

    def warn(self, where, message):
        self.warnings.append(f"data/{self.filename}: {where}: {message}")

    # Field helpers. Each returns the value if valid, otherwise None.

    def obj(self, value, where):
        if not isinstance(value, dict):
            self.fail(where, f"must be an object, got {type_name(value)}")
            return None
        return value

    def keys(self, value, where, required, optional=()):
        for key in required:
            if key not in value:
                self.fail(where, f'missing field "{key}"')
        allowed = set(required) | set(optional)
        for key in value:
            if key not in allowed:
                self.fail(where, f'unknown field "{key}" (allowed: {", ".join(sorted(allowed))})')

    def text(self, value, where, field, allow_empty=False):
        if not isinstance(value, str):
            self.fail(where, f'field "{field}": must be text, got {type_name(value)}')
            return None
        if not allow_empty and not value.strip():
            self.fail(where, f'field "{field}": must not be empty')
            return None
        return value

    def ident(self, value, where, field="id"):
        value = self.text(value, where, field)
        if value is not None and not ID_RE.match(value):
            self.fail(where, f'field "{field}": "{value}" must be lowercase letters, digits, "-" or "_"')
            return None
        return value

    def url(self, value, where, field):
        value = self.text(value, where, field)
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.netloc or any(c.isspace() for c in value):
            self.fail(where, f'field "{field}": "{value}" is not a valid URL (must start with https://)')
            return None
        if PLACEHOLDER_MARK in parts.netloc:
            self.warn(where, f'field "{field}" is still a placeholder ({value})')
        return value

    def date(self, value, where, field):
        value = self.text(value, where, field)
        if value is None:
            return None
        try:
            if not DATE_RE.match(value):
                raise ValueError
            return dt.date.fromisoformat(value)
        except ValueError:
            self.fail(where, f'field "{field}": "{value}" is not a valid date (expected YYYY-MM-DD)')
            return None


def type_name(value):
    return {dict: "an object", list: "a list", str: "text", bool: "true/false",
            int: "a number", float: "a number", type(None): "null"}.get(type(value), type(value).__name__)


def where_item(list_name, index, item):
    label = f"{list_name}[{index}]"
    if isinstance(item, dict) and isinstance(item.get("id"), str):
        label += f' (id "{item["id"]}")'
    return label


def read_json(path, checker, supported=SUPPORTED_SCHEMA_VERSIONS):
    if not path.is_file():
        checker.fail("", "file is missing")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        checker.fail("", f"invalid JSON on line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return None
    except UnicodeDecodeError:
        checker.fail("", "file is not UTF-8")
        return None
    if checker.obj(data, "top level") is None:
        return None
    version = data.get("schema_version")
    if "schema_version" not in data:
        checker.fail("", 'missing field "schema_version"')
        return None
    if type(version) is not int or version not in supported:
        listed = ", ".join(str(v) for v in supported)
        checker.fail("", f'unknown "schema_version" {json.dumps(version)} (this build.py supports: {listed})')
        return None
    return data


def check_list(checker, data, name):
    value = data.get(name)
    if not isinstance(value, list):
        checker.fail("", f'field "{name}" must be a list, got {type_name(value)}')
        return []
    return value


def check_unique_ids(checker, items, list_name):
    seen = set()
    for index, item in enumerate(items):
        ident = item.get("id")
        if ident is not None and ident in seen:
            checker.fail(f"{list_name}[{index}]", f'duplicate id "{ident}"')
        seen.add(ident)


def validate_links(data_dir):
    c = Checker("links.json")
    data = read_json(data_dir / "links.json", c)
    result = None
    if data is not None:
        c.keys(data, "top level", ["schema_version", "streaming", "social", "merch_url"])
        result = {"streaming": [], "social": [], "merch_url": None}
        for group in ("streaming", "social"):
            if group not in data:
                continue
            for index, raw in enumerate(check_list(c, data, group)):
                where = where_item(group, index, raw)
                if c.obj(raw, where) is None:
                    continue
                c.keys(raw, where, ["id", "label", "url"])
                item = {
                    "id": c.ident(raw.get("id"), where) if "id" in raw else None,
                    "label": c.text(raw.get("label"), where, "label") if "label" in raw else None,
                    "url": c.url(raw.get("url"), where, "url") if "url" in raw else None,
                }
                result[group].append(item)
            check_unique_ids(c, result[group], group)
        if "merch_url" in data:
            result["merch_url"] = c.url(data["merch_url"], "top level", "merch_url")
    return result, c


def validate_releases(data_dir, assets_root, streaming_ids):
    c = Checker("releases.json")
    data = read_json(data_dir / "releases.json", c)
    releases = []
    if data is not None:
        c.keys(data, "top level", ["schema_version", "releases"])
        for index, raw in enumerate(check_list(c, data, "releases") if "releases" in data else []):
            where = where_item("releases", index, raw)
            if c.obj(raw, where) is None:
                continue
            c.keys(raw, where, ["id", "title", "type", "release_date", "cover", "links"])
            item = {
                "id": c.ident(raw.get("id"), where) if "id" in raw else None,
                "title": c.text(raw.get("title"), where, "title") if "title" in raw else None,
                "type": None,
                "release_date": c.date(raw.get("release_date"), where, "release_date") if "release_date" in raw else None,
                "cover": None,
                "links": {},
            }
            if "type" in raw:
                if raw["type"] in RELEASE_TYPES:
                    item["type"] = raw["type"]
                else:
                    c.fail(where, f'field "type": {json.dumps(raw["type"])} must be one of: {", ".join(RELEASE_TYPES)}')
            if "cover" in raw:
                cover = c.text(raw["cover"], where, "cover")
                if cover is not None:
                    item["cover"] = check_cover(c, where, cover, assets_root)
            if "links" in raw:
                links = raw["links"]
                if not isinstance(links, dict):
                    c.fail(where, f'field "links": must be an object, got {type_name(links)}')
                else:
                    for key, url in links.items():
                        if key not in streaming_ids:
                            known = ", ".join(streaming_ids) or "(none)"
                            c.fail(where, f'field "links": unknown service "{key}" (must be a streaming id from links.json: {known})')
                            continue
                        checked = c.url(url, where, f"links.{key}")
                        if checked is not None:
                            item["links"][key] = checked
            releases.append(item)
        check_unique_ids(c, releases, "releases")
    return releases, c


def check_cover(c, where, cover, assets_root):
    path = Path(cover)
    if (path.is_absolute() or ".." in path.parts or len(path.parts) < 3
            or path.parts[:2] != ("assets", "covers")):
        c.fail(where, f'field "cover": "{cover}" must be a file in assets/covers/')
        return None
    if path.suffix.lower() not in COVER_SUFFIXES:
        c.fail(where, f'field "cover": "{cover}" must end with one of {", ".join(COVER_SUFFIXES)}')
        return None
    if not (assets_root / path).is_file():
        c.fail(where, f'field "cover": file "{cover}" does not exist')
        return None
    return path.as_posix()


def validate_shows(data_dir):
    c = Checker("shows.json")
    data = read_json(data_dir / "shows.json", c, SHOWS_SCHEMA_VERSIONS)
    shows = []
    if data is not None:
        c.keys(data, "top level", ["schema_version", "shows"])
        for index, raw in enumerate(check_list(c, data, "shows") if "shows" in data else []):
            where = where_item("shows", index, raw)
            if c.obj(raw, where) is None:
                continue
            optional = ["time", "note"] + (["end_time", "tour"] if data["schema_version"] >= 2 else [])
            c.keys(raw, where, ["id", "date", "venue", "city", "country", "tickets"], optional)
            item = {
                "id": c.ident(raw.get("id"), where) if "id" in raw else None,
                "date": c.date(raw.get("date"), where, "date") if "date" in raw else None,
                "time": None,
                "venue": c.text(raw.get("venue"), where, "venue") if "venue" in raw else None,
                "city": c.text(raw.get("city"), where, "city") if "city" in raw else None,
                "country": None,
                "tickets": None,
                "note": "",
                "end_time": None,
                "tour": "",
            }
            if "time" in raw:
                time = c.text(raw["time"], where, "time")
                if time is not None and not TIME_RE.match(time):
                    c.fail(where, f'field "time": "{time}" is not a valid time (expected HH:MM, 24h)')
                else:
                    item["time"] = time
            if "end_time" in raw:
                end = c.text(raw["end_time"], where, "end_time")
                if end is not None and not TIME_RE.match(end):
                    c.fail(where, f'field "end_time": "{end}" is not a valid time (expected HH:MM, 24h)')
                elif end is not None and "time" not in raw:
                    c.fail(where, 'field "end_time": needs a start "time" too')
                else:
                    item["end_time"] = end
            if "tour" in raw:
                tour = c.text(raw["tour"], where, "tour", allow_empty=True)
                item["tour"] = (tour or "").strip()
            if "country" in raw:
                country = c.text(raw["country"], where, "country")
                if country is not None and not COUNTRY_RE.match(country):
                    c.fail(where, f'field "country": "{country}" must be a two-letter country code like "SE"')
                else:
                    item["country"] = country
            if "note" in raw:
                note = c.text(raw["note"], where, "note", allow_empty=True)
                item["note"] = (note or "").strip()
            if "tickets" in raw:
                item["tickets"] = check_tickets(c, where, raw["tickets"])
            shows.append(item)
        check_unique_ids(c, shows, "shows")
    return shows, c


def check_tickets(c, where, tickets):
    if not isinstance(tickets, dict):
        c.fail(where, f'field "tickets": must be an object, got {type_name(tickets)}')
        return None
    kind = tickets.get("type")
    if kind == "free":
        extra = set(tickets) - {"type"}
        if extra:
            c.fail(where, f'field "tickets": unknown field "{sorted(extra)[0]}" (free tickets only have "type")')
        return {"type": "free"}
    if kind == "link":
        extra = set(tickets) - {"type", "url"}
        if extra:
            c.fail(where, f'field "tickets": unknown field "{sorted(extra)[0]}"')
        if "url" not in tickets:
            c.fail(where, 'field "tickets": type "link" needs a "url"')
            return None
        url = c.url(tickets["url"], where, "tickets.url")
        return {"type": "link", "url": url} if url else None
    c.fail(where, f'field "tickets.type": {json.dumps(kind)} must be "free" or "link"')
    return None


def load_data(data_dir, assets_root=ROOT):
    """Validate all data files. Returns (data, warnings) or raises ValidationError."""
    data_dir = Path(data_dir)
    links, c_links = validate_links(data_dir)
    streaming_ids = [s["id"] for s in links["streaming"] if s["id"]] if links else []
    releases, c_releases = validate_releases(data_dir, Path(assets_root), streaming_ids)
    shows, c_shows = validate_shows(data_dir)
    checkers = (c_links, c_releases, c_shows)
    problems = [p for c in checkers for p in c.problems]
    if problems:
        raise ValidationError(problems)
    warnings = [w for c in checkers for w in c.warnings]
    return {"links": links, "releases": releases, "shows": shows}, warnings


# --------------------------------------------------------------------------
# Selection logic (pure, easy to test)
# --------------------------------------------------------------------------

def today_in_stockholm():
    return dt.datetime.now(ZoneInfo(TIMEZONE)).date()


def visible_releases(releases, today):
    """Released (date <= today), newest first. Ties broken by id for determinism."""
    out = [r for r in releases if r["release_date"] <= today]
    return sorted(out, key=lambda r: (r["release_date"], r["id"]), reverse=True)


def latest_release(releases, today):
    visible = visible_releases(releases, today)
    return visible[0] if visible else None


def split_shows(shows, today):
    """(upcoming nearest first, past most recent first). A show is upcoming all its day."""
    def key(s):
        return (s["date"], s["time"] or "", s["id"])
    upcoming = sorted((s for s in shows if s["date"] >= today), key=key)
    past = sorted((s for s in shows if s["date"] < today), key=key, reverse=True)
    return upcoming, past


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def esc(value):
    return html.escape(str(value), quote=True)


class Templates:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.cache = {}

    def render(self, name, **values):
        if name not in self.cache:
            text = (self.directory / name).read_text(encoding="utf-8")
            self.cache[name] = string.Template(text)
        return self.cache[name].substitute(values)


def spotify_embed(url):
    """(embed URL, height) for a Spotify link, or None if it is not one we can embed."""
    match = SPOTIFY_RE.match(url or "")
    if not match:
        return None
    kind, item_id = match.groups()
    return f"https://open.spotify.com/embed/{kind}/{item_id}", 152 if kind == "track" else 352


def long_date(day):
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def show_date(day, this_year=None):
    """"Fri 4 Dec", with the year only when it is not this year."""
    text = f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1][:3]}"
    return text if day.year == this_year else f"{text} {day.year}"


class Site:
    def __init__(self, data, templates_dir, base_url, today):
        self.data = data
        self.t = Templates(templates_dir)
        self.base_url = normalize_base_url(base_url)
        self.base_path = urlsplit(self.base_url).path
        self.today = today
        self.streaming = data["links"]["streaming"]
        self.social = data["links"]["social"]
        self.merch_url = data["links"]["merch_url"]

    # -- shared pieces ---------------------------------------------------

    def nav(self, root, current):
        items = []
        for key, label in NAV:
            href = self.merch_url if key == "merch" else f"{root}{key}/"
            aria = ' aria-current="page"' if key == current else ""
            items.append(f'<li><a href="{esc(href)}"{aria}>{label}</a></li>')
        return "\n          ".join(items)

    def shop_icon(self):
        """Bag icon in the header's right corner, like the shop's cart icon. Links to the shop."""
        if not self.merch_url:
            return ""
        return (
            f'<a class="header-icon shop" href="{esc(self.merch_url)}" aria-label="Merch shop">'
            f'<svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
            f'<path fill="currentColor" fill-rule="evenodd" d="{BAG_ICON}"/></svg></a>'
        )

    def link_list(self, links, css_class):
        if not links:
            return ""
        items = "".join(
            f'\n        <li><a class="button" href="{esc(link["url"])}">{esc(link["label"])}</a></li>'
            for link in links
        )
        return f'<ul class="{css_class}">{items}\n      </ul>'

    def release_buttons(self, release):
        links = [{"label": s["label"], "url": release["links"][s["id"]]}
                 for s in self.streaming if s["id"] in release["links"]]
        return self.link_list(links, "buttons")

    def spotify_player(self, url, label="Play on Spotify"):
        """Click-to-load Spotify player. Nothing is fetched from Spotify until the visitor
        clicks; without JavaScript the button is a plain link to Spotify."""
        embed = spotify_embed(url)
        if not embed:
            return ""
        src, height = embed
        return (f'<div class="player" data-embed="{esc(src)}" data-height="{height}">\n'
                f'            <a class="player-start" href="{esc(url)}">\n'
                f'              <span class="player-icon" aria-hidden="true"></span>\n'
                f'              <span class="player-text"><strong>{esc(label)}</strong>'
                f'<small>Loads Spotify’s player, which may set cookies.</small></span>\n'
                f'            </a>\n'
                f'          </div>')

    def playlist(self):
        return self.t.render("partials/playlist.html",
                             title=esc(PLAYLIST_TITLE),
                             player=self.spotify_player(PLAYLIST_URL, f"Play {PLAYLIST_TITLE}"))

    def release_card(self, release, root, heading, player=False):
        return self.t.render(
            "partials/release.html",
            heading=heading,
            id=esc(release["id"]),
            title=esc(release["title"]),
            cover=esc(root + release["cover"]),
            cover_alt=esc(f'Cover art for {release["title"]}'),
            type=RELEASE_TYPES[release["type"]],
            date_iso=release["release_date"].isoformat(),
            date=long_date(release["release_date"]),
            buttons=self.release_buttons(release),
            player=self.spotify_player(release["links"].get("spotify")) if player else "",
        )

    def show_item(self, show):
        # Shows at home in Sweden only need the city; elsewhere the country is added.
        place = show["city"]
        if show["country"] != HOME_COUNTRY:
            place += f', {COUNTRY_NAMES.get(show["country"], show["country"])}'
        datetime_attr = show["date"].isoformat()
        hours = ""
        if show["time"]:
            datetime_attr += f'T{show["time"]}'
            hours = show["time"] + (f'–{show["end_time"]}' if show["end_time"] else "")
        if show["tickets"]["type"] == "free":
            tickets = '<p class="tickets">Free – no tickets needed</p>'
        else:
            label = esc(f'Tickets for {show["venue"]}, {show["date"].isoformat()}')
            tickets = (f'<p class="tickets"><a class="button" href="{esc(show["tickets"]["url"])}" '
                       f'aria-label="{label}">Tickets</a></p>')
        note = f'<p class="note">{esc(show["note"])}</p>' if show["note"] else ""
        return self.t.render(
            "partials/show.html",
            id=esc(show["id"]),
            datetime=esc(datetime_attr),
            when=esc(show_date(show["date"], self.today.year)),
            venue=esc(show["venue"]),
            place=esc(place),
            hours=f'<span class="hours"><span class="dash"> – </span>{esc(hours)}</span>' if hours else "",
            tickets=tickets,
            note=note,
            tour=f'<p class="tour">{esc(show["tour"])}</p>' if show["tour"] else "",
        )

    def show_list(self, shows):
        return '<ol class="shows">\n' + "\n".join(self.show_item(s) for s in shows) + "\n      </ol>"

    def page(self, *, path, title, description, current, content, root):
        """Wrap content in the base layout. path is relative to the site root ("" = home)."""
        full_title = SITE_NAME if not title else f"{title} – {SITE_NAME}"
        return self.t.render(
            "base.html",
            title=esc(full_title),
            description=esc(description),
            canonical=esc(self.base_url + path),
            share_image=esc(self.base_url + SHARE_IMAGE),
            share_width=SHARE_IMAGE_SIZE[0],
            share_height=SHARE_IMAGE_SIZE[1],
            root=esc(root),
            home_current=' aria-current="page"' if current == "home" else "",
            nav=self.nav(root, current),
            shop_icon=self.shop_icon(),
            content=content,
            social=self.link_list(self.social, "social"),
        )

    # -- pages -------------------------------------------------------------

    def home(self):
        root = "./"
        latest = latest_release(self.data["releases"], self.today)
        if latest:
            release = self.release_card(latest, root, "h3", player=True)
        else:
            release = '<p>New music is on its way.</p>'
        upcoming, _ = split_shows(self.data["shows"], self.today)
        if upcoming:
            next_show = self.t.render("partials/next_show.html",
                                      show=self.show_list(upcoming[:1]), root=root)
        else:
            next_show = ""
        content = self.t.render("home.html", release=release, next_show=next_show,
                                playlist=self.playlist(),
                                listen=self.link_list(self.streaming, "buttons"))
        return self.page(path="", title="", current="home", root=root, content=content,
                         description="Official site of Joel – new music, merch and upcoming shows.")

    def music(self):
        root = "../"
        releases = visible_releases(self.data["releases"], self.today)
        if releases:
            cards = "\n".join(self.release_card(r, root, "h3") for r in releases)
            release_html = f'<div class="releases">\n{cards}\n      </div>'
        else:
            release_html = "<p>New music is on its way.</p>"
        content = self.t.render("music.html",
                                playlist=self.playlist(),
                                streaming=self.link_list(self.streaming, "buttons"),
                                social=self.link_list(self.social, "buttons"),
                                releases=release_html)
        return self.page(path="music/", title="Music", current="music", root=root, content=content,
                         description="Listen to Joel on Spotify, Apple Music, YouTube and Bandcamp, and follow along.")

    def shows(self):
        root = "../"
        upcoming, past = split_shows(self.data["shows"], self.today)
        if upcoming:
            upcoming_html = self.show_list(upcoming)
        else:
            upcoming_html = '<p class="empty">No upcoming shows right now – check back soon.</p>'
        past_html = self.t.render("partials/past_shows.html", shows=self.show_list(past)) if past else ""
        content = self.t.render("shows.html", upcoming=upcoming_html, past=past_html)
        return self.page(path="shows/", title="Shows", current="shows", root=root, content=content,
                         description="Upcoming shows and concerts with Joel.")

    def not_found(self):
        # 404.html is served from any URL, so it needs absolute paths.
        root = self.base_path
        content = self.t.render("404.html", root=esc(root))
        return self.page(path="404.html", title="Page not found", current="", root=root, content=content,
                         description="This page could not be found.")

    def sitemap(self):
        urls = "".join(f"  <url><loc>{esc(self.base_url + p)}</loc></url>\n" for p in ("", "music/", "shows/"))
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{urls}</urlset>\n")

    def robots(self):
        return f"User-agent: *\nAllow: /\n\nSitemap: {self.base_url}sitemap.xml\n"

    def files(self):
        files = {
            "index.html": self.home(),
            "music/index.html": self.music(),
            "shows/index.html": self.shows(),
            "404.html": self.not_found(),
            "sitemap.xml": self.sitemap(),
            "robots.txt": self.robots(),
        }
        if urlsplit(self.base_url).netloc == CUSTOM_DOMAIN and self.base_path == "/":
            files["CNAME"] = CUSTOM_DOMAIN + "\n"
        return files


def normalize_base_url(base_url):
    parts = urlsplit(base_url)
    if parts.scheme not in ("https", "http") or not parts.netloc or parts.query or parts.fragment:
        raise SystemExit(f"Invalid --base-url {base_url!r}: expected something like https://songsbyjoel.com/")
    return base_url if base_url.endswith("/") else base_url + "/"


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def prepare_out_dir(out_dir):
    """Empty out_dir, but only if it looks like an earlier build (safety net)."""
    if out_dir.exists():
        if not out_dir.is_dir():
            raise SystemExit(f"{out_dir} exists and is not a folder")
        if any(out_dir.iterdir()) and not (out_dir / "sitemap.xml").is_file():
            raise SystemExit(f"Refusing to empty {out_dir}: it does not look like a build folder")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)


def build(data_dir=ROOT / "data", templates_dir=ROOT / "templates", assets_dir=ROOT / "assets",
          out_dir=ROOT / "_site", base_url=DEFAULT_BASE_URL, today=None):
    """Validate, then write the whole site. Returns the list of warnings."""
    assets_dir = Path(assets_dir)
    data, warnings = load_data(data_dir, assets_root=assets_dir.parent)
    site = Site(data, templates_dir, base_url, today or today_in_stockholm())
    files = site.files()  # render everything before touching the output folder

    out_dir = Path(out_dir)
    prepare_out_dir(out_dir)
    for rel, text in sorted(files.items()):
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    shutil.copytree(assets_dir, out_dir / "assets",
                    ignore=shutil.ignore_patterns(".DS_Store", "Thumbs.db"))
    return warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build songsbyjoel.com")
    parser.add_argument("--check", action="store_true", help="only validate data/, do not build")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"site root (default {DEFAULT_BASE_URL})")
    parser.add_argument("--out", default=str(ROOT / "_site"), help="output folder (default _site/)")
    parser.add_argument("--today", help="override today's date, YYYY-MM-DD (for testing)")
    args = parser.parse_args(argv)

    today = None
    if args.today:
        try:
            today = dt.date.fromisoformat(args.today)
        except ValueError:
            parser.error(f"--today {args.today!r} is not a valid date (YYYY-MM-DD)")

    try:
        if args.check:
            _, warnings = load_data(ROOT / "data")
        else:
            warnings = build(out_dir=Path(args.out), base_url=args.base_url, today=today)
    except ValidationError as exc:
        print(f"Data is invalid ({len(exc.problems)} problem(s)). Nothing was built or published:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    print("Data OK." if args.check else f"Built site to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
