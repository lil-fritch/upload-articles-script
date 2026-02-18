import aiohttp
import asyncio
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("scraper_service")

class ScraperService:
    """
    Service to fetch content using Jina Reader API.
    """
    def __init__(self, timeout: int = 30):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.api_key = settings.JINA_API_KEY
        self._session = None
        
        self.headers = {
             "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
             "X-Retain-Images": "none",
             "X-Remove-Selector": "nav, footer, header, script, style, aside, form, iframe, .ads, .sidebar, .widget, .related, .comments, .cookie-notice, .newsletter-signup, .social-share, .menu",
             "X-Return-Format": "markdown",
        }
        self.jina_prefix = "https://r.jina.ai/"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout, headers=self.headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def fetch_content(self, url: str) -> str:
        """
        Fetches the Markdown content of a URL using Jina.
        """
        target_url = f"{self.jina_prefix}{url}"
        
        try:
            session = await self._get_session()
            async with session.get(target_url) as response:
                if response.status == 429:
                    logger.warning(f"Rate limit hit for {url}. Sleeping 2s...")
                    await asyncio.sleep(2)
                    return ""

                if response.status != 200:
                    logger.warning(f"Failed to fetch {url} via Jina: Status {response.status}")
                    return ""

                text = await response.text()

                if len(text) < 100:
                    logger.warning(f"Content too short for {url} ({len(text)} chars). Skipping.")
                    return ""

                return text
        except Exception as e:
            logger.error(f"Error scraping {url} with Jina: {e}")
            return ""