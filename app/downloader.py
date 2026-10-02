import asyncio
import re
from pathlib import Path
import yt_dlp

class DownloadError(RuntimeError):
    pass

def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value)
    return re.sub(r"\s+", " ", value).strip()[:180] or "track"

class AudioDownloader:
    def __init__(self, download_dir, max_file_size_mb):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_file_size_mb * 1024 * 1024

    async def download(self, track):
        return await asyncio.to_thread(self._download, track)

    def _download(self, track):
        stem = safe_name(f"{track.artist_text} - {track.title}")
        outtmpl = str(self.download_dir / f"{stem}.%(ext)s")
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
                "preferredquality": "192",
            }],
            "postprocessor_args": [
                "-metadata", f"title={track.title}",
                "-metadata", f"artist={track.artist_text}",
                "-metadata", f"album={track.album}",
            ],
            "max_filesize": self.max_bytes,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
        }

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
                    matches = list(self.download_dir.glob(f"{stem}*.mp3"))
                    if not matches:
                        raise DownloadError("MP3 was not produced")
                    output = max(matches, key=lambda p: p.stat().st_mtime)

                if output.stat().st_size > self.max_bytes:
                    output.unlink(missing_ok=True)
                    raise DownloadError("File is too large")
                return output
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(str(exc)) from exc
