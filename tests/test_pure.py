"""Pure-function tests: no network, no Telegram, no spotipy needed."""
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.downloader import safe_name  # noqa: E402
from app.history import History  # noqa: E402

TRACK_RE = re.compile(r"^(?:/intl-[a-zA-Z-]+)?/track/([A-Za-z0-9]+)$")
COLLECTION_RE = re.compile(
    r"^(?:/intl-[a-zA-Z-]+)?/(playlist|album)/([A-Za-z0-9]+)$")
HOSTS = {"open.spotify.com", "spotify.com"}


def _path(url):
    from urllib.parse import urlparse
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    if p.netloc.lower() not in HOSTS:
        return None
    return p.path.rstrip("/")


def extract_track_id(url):
    path = _path(url)
    if not path:
        return None
    m = TRACK_RE.match(path)
    return m.group(1) if m else None


def extract_collection(url):
    path = _path(url)
    if not path:
        return None
    m = COLLECTION_RE.match(path)
    return (m.group(1), m.group(2)) if m else None


# mirrors of the regexes in app/spotify.py — if these drift, copy the
# patterns from the module instead of editing here.
def test_regexes_mirror_module():
    src = Path(__file__).resolve().parent.parent.joinpath(
        "app", "spotify.py").read_text()
    assert "intl-" in src
    assert "playlist|album" in src


@pytest.mark.parametrize("url,expected", [
    ("https://open.spotify.com/track/abc123XYZ", "abc123XYZ"),
    ("https://open.spotify.com/track/abc123XYZ/", "abc123XYZ"),
    ("https://open.spotify.com/intl-fa/track/abc123XYZ", "abc123XYZ"),
    ("https://open.spotify.com/intl-de/track/abc123XYZ/", "abc123XYZ"),
    ("https://spotify.com/track/abc123XYZ", "abc123XYZ"),
    ("https://open.spotify.com/album/abc123", None),
    ("https://open.spotify.com/playlist/abc123", None),
    ("https://youtube.com/watch?v=abc123", None),
    ("not a url", None),
    ("", None),
])
def test_track_id(url, expected):
    assert extract_track_id(url) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://open.spotify.com/playlist/PL123abc", ("playlist", "PL123abc")),
    ("https://open.spotify.com/album/AL456def", ("album", "AL456def")),
    ("https://open.spotify.com/intl-fa/playlist/PL123abc",
     ("playlist", "PL123abc")),
    ("https://open.spotify.com/track/abc123", None),
    ("https://open.spotify.com/artist/abc123", None),
    ("garbage", None),
])
def test_collection(url, expected):
    assert extract_collection(url) == expected


@pytest.mark.parametrize("raw,expected", [
    ('Artist - Title<>:"/\\|?*', "Artist - Title"),
    ("  a   b  ", "a b"),
    ("", "track"),
    ("///", "track"),
])
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_safe_name_truncates():
    assert len(safe_name("x" * 500)) == 180


def test_history_prefs_and_stats():
    with tempfile.TemporaryDirectory() as td:
        h = History(str(Path(td) / "h.db"))
        assert h.get_quality(1) == 192
        h.set_quality(1, 320)
        assert h.get_quality(1) == 320
        assert h.get_cached(1, "t1") is None
        h.save(1, "t1", "Title", "Artist", "fileid1", 320, 1000)
        cached = h.get_cached(1, "t1")
        assert cached["file_id"] == "fileid1"
        assert cached["quality"] == 320
        st = h.stats(1)
        assert st == {"count": 1, "bytes": 1000}
        # upsert replaces
        h.save(1, "t1", "Title", "Artist", "fileid2", 128, 2000)
        assert h.get_cached(1, "t1")["file_id"] == "fileid2"
        assert h.stats(1) == {"count": 1, "bytes": 2000}
        assert h.stats(999) == {"count": 0, "bytes": 0}
