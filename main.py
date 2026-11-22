import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

from qm.bot import Quartermaster  # noqa: E402  (after load_dotenv so env settings are visible)

if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    Quartermaster().run(token, log_handler=None)
