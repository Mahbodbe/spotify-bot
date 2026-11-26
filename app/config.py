import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _materialize_cookiefile():
    """Support either a file path (YT_COOKIEFILE) or base64 secret (YT_COOKIES_B64)."""
    b64 = (os.getenv("YT_COOKIES_B64") or "").strip()
    if b64:
        try:
            raw = base64.b64decode(b64)
            target = Path("/tmp/.cookies-yt")
            target.write_bytes(raw)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            return str(target)
        except Exception:
            pass
    return os.getenv("YT_COOKIEFILE", ".cookies-yt")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    spotify_client_id: str
    spotify_client_secret: str
    download_dir: str
    max_file_size_mb: int
    default_quality: int
    max_playlist_tracks: int
    cookiefile: str
    health_port: int
    webhook_url: str
    webhook_secret: str

    @classmethod
    def from_env(cls):
        values = {
            "BOT_TOKEN": os.getenv("BOT_TOKEN"),
            "SPOTIFY_CLIENT_ID": os.getenv("SPOTIFY_CLIENT_ID"),
            "SPOTIFY_CLIENT_SECRET": os.getenv("SPOTIFY_CLIENT_SECRET"),
        }
        missing = [k for k, v in values.items() if not v]
        if missing:
            raise RuntimeError("Missing environment variables: " + ", ".join(missing))
        quality = int(os.getenv("DEFAULT_QUALITY", "192"))
        if quality not in (128, 192, 320):
            quality = 192
        webhook_url = (
            os.getenv("WEBHOOK_URL")
            or os.getenv("RENDER_EXTERNAL_URL")
            or ""
        ).strip().rstrip("/")
        is_paas = bool(webhook_url or os.getenv("RENDER") or os.getenv("SPACE_ID"))
        default_dir = "/tmp/downloads" if is_paas else "downloads"
        port_raw = os.getenv("PORT") or ("7860" if is_paas else "0")
        secret = (os.getenv("WEBHOOK_SECRET") or "").strip()
        if not secret and webhook_url:
            secret = hashlib.sha256(values["BOT_TOKEN"].encode()).hexdigest()[:32]
        return cls(
            bot_token=values["BOT_TOKEN"],
            spotify_client_id=values["SPOTIFY_CLIENT_ID"],
            spotify_client_secret=values["SPOTIFY_CLIENT_SECRET"],
            download_dir=os.getenv("DOWNLOAD_DIR", default_dir),
            max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", "45")),
            default_quality=quality,
            max_playlist_tracks=int(os.getenv("MAX_PLAYLIST_TRACKS", "30")),
            cookiefile=_materialize_cookiefile(),
            health_port=int(port_raw),
            webhook_url=webhook_url,
            webhook_secret=secret,
        )
