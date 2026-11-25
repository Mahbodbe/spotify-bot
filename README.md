# Spotify Telegram Bot

Telegram bot for downloading Spotify tracks, playlists, and albums as tagged MP3s (with cover art and optional lyrics).

## How it works

Spotify's Web API provides track metadata (title, artist, album, cover, duration), not the raw audio stream. The bot resolves the track on Spotify, searches public audio sources via `yt-dlp` (YouTube first with flat multi-candidate duration matching, SoundCloud fallback), converts to MP3 with `FFmpeg`, embeds ID3 tags + cover art with `mutagen`, sends the audio to Telegram, and cleans up temporary files.

## Features

- **Single tracks**: Send any `open.spotify.com/track/...` or `spotify.link/...` URL.
- **Playlists & albums**: Download sequentially or packed into size-limited ZIP parts.
- **Inline search**: Send a song name directly and pick from top 5 Spotify results.
- **Quality & cache**: `/quality` (128 / 192 / 320 kbps), SQLite `file_id` cache, `/stats`, and `/cancel`.

## Requirements

- Python 3.12+
- `ffmpeg` and `nodejs` (required by `yt-dlp` for YouTube signature challenges)
- Telegram Bot Token (`BOT_TOKEN`)
- Spotify App credentials (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`)

## Setup

```bash
cp .env.example .env
# Fill in BOT_TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
pip install -r requirements.txt
python -m app
```

### Docker

```bash
cp .env.example .env
docker compose up -d --build
```

If running on a VPS/datacenter IP where YouTube blocks anonymous requests, place a Netscape-format `cookies.txt` at `downloads/.cookies-yt` (matches `YT_COOKIEFILE` in `.env.example`).
