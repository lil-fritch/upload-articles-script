"""
Strapi synchronization utilities
- Upload pending local articles
- Download existing slugs to avoid duplicates
"""
import asyncio
import aiohttp
from pathlib import Path
from typing import Set
from src.config import settings, OUTPUT_DIR
from src.utils.logger import setup_logger
from src.utils.filename_utils import get_safe_filename

logger = setup_logger("strapi_sync")

ARTICLES_DIR = OUTPUT_DIR / "articles"
GENERATED_LOG_PATH = OUTPUT_DIR / "generated_topics.log"


async def get_existing_strapi_slugs() -> Set[str]:
    """Fetch all existing article slugs from Strapi"""
    if not settings.STRAPI_ARTICLES_API_URL or not settings.STRAPI_API_TOKEN:
        logger.warning("Strapi not configured, skipping sync.")
        return set()
    
    headers = {
        "Authorization": f"Bearer {settings.STRAPI_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    existing_slugs = set()
    page = 1
    page_size = 100
    
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                url = f"{settings.STRAPI_ARTICLES_API_URL}?pagination[page]={page}&pagination[pageSize]={page_size}&fields[0]=slug"
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch Strapi articles (page {page}): {response.status}")
                        break
                    
                    data = await response.json()
                    articles = data.get("data", [])
                    
                    if not articles:
                        break
                    
                    for article in articles:
                        slug = article.get("attributes", {}).get("slug")
                        if slug:
                            existing_slugs.add(slug)
                    
                    # Check if there are more pages
                    pagination = data.get("meta", {}).get("pagination", {})
                    if page >= pagination.get("pageCount", 1):
                        break
                    
                    page += 1
        
        logger.info(f"Found {len(existing_slugs)} existing articles in Strapi")
        return existing_slugs
    
    except Exception as e:
        logger.error(f"Failed to fetch Strapi slugs: {e}")
        return set()


async def upload_article_to_strapi(article_path: Path, topic: str) -> bool:
    """Upload a single article to Strapi (reusable from main.py)"""
    if not settings.STRAPI_ARTICLES_API_URL or not settings.STRAPI_API_TOKEN:
        return False
    
    try:
        with open(article_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Parse frontmatter
        frontmatter = {}
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) == 3:
                fm_text = parts[1].strip()
                for line in fm_text.split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        frontmatter[key.strip()] = value.strip()
                body = parts[2].strip()
        
        title = frontmatter.get("title", topic)
        slug = get_safe_filename(topic)
        
        payload = {
            "data": {
                "title": title,
                "slug": slug,
                "meta_title": title,
                "description": frontmatter.get("description", ""),
                "date": article_path.stat().st_mtime,  # Use file modification time
                "image": "",
                "author": "admin",
                "categories": [],
                "tags": [],
                "content": body,
                "draft": False
            }
        }
        
        headers = {
            "Authorization": f"Bearer {settings.STRAPI_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            # Check if exists
            check_url = f"{settings.STRAPI_ARTICLES_API_URL}?filters[slug][$eq]={slug}"
            async with session.get(check_url, headers=headers) as response:
                if response.status == 200:
                    existing = await response.json()
                    if existing.get("data") and len(existing["data"]) > 0:
                        article_id = existing["data"][0]["id"]
                        update_url = f"{settings.STRAPI_ARTICLES_API_URL}/{article_id}"
                        async with session.put(update_url, json=payload, headers=headers) as update_response:
                            if update_response.status in [200, 201]:
                                return True
                            return False
            
            # Create new
            async with session.post(settings.STRAPI_ARTICLES_API_URL, json=payload, headers=headers) as response:
                return response.status in [200, 201]
    
    except Exception as e:
        logger.error(f"Failed to upload {article_path.name}: {e}")
        return False


async def sync_local_to_strapi() -> int:
    """Upload all local articles that are not in generated log (pending uploads)"""
    if not ARTICLES_DIR.exists():
        logger.info("No articles directory found, skipping sync.")
        return 0
    
    # Load existing log
    logged_topics = set()
    if GENERATED_LOG_PATH.exists():
        try:
            with open(GENERATED_LOG_PATH, "r", encoding="utf-8") as f:
                logged_topics = set(line.strip() for line in f if line.strip())
        except Exception as e:
            logger.error(f"Failed to read generated log: {e}")
    
    # Get Strapi slugs
    strapi_slugs = await get_existing_strapi_slugs()
    
    # Find pending uploads
    articles = list(ARTICLES_DIR.glob("*.md"))
    pending = []
    
    for article in articles:
        # Derive topic from filename
        topic = article.stem.replace("_", " ")
        slug = article.stem
        
        # Skip if already uploaded or in Strapi
        if topic in logged_topics or slug in strapi_slugs:
            continue
        
        pending.append((article, topic))
    
    if not pending:
        logger.info("No pending articles to upload.")
        return 0
    
    logger.info(f"Uploading {len(pending)} pending articles to Strapi...")
    
    uploaded = 0
    for article_path, topic in pending:
        success = await upload_article_to_strapi(article_path, topic)
        if success:
            uploaded += 1
            # Add to log
            try:
                with open(GENERATED_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(topic + "\n")
            except Exception as e:
                logger.error(f"Failed to update log: {e}")
            logger.info(f"✓ Uploaded: {article_path.name}")
        else:
            logger.warning(f"✗ Failed: {article_path.name}")
    
    logger.info(f"Sync complete: {uploaded}/{len(pending)} uploaded")
    return uploaded


async def sync_startup():
    """Run full sync on startup: upload pending + download existing slugs"""
    logger.info("=" * 60)
    logger.info("Starting Strapi synchronization...")
    logger.info("=" * 60)
    
    # Step 1: Get existing Strapi articles
    strapi_slugs = await get_existing_strapi_slugs()
    
    # Step 2: Upload pending local articles
    uploaded = await sync_local_to_strapi()
    
    logger.info("=" * 60)
    logger.info(f"Sync complete | Strapi: {len(strapi_slugs)} articles | Uploaded: {uploaded}")
    logger.info("=" * 60)
    
    return strapi_slugs


def sync_startup_blocking() -> Set[str]:
    """Blocking wrapper for use in main.py"""
    try:
        return asyncio.run(sync_startup())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(sync_startup())
