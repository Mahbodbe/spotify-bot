import re
from dataclasses import dataclass
from urllib.parse import urlparse
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Accepts optional locale prefix: /intl-<lang>/track/<id>
TRACK_RE = re.compile(r"^(?:/intl-[a-zA-Z-]+)?/track/([A-Za-z0-9]+)$")
COLLECTION_RE = re.compile(r"^(?:/intl-[a-zA-Z-]+)?/(playlist|album)/([A-Za-z0-9]+)$")

SPOTIFY_HOSTS = {"open.spotify.com", "spotify.com"}


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int
    url: str
    cover_url: str = ""

    @property
    def artist_text(self):
        return ", ".join(self.artists)

    @property
    def search_query(self):
        return f"{self.artist_text} - {self.title} official audio"


@dataclass(frozen=True)
class Collection:
    kind: str  # "playlist" | "album"
    id: str
    name: str
    tracks: tuple


def _path(url):
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.netloc.lower() not in SPOTIFY_HOSTS:
        return None
    return parsed.path.rstrip("/")


class SpotifyService:
    def __init__(self, client_id, client_secret):
        self.client = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret,
            )
        )

    @staticmethod
    def extract_track_id(url):
        path = _path(url)
        if not path:
            return None
        match = TRACK_RE.match(path)
        return match.group(1) if match else None

    @staticmethod
    def extract_collection(url):
        """Return (kind, id) for playlist/album URLs, else None."""
        path = _path(url)
        if not path:
            return None
        match = COLLECTION_RE.match(path)
        return (match.group(1), match.group(2)) if match else None

    @staticmethod
    def _to_track(data):
        images = data.get("album", {}).get("images") or []
        cover = images[0]["url"] if images else ""
        return Track(
            id=data["id"],
            title=data["name"],
            artists=tuple(a["name"] for a in data["artists"]),
            album=data["album"]["name"],
            duration_ms=data["duration_ms"],
            url=data["external_urls"]["spotify"],
            cover_url=cover,
        )

    def get_track(self, url):
        track_id = self.extract_track_id(url)
        if not track_id:
            return None
        data = self.client.track(track_id)
        return self._to_track(data)

    def search_tracks(self, query, limit=5):
        result = self.client.search(q=query, type="track", limit=limit)
        items = (result.get("tracks") or {}).get("items") or []
        return [self._to_track(d) for d in items]

    def get_collection(self, url):
        parsed = self.extract_collection(url)
        if not parsed:
            return None
        kind, coll_id = parsed
        if kind == "playlist":
            meta = self.client.playlist(coll_id, fields="name,tracks.total")
            name = meta.get("name") or "playlist"
            tracks = []
            offset = 0
            while True:
                page = self.client.playlist_tracks(
                    coll_id, limit=100, offset=offset,
                    fields="items.track(id,name,artists(name),album(name,images),duration_ms,external_urls),next,total",
                )
                for item in page.get("items") or []:
                    t = item.get("track")
                    if t and t.get("id"):
                        try:
                            tracks.append(self._to_track(t))
                        except (KeyError, TypeError):
                            continue
                if not page.get("next"):
                    break
                offset += 100
        else:
            meta = self.client.album(coll_id)
            name = meta.get("name") or "album"
            images = meta.get("images") or []
            cover = images[0]["url"] if images else ""
            tracks = []
            offset = 0
            while True:
                page = self.client.album_tracks(coll_id, limit=50, offset=offset)
                for t in page.get("items") or []:
                    if t.get("id"):
                        artists = tuple(a["name"] for a in t["artists"])
                        tracks.append(Track(
                            id=t["id"], title=t["name"], artists=artists,
                            album=name, duration_ms=t["duration_ms"],
                            url=t["external_urls"]["spotify"], cover_url=cover,
                        ))
                if not page.get("next"):
                    break
                offset += 50
        return Collection(kind=kind, id=coll_id, name=name, tracks=tuple(tracks))
