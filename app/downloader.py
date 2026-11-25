import asyncio
import logging
import re
import urllib.request
import uuid
from pathlib import Path
import yt_dlp
import yt_dlp.utils

log = logging.getLogger(__name__)

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


def _pick_by_duration(entries, target_sec, tolerance=90):
    """Pick the entry whose duration is closest to target within tolerance."""
    best = None
    best_diff = None
    for e in entries or []:
        d = e.get("duration") if isinstance(e, dict) else None
        if not d:
            continue
        diff = abs(d - target_sec)
        if diff <= tolerance and (best_diff is None or diff < best_diff):
            best, best_diff = e, diff
    if best is not None:
        return best
    if entries and all(
            not (isinstance(e, dict) and e.get("duration"))
            for e in entries):
        return entries[0]
    return None


def _entry_url(entry, source):
    """Extract a downloadable URL from either a full or flat yt-dlp entry."""
    url = entry.get("webpage_url") or entry.get("url") or ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    vid = entry.get("id")
    if vid and source == "youtube":
        return f"https://www.youtube.com/watch?v={vid}"
    return ""


class AudioDownloader:
    def __init__(self, download_dir, max_file_size_mb, cookiefile=None):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_file_size_mb * 1024 * 1024
        self.cookiefile = None
        if cookiefile:
            cand = Path(cookiefile)
            if not cand.is_absolute():
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

    def _base_options(self, outtmpl, quality, progress_hook):
        return {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
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

    def _download_url(self, options, url, progress_hook):
        """Download one resolved URL with given options. Returns mp3 Path."""
        options = dict(options)
        options["progress_hooks"] = [progress_hook]
        with yt_dlp.YoutubeDL(options) as ydl:
            entry = ydl.extract_info(url, download=True)
            output = Path(ydl.prepare_filename(entry)).with_suffix(".mp3")
            if not output.exists():
                matches = list(Path(output).parent.glob("*.mp3"))
                if not matches:
                    raise DownloadError("MP3 was not produced")
                output = max(matches, key=lambda p: p.stat().st_mtime)
            if output.stat().st_size > self.max_bytes:
                output.unlink(missing_ok=True)
                raise DownloadError("File is too large")
            return output

    def _search_candidates(self, query, target_sec, source, cookiefile=None):
        """Flat search (fast, avoids per-video fetches); return up to 3 URLs
        ordered by duration closeness."""
        search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "socket_timeout": 20,
        }
        if cookiefile:
            search_opts["cookiefile"] = cookiefile
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            info = ydl.extract_info(query, download=False)
        raw = info.get("entries") if isinstance(info, dict) else None
        entries = []
        if raw:
            for e in raw:
                if isinstance(e, dict):
                    entries.append(e)
                if len(entries) >= 5:
                    break
        within = []
        unknown = []
        for e in entries:
            page = _entry_url(e, source)
            if not page:
                continue
            d = e.get("duration")
            if d:
                diff = abs(d - target_sec)
                if diff <= 90:
                    within.append((diff, page))
            else:
                unknown.append(page)
        within.sort(key=lambda x: x[0])
        ordered = [p for _, p in within] + unknown
        return ordered[:3]

    def _try_source(self, source, query, target_sec, opts, progress_hook,
                    cancel_event):
        pages = self._search_candidates(
            query, target_sec, source, opts.get("cookiefile"))
        if not pages:
            raise DownloadError(f"no {source} match within duration")
        last_err = None
        for page in pages:
            self._check_cancel(cancel_event)
            try:
                output = self._download_url(opts, page, progress_hook)
                log.info("source=%s page=%s", source, page)
                return output
            except Cancelled:
                raise
            except Exception as e:
                last_err = e
                log.warning("%s candidate failed (%s): %s", source, page, e)
        raise DownloadError(f"{source}: {last_err}")

    def _download(self, track, quality, cancel_event, with_cover, with_lyrics):
        self._check_cancel(cancel_event)
        job_dir = self.download_dir / f"job-{uuid.uuid4().hex[:12]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_name(f"{track.artist_text} - {track.title}")
        outtmpl = str(job_dir / f"{stem}.%(ext)s")
        target_sec = track.duration_ms / 1000

        def progress_hook(d):
            if cancel_event is not None and cancel_event.is_set():
                raise Cancelled("cancelled by user")

        base = self._base_options(outtmpl, quality, progress_hook)
        errors = []
        output = None

        # 1) YouTube search (top 5 flat search, tries up to 3 best matches)
        yt_opts = dict(base)
        if self.cookiefile:
            yt_opts["cookiefile"] = self.cookiefile
        try:
            output = self._try_source(
                "youtube", f"ytsearch5:{track.search_query}",
                target_sec, yt_opts, progress_hook, cancel_event,
            )
        except Cancelled:
            raise
        except Exception as e:
            errors.append(str(e))

        # 2) SoundCloud fallback (no login needed, datacenter-friendly)
        if output is None:
            sc_opts = dict(base)
            try:
                output = self._try_source(
                    "soundcloud",
                    f"scsearch5:{track.artist_text} {track.title}",
                    target_sec, sc_opts, progress_hook, cancel_event,
                )
            except Cancelled:
                raise
            except Exception as e:
                errors.append(str(e))
                raise DownloadError("; ".join(errors))

        cover = fetch_bytes(track.cover_url) if with_cover else b""
        lyrics = fetch_lyrics(track.artists[0] if track.artists else "",
                              track.title) if with_lyrics else ""
        tag_mp3(output, track, cover, lyrics)
        return output, lyrics
