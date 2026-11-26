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

## Deploy Free on Render (Docker + Auto Webhook)

1. Go to [Render](https://dashboard.render.com) → **New → Web Service** → connect this GitHub repo.
2. Choose **Language: Docker** and **Instance Type: Free**.
3. Add these **Environment Variables**:
   - `BOT_TOKEN`
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - *(Optional)* `YT_COOKIES_B64` — base64-encoded YouTube `cookies.txt` if YouTube blocks datacenter IPs.
4. Deploy. Render automatically provides `RENDER_EXTERNAL_URL` and `PORT`, so the bot auto-switches to **Webhook mode** (waking up automatically whenever a Telegram message arrives).

## Local / Docker Compose

```bash
cp .env.example .env
# Fill in BOT_TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
docker compose up -d --build
```
