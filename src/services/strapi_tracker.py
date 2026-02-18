"""
Strapi-based progress tracker for daemon mode.
Uses Strapi API as the single source of truth for tracking generated articles.
"""
import asyncio
import aiohttp
from datetime import datetime
from typing import Set, Dict, List, Optional
from src.config import settings
from src.utils.logger import setup_logger
from src.utils.filename_utils import get_safe_filename

logger = setup_logger("strapi_tracker")


class StrapiTracker:
    """
    Tracks daemon progress using Strapi API.
    - Fetches all published articles to determine what's already generated
    - Stores pending topics in Strapi (optional, for resume capability)
    - Provides daily limit tracking via local state (resets at midnight)
    """

    def __init__(self):
        self.api_url = settings.STRAPI_ARTICLES_API_URL
        self.api_token = settings.STRAPI_API_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        } if self.api_token else {}

    async def check_connection(self) -> bool:
        """
        Check if Strapi is accessible.
        Returns True if connection successful, False otherwise.
        """
        if not self.api_url or not self.api_token:
            logger.error("Strapi credentials not configured")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                # Try to fetch first page with minimal fields
                url = f"{self.api_url}?pagination[pageSize]=1&fields[0]=id"
                async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        logger.info("Strapi connection successful")
                        return True
                    else:
                        logger.error(f"Strapi connection failed: {response.status}")
                        return False
        except asyncio.TimeoutError:
            logger.error("Strapi connection timed out")
            return False
        except Exception as e:
            logger.error(f"Strapi connection error: {e}")
            return False

    async def get_all_published_articles(self) -> List[Dict]:
        """
        Fetch all published articles from Strapi.
        Returns list of article dicts with: id, slug, title, topic, game_slug, created_at
        """
        if not self.api_url or not self.api_token:
            logger.warning("Strapi not configured")
            return []

        all_articles = []
        page = 1
        page_size = 100

        try:
            async with aiohttp.ClientSession() as session:
                while True:
                    url = (
                        f"{self.api_url}?"
                        f"pagination[page]={page}&"
                        f"pagination[pageSize]={page_size}&"
                        f"fields[0]=slug&"
                        f"fields[1]=title&"
                        f"fields[2]=topic&"
                        f"fields[3]=game_slug&"
                        f"fields[4]=created_at"
                    )

                    async with session.get(url, headers=self.headers) as response:
                        if response.status != 200:
                            logger.error(f"Failed to fetch Strapi articles (page {page}): {response.status}")
                            break

                        data = await response.json()
                        articles = data.get("data", [])

                        if not articles:
                            break

                        for article in articles:
                            attrs = article.get("attributes", {})
                            all_articles.append({
                                "id": article.get("id"),
                                "slug": attrs.get("slug", ""),
                                "title": attrs.get("title", ""),
                                "topic": attrs.get("topic", attrs.get("title", "")),
                                "game_slug": attrs.get("game_slug", ""),
                                "created_at": attrs.get("created_at", "")
                            })

                        # Check if there are more pages
                        pagination = data.get("meta", {}).get("pagination", {})
                        if page >= pagination.get("pageCount", 1):
                            break

                        page += 1

            logger.info(f"Fetched {len(all_articles)} articles from Strapi")
            return all_articles

        except Exception as e:
            logger.error(f"Failed to fetch Strapi articles: {e}")
            return []

    async def get_published_slugs(self) -> Set[str]:
        """
        Get set of all published article slugs.
        Used for quick duplicate checking.
        """
        articles = await self.get_all_published_articles()
        return {article["slug"] for article in articles if article.get("slug")}

    async def get_published_topics(self) -> Set[str]:
        """
        Get set of all published topics (normalized).
        Used to check if a topic was already generated.
        """
        articles = await self.get_all_published_articles()
        # Normalize topics: lowercase, strip whitespace
        return {
            article["topic"].lower().strip()
            for article in articles
            if article.get("topic")
        }

    async def is_topic_published(self, topic: str) -> bool:
        """
        Check if a topic was already published to Strapi.
        """
        published_topics = await self.get_published_topics()
        return topic.lower().strip() in published_topics

    async def is_slug_published(self, slug: str) -> bool:
        """
        Check if a slug already exists in Strapi.
        """
        published_slugs = await self.get_published_slugs()
        return slug.lower() in published_slugs

    async def record_generation(
        self,
        topic: str,
        article_path: str,
        game_slug: str,
        image_url: str = ""
    ) -> bool:
        """
        Record a newly generated article to Strapi.
        This is called after successful article generation and upload.
        """
        # The article should already be uploaded via upload_article_to_strapi
        # This method is for additional tracking if needed
        return True

    async def get_daily_count(self, date_str: str) -> int:
        """
        Get count of articles generated on a specific date.
        Uses created_at field from Strapi.
        """
        articles = await self.get_all_published_articles()
        count = 0

        for article in articles:
            created_at = article.get("created_at", "")
            if created_at.startswith(date_str):
                count += 1

        return count


# Global instance
tracker = StrapiTracker()


async def check_strapi_connection() -> bool:
    """Check Strapi connection at startup. Exit if failed."""
    connected = await tracker.check_connection()
    if not connected:
        logger.error("Strapi connection failed. Daemon cannot start without Strapi.")
        return False
    return True


async def get_existing_articles() -> List[Dict]:
    """Get all existing articles from Strapi."""
    return await tracker.get_all_published_articles()


async def get_existing_slugs() -> Set[str]:
    """Get set of existing article slugs from Strapi."""
    return await tracker.get_published_slugs()


async def get_existing_topics() -> Set[str]:
    """Get set of existing topics from Strapi."""
    return await tracker.get_published_topics()
