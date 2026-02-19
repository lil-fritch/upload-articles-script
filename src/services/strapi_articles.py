import traceback
import aiohttp
import random
from datetime import datetime
from pathlib import Path
from src.config import settings, OUTPUT_DIR
from src.utils.logger import setup_logger
from src.utils.filename_utils import get_safe_filename

logger = setup_logger("strapi_articles")


def extract_categories_and_tags(topic: str, keywords: list = None) -> tuple[list, list]:
    """
    Extract categories and tags from topic without LLM.
    Limited to 3 each to avoid excessive page generation.
    Uses random selection for categories to add variety.
    """
    topic_lower = topic.lower()
    
    # All possible categories based on topic patterns
    category_matches = []
    
    if any(word in topic_lower for word in ["strategy", "guide", "tips", "how to", "tactics", "professional", "tutorial"]):
        category_matches.append("strategy")
    if any(word in topic_lower for word in ["bankroll", "budget", "stakes", "money", "low", "high roller", "budget-friendly"]):
        category_matches.append("bankroll")
    if any(word in topic_lower for word in ["feature", "bonus", "free spins", "rtp", "volatility", "mechanics"]):
        category_matches.append("features")
    if any(word in topic_lower for word in ["vs", "comparison", "best", "top", "review", "rated"]):
        category_matches.append("reviews")
    if any(word in topic_lower for word in ["mobile", "ios", "android", "app", "download"]):
        category_matches.append("mobile")
    if any(word in topic_lower for word in ["free", "demo", "play for fun", "no deposit"]):
        category_matches.append("free-play")
    if any(word in topic_lower for word in ["real money", "cash", "win", "payout", "withdrawal"]):
        category_matches.append("real-money")
    if any(word in topic_lower for word in ["new", "2025", "2026", "release", "latest", "fresh"]):
        category_matches.append("new")
    
    # Randomly select up to 3 categories from matched
    if category_matches:
        # Remove duplicates while preserving order
        unique_categories = list(dict.fromkeys(category_matches))
        # Random shuffle and take up to 3
        random.shuffle(unique_categories)
        categories = unique_categories[:3]
    else:
        categories = ["general"]
    
    # Tags from topic words only (NO game_slug to avoid extra pages)
    stop_words = {
        "the", "a", "an", "for", "with", "and", "or", "in", "on", "at", "to", "of",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might",
        "that", "this", "these", "those", "it", "its", "as", "but", "by", "from",
        "players", "playing", "play", "game", "games", "slot", "slots"
    }
    
    # Extract meaningful words from topic
    topic_words = [w.strip(".,!?;:'\"()") for w in topic.split()]
    meaningful_words = [
        w.lower() for w in topic_words 
        if len(w) > 4 and w.lower() not in stop_words  # Min 5 chars for quality
    ]
    
    # Add keywords if provided (they're more relevant than topic words)
    tags = []
    if keywords and isinstance(keywords, list):
        tags.extend([k.lower().strip() for k in keywords[:2]])  # Max 2 keywords
    
    # Fill remaining with topic words
    for word in meaningful_words:
        if word not in tags and len(tags) < 3:
            tags.append(word)
    
    # Limit to 3 tags total
    tags = tags[:3]
    
    return categories, tags


async def upload_image_to_strapi(image_path: str, image_name: str) -> str | None:
    """
    Upload an image file to Strapi media library.
    Returns the internal Strapi image URL if successful, None otherwise.
    """
    if not settings.STRAPI_API_TOKEN:
        logger.warning("Strapi API token not configured for image upload.")
        return None

    image_file = Path(image_path)
    if not image_file.exists():
        logger.error(f"Image file not found: {image_path}")
        return None

    # Build base URL from STRAPI_ARTICLES_API_URL (remove /api/blog-posts suffix)
    base_url = settings.STRAPI_ARTICLES_API_URL
    if "/api/" in base_url:
        base_url = base_url.split("/api/")[0] + "/api"

    headers = {
        "Authorization": f"Bearer {settings.STRAPI_API_TOKEN}"
    }

    try:
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field("files", open(image_file, "rb"), filename=f"{image_name}.webp")

            upload_url = f"{base_url.rstrip('/')}/upload"
            async with session.post(upload_url, data=data, headers=headers) as response:
                if response.status in (200, 201):
                    result = await response.json()
                    # Strapi returns list of uploaded files
                    if isinstance(result, list) and len(result) > 0:
                        file_info = result[0]
                        # Get the URL from the uploaded file info
                        file_url = file_info.get("url", "")
                        # Handle relative URLs - construct full URL
                        if file_url.startswith("/"):
                            # Extract base URL (e.g., https://strapi.safercase.app)
                            if '/api' in base_url:
                                media_base = base_url.split('/api')[0]
                            else:
                                media_base = base_url.rstrip('/')
                            file_url = f"{media_base}{file_url}"
                        logger.info(f"Uploaded image to Strapi: {image_name}.webp -> {file_url}")
                        return file_url
                    else:
                        logger.error(f"Strapi upload returned unexpected format: {result}")
                        return None
                else:
                    error_text = await response.text()
                    logger.error(f"Strapi image upload failed ({response.status}): {error_text}")
                    return None

    except Exception as e:
        logger.error(f"Failed to upload image to Strapi: {e}")
        traceback.print_exc()
        return None


async def upload_article_to_strapi(
    article_path: str,
    topic: str,
    image_path: str | None = None
) -> bool:
    """
    Upload article to Strapi.
    If image_path is provided, upload the image first and use internal Strapi URL.
    """
    if not settings.STRAPI_ARTICLES_API_URL or not settings.STRAPI_API_TOKEN:
        logger.warning("Strapi credentials not configured, skipping upload.")
        return False

    try:
        with open(article_path, "r", encoding="utf-8") as f:
            content = f.read()

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

        # Remove H1 title from body if it duplicates the title (case-insensitive check)
        body_lines = body.split("\n")
        if body_lines and body_lines[0].strip().startswith("# "):
            h1_text = body_lines[0].strip()[2:].strip()
            if h1_text.lower() == title.lower() or h1_text.lower() == topic.lower():
                body = "\n".join(body_lines[1:]).strip()

        slug = get_safe_filename(topic)

        # Handle image upload
        image_value = ""
        if image_path:
            # Check if it's a local path or URL
            if Path(image_path).exists():
                # Upload local image to Strapi
                image_name = get_safe_filename(topic)
                image_value = await upload_image_to_strapi(image_path, image_name)
                if not image_value:
                    logger.warning("Image upload failed, proceeding without image")
            else:
                # It's already a URL, use as-is
                image_value = image_path

        # Extract categories and tags from topic
        keywords = frontmatter.get("keywords", [])
        if isinstance(keywords, str):
            # Handle JSON/YAML array string like "[]" or "['word1', 'word2']"
            keywords = keywords.strip()
            if keywords == "[]" or not keywords:
                keywords = []
            else:
                # Try to parse as comma-separated values
                keywords = [k.strip().strip("'\"") for k in keywords.split(",") if k.strip()]
        categories, tags = extract_categories_and_tags(topic, keywords)

        payload = {
            "data": {
                "title": title,
                "slug": slug,
                "meta_title": title,
                "description": frontmatter.get("description", ""),
                "date": datetime.now().isoformat(),
                "image": image_value,
                "author": "admin",
                "categories": categories,
                "tags": tags,
                "content": body,
                "draft": False
            }
        }

        headers = {
            "Authorization": f"Bearer {settings.STRAPI_API_TOKEN}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            check_url = f"{settings.STRAPI_ARTICLES_API_URL}?filters[slug][$eq]={slug}"
            async with session.get(check_url, headers=headers) as response:
                if response.status == 200:
                    existing = await response.json()
                    if existing.get("data") and len(existing["data"]) > 0:
                        article_id = existing["data"][0]["id"]
                        update_url = f"{settings.STRAPI_ARTICLES_API_URL}/{article_id}"
                        async with session.put(update_url, json=payload, headers=headers) as update_response:
                            if update_response.status in [200, 201]:
                                logger.info(f"Updated article in Strapi: {slug}")
                                return True
                            error_text = await update_response.text()
                            logger.error(f"Strapi update failed ({update_response.status}): {error_text}")
                            return False

            async with session.post(settings.STRAPI_ARTICLES_API_URL, json=payload, headers=headers) as response:
                if response.status in [200, 201]:
                    result = await response.json()
                    logger.info(f"Uploaded to Strapi: {slug} (ID: {result.get('data', {}).get('id', 'unknown')})")
                    return True
                error_text = await response.text()
                logger.error(f"Strapi upload failed ({response.status}): {error_text}")
                return False

    except Exception as e:
        logger.error(f"Failed to upload to Strapi: {e}")
        traceback.print_exc()
        return False
