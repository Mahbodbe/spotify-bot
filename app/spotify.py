import re
from dataclasses import dataclass
from urllib.parse import urlparse
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

TRACK_RE = re.compile(r"^/track/([A-Za-z0-9]+)$")

@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int
    url: str

    @property
    def artist_text(self):
        return ", ".join(self.artists)

    @property
    def search_query(self):
        return f"{self.artist_text} - {self.title} official audio"

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
        try:
            parsed = urlparse(url.strip())
        except ValueError:
            return None
        if parsed.netloc.lower() not in {"open.spotify.com", "spotify.com"}:
            return None
        match = TRACK_RE.match(parsed.path.rstrip("/"))
        return match.group(1) if match else None

    def get_track(self, url):
        track_id = self.extract_track_id(url)
        if not track_id:
            return None
        data = self.client.track(track_id)
        return Track(
            id=data["id"],
            title=data["name"],
            artists=tuple(a["name"] for a in data["artists"]),
            album=data["album"]["name"],
            duration_ms=data["duration_ms"],
            url=data["external_urls"]["spotify"],
        )
