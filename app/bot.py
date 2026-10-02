import asyncio
import html
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message

from .config import Settings
from .downloader import AudioDownloader, DownloadError
from .spotify import SpotifyService

log = logging.getLogger(__name__)

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
        self.user_locks = {}
        self.global_semaphore = asyncio.Semaphore(2)

        self.dp.message.register(self.start, CommandStart())
        self.dp.message.register(self.handle_text, F.text)

    async def start(self, message: Message):
        await message.answer(
            "🎵 سلام! لینک آهنگ Spotify رو بفرست تا نسخه صوتی‌ش رو برات ارسال کنم.\n\n"
            "فعلاً فقط لینک Track پشتیبانی می‌شه."
        )

    async def handle_text(self, message: Message):
        url = (message.text or "").strip()
        if not self.spotify.extract_track_id(url):
            await message.answer(
                "❌ لینک معتبر Spotify Track نیست.\n"
                "مثال: https://open.spotify.com/track/..."
            )
            return

        user_id = message.from_user.id if message.from_user else message.chat.id
        lock = self.user_locks.setdefault(user_id, asyncio.Lock())
        if lock.locked():
            await message.answer("⏳ درخواست قبلیت هنوز در حال پردازشه.")
            return

        async with lock:
            status = await message.answer("🔎 اطلاعات آهنگ رو می‌گیرم...")
            path = None
            try:
                track = await asyncio.to_thread(self.spotify.get_track, url)
                if not track:
                    await status.edit_text("❌ اطلاعات آهنگ پیدا نشد.")
                    return

                await status.edit_text(
                    f"🎵 <b>{html.escape(track.title)}</b>\n"
                    f"👤 {html.escape(track.artist_text)}\n"
                    f"💿 {html.escape(track.album)}\n\n"
                    "🔎 دارم نسخه صوتی مناسب رو پیدا می‌کنم..."
                )

                async with self.global_semaphore:
                    await self.bot.send_chat_action(
                        message.chat.id, ChatAction.UPLOAD_AUDIO
                    )
                    path = await self.downloader.download(track)

                await status.edit_text("📤 فایل آماده‌ست؛ دارم می‌فرستم...")
                await message.answer_audio(
                    FSInputFile(path),
                    title=track.title,
                    performer=track.artist_text,
                    caption=f"🎵 {track.title}\n👤 {track.artist_text}",
                )
                await status.delete()

            except DownloadError:
                log.warning("Could not download Spotify track: %s", url)
                await status.edit_text(
                    "❌ نتونستم یک نسخه صوتی قابل‌اعتماد برای این آهنگ پیدا کنم.\n"
                    "ممکنه منبع عمومی مناسب پیدا نشه یا فایل بیش از حد بزرگ باشه."
                )
            except Exception:
                log.exception("Unhandled error while processing Spotify URL")
                await status.edit_text("⚠️ یک خطای غیرمنتظره رخ داد؛ دوباره امتحان کن.")
            finally:
                if isinstance(path, Path):
                    path.unlink(missing_ok=True)

    async def run(self):
        await self.dp.start_polling(self.bot)

async def main():
    settings = Settings.from_env()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    await SpotifyBot(settings).run()
