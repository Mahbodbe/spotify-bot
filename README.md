# Spotify Telegram Bot 🎵

A focused Telegram bot: send a Spotify track URL and receive an MP3.

## Architecture

Spotify's Web API provides track metadata, not the track's raw audio stream. This bot uses Spotify to identify the exact track, then searches a public audio source with yt-dlp, validates the result duration, converts it to MP3 with FFmpeg, sends it to Telegram, and removes the temporary file.

Use the bot only for audio you are authorized to download and redistribute.

## Requirements

- Python 3.12+
- FFmpeg
- Telegram bot token
- Spotify Client ID and Client Secret

## Setup

Create `.env` from `.env.example` and fill in:

```
BOT_TOKEN=...
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

Then:

```bash
pip install -r requirements.txt
python -m app
```

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

## Current feature

Input:

`https://open.spotify.com/track/<id>`

Output: an MP3 Telegram audio message with title and artist metadata.

Albums, playlists, Spotify search, queues, history, and user accounts are intentionally out of scope for this first version.
