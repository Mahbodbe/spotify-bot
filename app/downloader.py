import asyncio
import re
import urllib.request
import uuid
from pathlib import Path
import yt_dlp

LYRICS_API = "https://lrclib.net/api/get"


class DownloadError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value)
    return re.sub(r"\s+", " ", value).strip()[:180] or "track"


def fetch_bytes(url, timeout=20):
    if not url:
        return b""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return b""


def fetch_lyrics(artist, title, timeout=15):
    """Free lyrics lookup via lrclib.net — returns plain lyrics or ''."""
    try:
        import json as _json
        import urllib.parse as _up
        qs = _up.urlencode({"artist_name": artist, "track_name": title})
        req = urllib.request.Request(
            f"{LYRICS_API}?{qs}",
            headers={"User-Agent": "spotify-telegram-bot"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8", errors="ignore"))
        return (data.get("plainLyrics") or "").strip()
    except Exception:
        return ""


def tag_mp3(path, track, cover_bytes=b"", lyrics=""):
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, USLT
    except ImportError:
        return
    try:
        audio = MP3(str(path), ID3=ID3)
        try:
            audio.add_tags()
        except Exception:
            pass
        audio.tags["TIT2"] = TIT2(encoding=3, text=track.title)
        audio.tags["TPE1"] = TPE1(encoding=3, text=track.artist_text)
        audio.tags["TALB"] = TALB(encoding=3, text=track.album)
        if cover_bytes:
            audio.tags["APIC"] = APIC(
                encoding=3, mime="image/jpeg", type=3,
                desc="cover", data=cover_bytes,
            )
        if lyrics:
            audio.tags["USLT"] = USLT(encoding=3, text=lyrics[:8000])
        audio.save()
    except Exception:
        pass


class AudioDownloader:
    def __init__(self, download_dir, max_file_size_mb, cookiefile=None):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_file_size_mb * 1024 * 1024
        self.cookiefile = None
        if cookiefile:
            cand = Path(cookiefile)
            if not cand.is_absolute():
                # try CWD first (repo root), then download dir
                if (Path.cwd() / cand).is_file():
                    cand = Path.cwd() / cand
                else:
                    cand = self.download_dir / cand
            if cand.is_file():
                self.cookiefile = str(cand)

    async def download(self, track, quality=192, cancel_event=None,
                       with_cover=True, with_lyrics=True):
        return await asyncio.to_thread(
            self._download, track, quality, cancel_event,
            with_cover, with_lyrics,
        )

    def _check_cancel(self, cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled("cancelled by user")

    def _download(self, track, quality, cancel_event, with_cover, with_lyrics):
        self._check_cancel(cancel_event)
        # Unique job dir — two users grabbing the same track never collide.
        job_dir = self.download_dir / f"job-{uuid.uuid4().hex[:12]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_name(f"{track.artist_text} - {track.title}")
        outtmpl = str(job_dir / f"{stem}.%(ext)s")

        def progress_hook(d):
            if cancel_event is not None and cancel_event.is_set():
                raise Cancelled("cancelled by user")

        options = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch1",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(quality),
            }],
            "max_filesize": self.max_bytes,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "progress_hooks": [progress_hook],
        }
        if self.cookiefile:
            options["cookiefile"] = self.cookiefile

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(f"ytsearch1:{track.search_query}", download=True)
                entries = info.get("entries") if info else None
                entry = entries[0] if entries else info
                if not entry:
                    raise DownloadError("No result found")

                source_duration = entry.get("duration")
                target_duration = track.duration_ms / 1000
                if source_duration and abs(source_duration - target_duration) > 90:
                    raise DownloadError("Matched source duration differs too much")

                output = Path(ydl.prepare_filename(entry)).with_suffix(".mp3")
                if not output.exists():
                    matches = list(job_dir.glob("*.mp3"))
                    if not matches:
                        raise DownloadError("MP3 was not produced")
                    output = max(matches, key=lambda p: p.stat().st_mtime)

                if output.stat().st_size > self.max_bytes:
                    output.unlink(missing_ok=True)
                    raise DownloadError("File is too large")

                cover = fetch_bytes(track.cover_url) if with_cover else b""
                lyrics = fetch_lyrics(track.artists[0] if track.artists else "",
                                      track.title) if with_lyrics else ""
                tag_mp3(output, track, cover, lyrics)
                return output, lyrics
        except Cancelled:
            raise
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(str(exc)) from exc
