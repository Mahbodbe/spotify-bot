import asyncio
import re
import urllib.request
import uuid
from pathlib import Path
import yt_dlp
import yt_dlp.utils

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
    # no duration info at all — fall back to first entry
    if entries and all(
            not (isinstance(e, dict) and e.get("duration"))
            for e in entries):
        return entries[0]
    return None


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

    def _search_candidates(self, options, query, target_sec):
        """Search (no download); return up to 3 candidate webpage URLs
        ordered by duration closeness."""
        options = dict(options)
        options["quiet"] = True
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=False)
        raw = info.get("entries") if isinstance(info, dict) else None
        entries = []
        if raw:
            count = 0
            it = iter(raw)  # type: ignore[arg-type]
            while count < 5:
                try:
                    entries.append(next(it))
                except StopIteration:
                    break
                count += 1
        cands = []
        for e in entries[:5]:
            if not isinstance(e, dict):
                continue
            d = e.get("duration")
            page = e.get("webpage_url")
            if not page:
                continue
            diff = abs(d - target_sec) if d else 10 ** 9
            cands.append((diff, page))
        cands.sort(key=lambda x: x[0])
        return [p for diff, p in cands if diff <= 90]

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

        # 1) YouTube search (with cookies when available)
        yt_opts = dict(base)
        yt_opts["default_search"] = "ytsearch1"
        if self.cookiefile:
            yt_opts["cookiefile"] = self.cookiefile
        try:
            pages = self._search_candidates(
                yt_opts, f"ytsearch1:{track.search_query}", target_sec)
            if not pages:
                raise DownloadError("No YouTube match within duration")
            output = self._download_url(yt_opts, pages[0], progress_hook)
            import logging as _lg
            _lg.getLogger(__name__).info("source=youtube page=%s", pages[0])
        except (Cancelled, DownloadError) as e:
            if isinstance(e, Cancelled):
                raise
            errors.append(f"youtube: {e}")
            output = None
        except Exception as e:
            errors.append(f"youtube: {e}")
            output = None

        # 2) SoundCloud fallback (no login needed, datacenter-friendly)
        if output is None:
            sc_opts = dict(base)
            sc_opts["default_search"] = "scsearch1"
            try:
                pages = self._search_candidates(
                    sc_opts,
                    f"scsearch1:{track.artist_text} {track.title}",
                    target_sec)
                if not pages:
                    raise DownloadError("No SoundCloud match within duration")
                output = self._download_url(sc_opts, pages[0], progress_hook)
                import logging as _lg2
                _lg2.getLogger(__name__).info(
                    "source=soundcloud page=%s", pages[0])
            except Cancelled:
                raise
            except DownloadError as e:
                raise DownloadError(
                    "نتونستم نسخه صوتی پیدا کنم (" +
                    "; ".join(errors + [f"soundcloud: {e}"]) + ")")
            except Exception as e:
                raise DownloadError(
                    f"نتونستم نسخه صوتی پیدا کنم ({errors}; sc: {e})")

        cover = fetch_bytes(track.cover_url) if with_cover else b""
        lyrics = fetch_lyrics(track.artists[0] if track.artists else "",
                              track.title) if with_lyrics else ""
        tag_mp3(output, track, cover, lyrics)
        return output, lyrics
