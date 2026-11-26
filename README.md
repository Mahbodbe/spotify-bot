---
title: Spotify Telegram Bot
emoji: 🎵
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Spotify Telegram Bot

Telegram bot for downloading Spotify tracks, playlists, and albums as tagged MP3s (with cover art and optional lyrics).

## How it works

Spotify's Web API provides track metadata (title, artist, album, cover, duration), not the raw audio stream. The bot resolves the track on Spotify, searches public audio sources via `yt-dlp` (YouTube first with flat multi-candidate duration matching, SoundCloud fallback), converts to MP3 with `FFmpeg`, embeds ID3 tags + cover art with `mutagen`, sends the audio to Telegram, and cleans up temporary files.

## Features

- **Single tracks**: Send any `open.spotify.com/track/...` or `spotify.link/...` URL.
- **Playlists & albums**: Download sequentially or packed into size-limited ZIP parts.
- **Inline search**: Send a song name directly and pick from top 5 Spotify results.
- **Quality & cache**: `/quality` (128 / 192 / 320 kbps), SQLite `file_id` cache, `/stats`, and `/cancel`.

## Deploy on Hugging Face Spaces (Free, Docker SDK)

1. Create a new Space on [Hugging Face](https://huggingface.co/new-space) with **SDK: Docker** (Blank template) and **Private** visibility.
2. Push this repo to the Space (`git remote add hf https://huggingface.co/spaces/<user>/<space> && git push hf main`).
3. In **Settings → Variables and secrets**, add these **Secrets**:
   - `BOT_TOKEN`
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - *(Optional)* `YT_COOKIES_B64` — base64-encoded YouTube `cookies.txt` if YouTube blocks datacenter IPs.
4. The container automatically runs as UID 1000, stores temp files in `/tmp/downloads`, and serves a health check on port `7860`.

## Local / Docker Compose

```bash
cp .env.example .env
# Fill in BOT_TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
docker compose up -d --build
```
