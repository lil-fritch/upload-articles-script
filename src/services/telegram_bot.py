import aiohttp
import asyncio
import os
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("telegram_bot")

class TelegramBot:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    async def send_message(self, text: str):
        if not self.token or not self.chat_id:
            logger.warning("Telegram token or chat_id not set. Skipping message.")
            return

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text
            # parse_mode disabled to avoid formatting issues with underscores
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        logger.error(f"Failed to send Telegram message: {await response.text()}")
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

    async def send_photo(self, photo_path: str, caption: str = ""):
        if not self.token or not self.chat_id:
            logger.warning("Telegram token or chat_id not set. Skipping photo.")
            return

        if not os.path.exists(photo_path):
            logger.error(f"Photo file not found: {photo_path}")
            await self.send_message(f"Error: Photo not found at {photo_path}\nCaption: {caption}")
            return

        url = f"{self.base_url}/sendPhoto"
        data = aiohttp.FormData()
        data.add_field("chat_id", self.chat_id)
        data.add_field("caption", caption)
        # parse_mode disabled to avoid formatting issues with underscores

        try:
            # Open file in binary mode
            with open(photo_path, "rb") as f:
                data.add_field("photo", f, filename=os.path.basename(photo_path))

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=data) as response:
                        if response.status != 200:
                            logger.error(f"Failed to send Telegram photo: {await response.text()}")
        except Exception as e:
            logger.error(f"Error sending Telegram photo: {e}")

    async def send_document(self, file_path: str, caption: str = ""):
        if not self.token or not self.chat_id:
            logger.warning("Telegram token or chat_id not set. Skipping document.")
            return

        if not os.path.exists(file_path):
            logger.error(f"Document file not found: {file_path}")
            await self.send_message(f"Error: Document not found at {file_path}\nCaption: {caption}")
            return

        url = f"{self.base_url}/sendDocument"
        data = aiohttp.FormData()
        data.add_field("chat_id", self.chat_id)
        data.add_field("caption", caption)
        # parse_mode disabled to avoid formatting issues with underscores

        try:
            # Open file in binary mode
            with open(file_path, "rb") as f:
                data.add_field("document", f, filename=os.path.basename(file_path))

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=data) as response:
                        if response.status != 200:
                            logger.error(f"Failed to send Telegram document: {await response.text()}")
        except Exception as e:
            logger.error(f"Error sending Telegram document: {e}")

# Global instance
telegram_bot = TelegramBot()
