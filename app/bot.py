import asyncio
import html
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .config import Settings
from .downloader import AudioDownloader, Cancelled, DownloadError
from .history import History
from .spotify import SpotifyService

log = logging.getLogger(__name__)

QUALITIES = (128, 192, 320)
MAX_CAPTION = 1000


def quality_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{q} kbps", callback_data=f"q:{q}")
        for q in QUALITIES
    ]])


def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ لغو", callback_data="cancel")
    ]])


def collection_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 همه رو یجا (ZIP)",
                              callback_data="pl:zip")],
        [InlineKeyboardButton(text="🎵 دونه‌دونه بفرست",
                              callback_data="pl:seq")],
        [InlineKeyboardButton(text="❌ بیخیال", callback_data="pl:no")],
    ])


def search_keyboard(tracks):
    rows = []
    for t in tracks:
        label = f"{t.title} — {t.artist_text}"[:60]
        rows.append([InlineKeyboardButton(text=label,
                                          callback_data=f"s:{t.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def fmt_duration(ms):
    s = int(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


class SpotifyBot:
    def __init__(self, settings):
        self.settings = settings
        self.bot = Bot(settings.bot_token)
        self.dp = Dispatcher()
        self.spotify = SpotifyService(
            settings.spotify_client_id,
            settings.spotify_client_secret,
        )
        self.downloader = AudioDownloader(
            settings.download_dir,
            settings.max_file_size_mb,
        )
        self.history = History(
            str(Path(settings.download_dir) / "history.db"))
        self.user_locks = {}
        self.cancel_events = {}
        self.pending_search = {}   # user_id -> {track_id: Track}
        self.pending_coll = {}     # user_id -> Collection
        self.global_semaphore = asyncio.Semaphore(2)

        self.dp.message.register(self.start, CommandStart())
        self.dp.message.register(self.cmd_quality, Command("quality"))
        self.dp.message.register(self.cmd_stats, Command("stats"))
        self.dp.message.register(self.cmd_cancel, Command("cancel"))
        self.dp.message.register(
            self.handle_text, F.text & ~F.text.startswith("/"))
        self.dp.callback_query.register(
            self.on_quality, F.data.startswith("q:"))
        self.dp.callback_query.register(
            self.on_search_pick, F.data.startswith("s:"))
        self.dp.callback_query.register(
            self.on_collection, F.data.startswith("pl:"))
        self.dp.callback_query.register(self.on_cancel, F.data == "cancel")

    # -- helpers --
    def _lock(self, user_id):
        return self.user_locks.setdefault(user_id, asyncio.Lock())

    def _cancel_event(self, user_id):
        ev = asyncio.Event()
        self.cancel_events[user_id] = ev
        return ev

    def _clear_cancel(self, user_id):
        self.cancel_events.pop(user_id, None)

    @staticmethod
    def _uid(message: Message):
        return message.from_user.id if message.from_user else message.chat.id

    # -- commands --
    async def start(self, message: Message):
        await message.answer(
            "🎵 سلام! لینک آهنگ Spotify رو بفرست تا نسخه صوتی‌ش رو برات ارسال کنم.\n\n"
            "• تک‌آهنگ (Track) → مستقیم MP3\n"
            "• پلی‌لیست / آلبوم → انتخاب ZIP یا دونه‌دونه\n"
            "• یا اسم آهنگ رو بنویس تا سرچ کنم 🔎\n\n"
            "دستورات:\n"
            "/quality — انتخاب کیفیت صدا\n"
            "/stats — آمار دانلودهای خودت\n"
            "/cancel — لغو دانلود جاری"
        )

    async def cmd_quality(self, message: Message):
        cur = self.history.get_quality(
            self._uid(message), self.settings.default_quality)
        await message.answer(
            f"🎚 کیفیت فعلی: <b>{cur} kbps</b>\nیکی رو انتخاب کن:",
            reply_markup=quality_keyboard(),
        )

    async def cmd_stats(self, message: Message):
        st = self.history.stats(self._uid(message))
        mb = st["bytes"] / (1024 * 1024)
        await message.answer(
            f"📊 آمار تو:\n🎵 {st['count']} آهنگ\n💾 {mb:.1f} مگابایت"
        )

    async def cmd_cancel(self, message: Message):
        ev = self.cancel_events.get(self._uid(message))
        if ev is not None:
            ev.set()
            await message.answer("❌ درخواست لغو ثبت شد...")
        else:
            await message.answer("کاری در حال اجرا نیست.")

    # -- callbacks --
    async def on_quality(self, query: CallbackQuery):
        await query.answer()
        try:
            q = int((query.data or "").split(":")[1])
        except (IndexError, ValueError):
            return
        if q not in QUALITIES:
            return
        self.history.set_quality(query.from_user.id, q)
        try:
            await query.message.edit_text(
                f"✅ کیفیت پیش‌فرض شد <b>{q} kbps</b>")
        except Exception:
            pass

    async def on_cancel(self, query: CallbackQuery):
        await query.answer("لغو شد")
        ev = self.cancel_events.get(query.from_user.id)
        if ev is not None:
            ev.set()

    async def on_search_pick(self, query: CallbackQuery):
        await query.answer()
        tid = (query.data or "")[2:]
        tracks = self.pending_search.get(query.from_user.id, {})
        track = tracks.get(tid)
        if not track:
            try:
                await query.message.edit_text(
                    "⏳ منقضی شده؛ اسم آهنگ رو دوباره بفرست.")
            except Exception:
                pass
            return
        try:
            await query.message.delete()
        except Exception:
            pass
        fake = query.message
        await self._send_track(fake, track, query.from_user.id)

    async def on_collection(self, query: CallbackQuery):
        await query.answer()
        mode = (query.data or "").split(":")[1] if ":" in (query.data or "") else ""
        coll = self.pending_coll.pop(query.from_user.id, None)
        if mode == "no" or not coll:
            try:
                await query.message.edit_text("باشه، بیخیال شدیم. 👍")
            except Exception:
                pass
            return
        try:
            await query.message.delete()
        except Exception:
            pass
        if mode == "zip":
            await self._send_collection_zip(query.message, coll,
                                            query.from_user.id)
        else:
            await self._send_collection_seq(query.message, coll,
                                            query.from_user.id)

    # -- main text handler --
    async def handle_text(self, message: Message):
        url = (message.text or "").strip()
        user_id = self._uid(message)

        if self.spotify.extract_track_id(url):
            track = await asyncio.to_thread(self.spotify.get_track, url)
            if not track:
                await message.answer("❌ اطلاعات آهنگ پیدا نشد.")
                return
            await self._send_track(message, track, user_id)
            return

        if self.spotify.extract_collection(url):
            await self._handle_collection(message, url, user_id)
            return

        # Plain text → Spotify search
        status = await message.answer("🔎 دارم سرچ می‌کنم...")
        try:
            tracks = await asyncio.to_thread(
                self.spotify.search_tracks, url, 5)
        except Exception:
            log.exception("Spotify search failed")
            await status.edit_text("⚠️ سرچ به مشکل خورد؛ دوباره امتحان کن.")
            return
        if not tracks:
            await status.edit_text("❌ چیزی پیدا نشد. دقیق‌تر بنویس.")
            return
        self.pending_search[user_id] = {t.id: t for t in tracks}
        try:
            await status.delete()
        except Exception:
            pass
        await message.answer("🔎 اینا رو پیدا کردم، یکیش رو انتخاب کن:",
                             reply_markup=search_keyboard(tracks))

    # -- single track --
    async def _send_track(self, message: Message, track, user_id):
        quality = self.history.get_quality(
            user_id, self.settings.default_quality)
        cached = self.history.get_cached(user_id, track.id)
        if cached and cached["quality"] == quality:
            await message.answer_audio(
                audio=cached["file_id"],
                caption=f"🎵 {track.title}\n👤 {track.artist_text} (از حافظه ⚡)",
            )
            return

        lock = self._lock(user_id)
        if lock.locked():
            await message.answer("⏳ درخواست قبلیت هنوز در حال پردازشه.")
            return
        async with lock:
            cancel_ev = self._cancel_event(user_id)
            status = await message.answer(
                f"🎵 <b>{html.escape(track.title)}</b>\n"
                f"👤 {html.escape(track.artist_text)}\n"
                f"🎚 {quality} kbps — دارم دانلود می‌کنم...",
                reply_markup=cancel_keyboard(),
            )
            path = None
            try:
                async with self.global_semaphore:
                    await self.bot.send_chat_action(
                        message.chat.id, ChatAction.UPLOAD_VOICE)
                    path, lyrics = await self.downloader.download(
                        track, quality, cancel_ev)
                await status.edit_text("📤 فایل آماده‌ست؛ دارم می‌فرستم...")
                caption = f"🎵 {track.title}\n👤 {track.artist_text}"
                sent = await message.answer_audio(
                    FSInputFile(path),
                    title=track.title,
                    performer=track.artist_text,
                    caption=caption[:MAX_CAPTION],
                )
                if sent.audio:
                    self.history.save(
                        user_id, track.id, track.title,
                        track.artist_text, sent.audio.file_id,
                        quality, path.stat().st_size)
                await status.delete()
                if lyrics:
                    await message.answer(
                        f"📝 متن آهنگ:\n\n{lyrics[:3500]}")
            except Cancelled:
                await status.edit_text("❌ لغو شد.")
            except DownloadError:
                log.warning("Could not download Spotify track: %s",
                            track.url)
                await status.edit_text(
                    "❌ نتونستم یک نسخه صوتی قابل‌اعتماد برای این آهنگ پیدا کنم.\n"
                    "ممکنه منبع عمومی مناسب پیدا نشه یا فایل بیش از حد بزرگ باشه."
                )
            except Exception:
                log.exception("Unhandled error while processing Spotify URL")
                await status.edit_text("⚠️ یک خطای غیرمنتظره رخ داد؛ دوباره امتحان کن.")
            finally:
                self._clear_cancel(user_id)
                if isinstance(path, Path):
                    try:
                        shutil.rmtree(path.parent, ignore_errors=True)
                    except Exception:
                        pass

    # -- collection (playlist/album) --
    async def _handle_collection(self, message: Message, url, user_id):
        status = await message.answer("📋 دارم لیست آهنگ‌ها رو می‌گیرم...")
        try:
            coll = await asyncio.to_thread(
                self.spotify.get_collection, url)
        except Exception:
            log.exception("Collection fetch failed")
            await status.edit_text("⚠️ نتونستم پلی‌لیست رو بخونم. (ممکنه خصوصی باشه)")
            return
        if not coll or not coll.tracks:
            await status.edit_text("❌ آهنگی توی این لیست پیدا نشد.")
            return
        tracks = coll.tracks[:self.settings.max_playlist_tracks]
        total_ms = sum(t.duration_ms for t in tracks)
        lines = [f"📋 <b>{html.escape(coll.name)}</b> ({coll.kind})",
                 f"🎵 {len(tracks)} آهنگ" +
                 (f" (از {len(coll.tracks)}، سقف {self.settings.max_playlist_tracks})"
                  if len(coll.tracks) > len(tracks) else "") +
                 f" ⏱ {fmt_duration(total_ms)}",
                 ""]
        for i, t in enumerate(tracks[:10], 1):
            lines.append(f"{i}. {html.escape(t.title)} —"
                         f" {html.escape(t.artist_text)}")
        if len(tracks) > 10:
            lines.append(f"... و {len(tracks) - 10} تای دیگه")
        lines.append("\nچطور بفرستم؟")
        self.pending_coll[user_id] = coll.__class__(
            coll.kind, coll.id, coll.name, tuple(tracks))
        await status.edit_text("\n".join(lines),
                               reply_markup=collection_keyboard())

    async def _download_many(self, message, tracks, user_id, status):
        """Download each track; returns list of (Track, Path, lyrics)."""
        quality = self.history.get_quality(
            user_id, self.settings.default_quality)
        cancel_ev = self._cancel_event(user_id)
        done = []
        try:
            for i, t in enumerate(tracks, 1):
                if cancel_ev.is_set():
                    raise Cancelled("cancelled by user")
                await status.edit_text(
                    f"⏳ {i}/{len(tracks)}: {html.escape(t.title)}...",
                    reply_markup=cancel_keyboard())
                async with self.global_semaphore:
                    path, lyrics = await self.downloader.download(
                        t, quality, cancel_ev)
                done.append((t, path, lyrics))
        finally:
            self._clear_cancel(user_id)
        return done

    @staticmethod
    def _cleanup(paths):
        seen = set()
        for p in paths:
            try:
                d = Path(p).parent
                if str(d) not in seen:
                    seen.add(str(d))
                    shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    async def _send_collection_seq(self, message, coll, user_id):
        lock = self._lock(user_id)
        if lock.locked():
            await message.answer("⏳ درخواست قبلیت هنوز در حال پردازشه.")
            return
        async with lock:
            status = await message.answer(
                f"🎵 شروع دانلود تکی {len(coll.tracks)} آهنگ...",
                reply_markup=cancel_keyboard())
            try:
                done = await self._download_many(
                    message, list(coll.tracks), user_id, status)
            except Cancelled:
                await status.edit_text("❌ لغو شد.")
                return
            except DownloadError as e:
                await status.edit_text(f"❌ خطا در دانلود: {e}")
                return
            await status.edit_text(f"📤 {len(done)} آهنگ آماده‌ست؛ می‌فرستم...")
            for t, path, _lyrics in done:
                try:
                    sent = await message.answer_audio(
                        FSInputFile(path),
                        title=t.title, performer=t.artist_text,
                        caption=f"🎵 {t.title}\n👤 {t.artist_text}"[:MAX_CAPTION],
                    )
                    if sent.audio:
                        self.history.save(
                            user_id, t.id, t.title, t.artist_text,
                            sent.audio.file_id,
                            self.history.get_quality(
                                user_id, self.settings.default_quality),
                            path.stat().st_size)
                except Exception:
                    log.exception("Failed sending track %s", t.id)
            await status.delete()
            self._cleanup([p for _, p, _ in done])

    async def _send_collection_zip(self, message, coll, user_id):
        lock = self._lock(user_id)
        if lock.locked():
            await message.answer("⏳ درخواست قبلیت هنوز در حال پردازشه.")
            return
        async with lock:
            status = await message.answer(
                f"📦 شروع دانلود {len(coll.tracks)} آهنگ برای ZIP...",
                reply_markup=cancel_keyboard())
            try:
                done = await self._download_many(
                    message, list(coll.tracks), user_id, status)
            except Cancelled:
                await status.edit_text("❌ لغو شد.")
                return
            except DownloadError as e:
                await status.edit_text(f"❌ خطا در دانلود: {e}")
                return
            if not done:
                await status.edit_text("❌ هیچ فایلی دانلود نشد.")
                return
            await status.edit_text("📦 دارم زیپ می‌کنم...")
            max_bytes = self.settings.max_file_size_mb * 1024 * 1024
            tmpdir = Path(tempfile.mkdtemp(prefix="spzip-"))
            parts = []
            idx = 1
            current = None
            current_size = 0

            def new_part():
                nonlocal idx, current, current_size
                if current:
                    current.close()
                name = f"{coll.name}-part{idx}.zip" if len(done) > 1 else f"{coll.name}.zip"
                safe = "".join(
                    c for c in name if c not in '<>:"/\\|?*')[:120] or "playlist.zip"
                zp = tmpdir / safe
                current = zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED)
                parts.append(zp)
                current_size = 0
                idx += 1

            new_part()
            from .downloader import safe_name as _safe
            for t, path, _lyrics in done:
                size = path.stat().st_size
                if current_size + size > max_bytes and current_size > 0:
                    new_part()
                arcname = f"{_safe(f'{t.artist_text} - {t.title}')}.mp3"
                current.write(path, arcname)
                current_size += size
            if current:
                current.close()
            await status.edit_text(f"📤 {len(parts)} فایل ZIP آماده‌ست؛ می‌فرستم...")
            for zp in parts:
                try:
                    await message.answer_document(
                        FSInputFile(zp),
                        caption=f"📦 {coll.name} ({len(done)} آهنگ)"[:MAX_CAPTION],
                    )
                except Exception:
                    log.exception("Failed sending zip %s", zp)
            await status.delete()
            self._cleanup([p for _, p, _ in done])
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def run(self):
        await self.dp.start_polling(self.bot)


async def main():
    settings = Settings.from_env()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    await SpotifyBot(settings).run()
