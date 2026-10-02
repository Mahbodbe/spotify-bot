import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str
    spotify_client_id: str
    spotify_client_secret: str
    download_dir: str
    max_file_size_mb: int

    @classmethod
    def from_env(cls):
        values = {
            "BOT_TOKEN": os.getenv("BOT_TOKEN"),
            "SPOTIFY_CLIENT_ID": os.getenv("SPOTIFY_CLIENT_ID"),
            "SPOTIFY_CLIENT_SECRET": os.getenv("SPOTIFY_CLIENT_SECRET"),
        }
        missing = [k for k, v in values.items() if not v]
        if missing:
            raise RuntimeError("Missing environment variables: " + ", ".join(missing))
        return cls(
            bot_token=values["BOT_TOKEN"],
            spotify_client_id=values["SPOTIFY_CLIENT_ID"],
            spotify_client_secret=values["SPOTIFY_CLIENT_SECRET"],
            download_dir=os.getenv("DOWNLOAD_DIR", "downloads"),
            max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", "45")),
        )
