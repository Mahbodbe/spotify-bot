import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _materialize_cookiefile(b64_env, file_env, default_name, tmp_name):
    """Support either a file path or a base64-encoded secret env var."""
    b64 = (os.getenv(b64_env) or "").strip()
    if b64:
        try:
            raw = base64.b64decode(b64)
            target = Path("/tmp") / tmp_name
            target.write_bytes(raw)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            return str(target)
        except Exception:
            pass
    return os.getenv(file_env, default_name)


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
    ig_cookiefile: str
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
            cookiefile=_materialize_cookiefile(
                "YT_COOKIES_B64", "YT_COOKIEFILE", ".cookies-yt", ".cookies-yt"),
            ig_cookiefile=_materialize_cookiefile(
                "IG_COOKIES_B64", "IG_COOKIEFILE", ".cookies-ig", ".cookies-ig"),
            health_port=int(port_raw),
            webhook_url=webhook_url,
            webhook_secret=secret,
        )
