import asyncio
import csv
import json
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from src.config import OUTPUT_DIR, DB_FILE, settings
from src.production.graph import GraphBuilder
from src.planning.game_selector import GameSelector
from src.utils.filename_utils import get_safe_filename
from src.utils.logger import setup_logger
from src.utils.seo_links import apply_game_link
from src.services.image_generator import generate_article_cover, generate_article_cover_parallel
from src.services.strapi_articles import upload_article_to_strapi
from src.services.strapi_tracker import tracker as strapi_tracker, check_strapi_connection
from src.services.telegram_bot import telegram_bot

logger = setup_logger("daemon")

DAILY_LIMIT = 50
GENERATED_TOPICS_PATH = OUTPUT_DIR / "generated_topics.csv"
ARTICLES_DIR = OUTPUT_DIR / "articles"
TOPIC_CACHE_DIR = OUTPUT_DIR / "topic_cache"
STATE_PATH = OUTPUT_DIR / "daemon_state.json"
TOPIC_CACHE_TTL_DAYS = 7


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _seconds_until_next_day() -> float:
    now = datetime.now()
    next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1.0, (next_day - now).total_seconds())


def _load_games_ordered() -> list[dict]:
    """
    Load games ordered by Tier priority (Tier 1 first, then Tier 2, then Tier 3).
    Within each tier, games are ordered by ID.
    Returns list of dicts with game info and tier.
    """
    games = []
    conn = sqlite3.connect(DB_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, slug FROM games ORDER BY id ASC")
        raw_games = []
        for g_id, name, slug in cursor.fetchall():
            if name and slug:
                raw_games.append({"id": g_id, "name": name, "slug": slug})
    finally:
        conn.close()
    
    # Get tier classification using GameSelector
    try:
        from src.llm_client import LLMClient
        llm = LLMClient()
        selector = GameSelector(llm)
        game_tiers = selector.get_games_with_tiers()  # Returns {"GameName": TierInt}
        
        # Assign tiers to games
        for game in raw_games:
            tier = game_tiers.get(game["name"], 3)
            games.append({
                "id": game["id"],
                "name": game["name"],
                "slug": game["slug"],
                "tier": tier
            })
        
        # Sort by tier (1 first), then by id
        games.sort(key=lambda x: (x["tier"], x["id"]))
        
    except Exception as e:
        logger.error(f"Failed to classify games by tier: {e}. Using default order.")
        # Fallback: return games without tier info
        for game in raw_games:
            games.append({
                "id": game["id"],
                "name": game["name"],
                "slug": game["slug"],
                "tier": 3
            })
    
    return games


def _ensure_topic_cache(game_name: str, game_slug: str) -> Path:
    TOPIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = TOPIC_CACHE_DIR / f"{game_slug}.jsonl"
    if cache_path.exists():
        logger.info(f"Topic cache exists for {game_name}: {cache_path}")
        return cache_path

    logger.info(f"Building topic cache for {game_name}...")

    if not GENERATED_TOPICS_PATH.exists():
        raise FileNotFoundError(f"Topics file not found at {GENERATED_TOPICS_PATH}")

    game_lower = game_name.lower()
    try:
        with open(GENERATED_TOPICS_PATH, "r", encoding="utf-8") as src, \
             open(cache_path, "w", encoding="utf-8") as dst:
            reader = csv.reader(src)
            header = next(reader, None)
            topic_count = 0
            for row in reader:
                if len(row) < 2:
                    continue
                t_type = row[0].strip()
                t_topic = row[1].strip()
                if not t_topic:
                    continue
                if game_lower in t_topic.lower():
                    dst.write(json.dumps({"type": t_type, "topic": t_topic}, ensure_ascii=False) + "\n")
                    topic_count += 1
        logger.info(f"Created topic cache for {game_name} with {topic_count} topics")
    except Exception as e:
        logger.error(f"Failed to build topic cache for {game_name}: {e}")
    return cache_path


def _load_cached_topics(cache_path: Path) -> list[dict]:
    topics = []
    if not cache_path.exists():
        return topics
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    if isinstance(payload, dict) and payload.get("topic"):
                        topics.append(payload)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Failed to read cache {cache_path}: {e}")
    return topics


def _filter_unwritten(topics: list[dict], published_topics: set[str]) -> list[dict]:
    """
    Filter out topics that are already published to Strapi.
    Uses Strapi as source of truth instead of local files.
    """
    filtered = []
    for t in topics:
        topic_str = t.get("topic", "")
        if not topic_str:
            continue
        # Check if already published via Strapi
        if topic_str.lower().strip() in published_topics:
            continue
        filtered.append(t)
    return filtered


def _build_pending_for_game(game: dict, published_topics: set[str]) -> list[dict]:
    cache_path = _ensure_topic_cache(game["name"], game["slug"])
    topics = _load_cached_topics(cache_path)
    topics = _filter_unwritten(topics, published_topics)
    for t in topics:
        t["game_name"] = game["name"]
        t["game_slug"] = game["slug"]
    return topics


def _select_daily_batch(state: dict, games: list[dict], published_topics: set[str], limit: int) -> list[dict]:
    """
    Select a batch of topics to process.
    Prioritizes completing all topics for the current game before moving to the next.
    """
    batch = []

    while len(batch) < limit:
        pending = state.get("pending_topics", [])
        if pending:
            needed = limit - len(batch)
            batch.extend(pending[:needed])
            state["pending_topics"] = pending[needed:]
            # Don't increment game index until pending is fully exhausted
            if not state["pending_topics"]:
                state["current_game_index"] += 1
            continue

        idx = state.get("current_game_index", 0)
        if idx >= len(games):
            logger.info("All games processed. Resetting to start.")
            state["current_game_index"] = 0
            idx = 0

        game = games[idx]
        logger.info(f"Checking game {idx + 1}/{len(games)}: {game['name']} (Tier {game['tier']})")
        
        pending = _build_pending_for_game(game, published_topics)
        if not pending:
            logger.info(f"No pending topics for {game['name']}, moving to next game.")
            state["current_game_index"] += 1
            continue

        logger.info(f"Found {len(pending)} pending topics for {game['name']}")
        state["pending_topics"] = pending

    return batch


def _cleanup_topic_cache() -> None:
    if not TOPIC_CACHE_DIR.exists():
        return
    ttl_seconds = TOPIC_CACHE_TTL_DAYS * 86400
    now_ts = time.time()
    removed = 0
    for cache_file in TOPIC_CACHE_DIR.glob("*.jsonl"):
        try:
            age = now_ts - cache_file.stat().st_mtime
            if age >= ttl_seconds:
                cache_file.unlink()
                removed += 1
        except Exception as e:
            logger.error(f"Failed to remove cache file {cache_file}: {e}")
    if removed:
        logger.info(f"Cache cleanup removed {removed} files.")


async def run_daemon_mode(llm, save_covers: bool = False):
    logger.info("--- Running Phase 2: Production (Daemon) ---")

    # Step 1: Check Strapi connection (required)
    logger.info("Checking Strapi connection...")
    strapi_connected = await check_strapi_connection()
    if not strapi_connected:
        logger.error("Strapi connection failed. Daemon cannot start without Strapi. Exiting.")
        return
    logger.info("Strapi connection verified")

    # Step 2: Get existing articles from Strapi (source of truth)
    logger.info("Fetching existing articles from Strapi...")
    existing_articles = await strapi_tracker.get_all_published_articles()
    published_topics = await strapi_tracker.get_published_topics()
    published_slugs = await strapi_tracker.get_published_slugs()
    logger.info(f"Found {len(existing_articles)} existing articles in Strapi")

    # Step 3: Load games from DB
    games = _load_games_ordered()
    if not games:
        logger.error("No games found in DB. Exiting daemon mode.")
        return

    # Step 4: Load state (local, for daily reset and current position only)
    state = {
        "last_run_date": "",
        "daily_count": 0,
        "current_game_index": 0,
        "pending_topics": []
    }
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load daemon state: {e}")

    # Main daemon loop
    while True:
        today = _today_str()

        # Reset daily count at midnight
        if state.get("last_run_date") != today:
            state["last_run_date"] = today
            state["daily_count"] = 0
            _save_state(state)
            _cleanup_topic_cache()
            # Refresh published topics from Strapi once per day
            published_topics = await strapi_tracker.get_published_topics()
            published_slugs = await strapi_tracker.get_published_slugs()

        remaining = DAILY_LIMIT - int(state.get("daily_count", 0))
        if remaining <= 0:
            sleep_for = _seconds_until_next_day()
            logger.info(f"Daily limit reached. Sleeping for {int(sleep_for)}s.")
            await asyncio.sleep(sleep_for)
            continue

        # Select batch of topics to process
        batch = _select_daily_batch(state, games, published_topics, remaining)
        if not batch:
            logger.info("No available topics to write. Sleeping for 1 hour.")
            await asyncio.sleep(3600)
            continue

        for topic_data in batch:
            # Game info is now stored in topic_data from _build_pending_for_game
            game_name = topic_data.get("game_name", "Unknown")
            game_slug = topic_data.get("game_slug", "unknown")
            
            pending_count = len(state.get("pending_topics", []))
            
            logger.info(
                "STATUS | Today: %s/%s | Total in Strapi: %s | Game: %s (%s) | Pending: %s",
                state.get("daily_count", 0), DAILY_LIMIT, len(existing_articles),
                game_name, game_slug, pending_count
            )

            topic_str = topic_data.get("topic", "")
            if not topic_str:
                continue

            # Double-check topic is not already published (race condition protection)
            if topic_str.lower().strip() in published_topics:
                logger.info(f"SKIP: Topic already published to Strapi: {topic_str}")
                continue

            safe_name = get_safe_filename(topic_str)

            # Check slug in Strapi
            if safe_name in published_slugs:
                logger.info(f"SKIP: Article already in Strapi (slug: {safe_name})")
                continue

            logger.info("Initializing Fresh Graph...")
            graph_builder = GraphBuilder(llm)
            app = graph_builder.build()

            logger.info(f"Starting process for: {topic_str}")
            initial_state = {
                "topic_data": topic_data,
                "game_specs": None,
                "specs_missing": True,
                "search_queries": [],
                "search_results": [],
                "outline": None,
                "rag_chunks": []
            }

            # Start image generation in parallel with article generation
            image_task = asyncio.create_task(
                generate_article_cover_parallel(
                    llm,
                    topic_data,
                    game_specs=None,
                    safe_name=safe_name,
                    save_to_disk=True,
                )
            )
            logger.info("Image generation task started (parallel with article)")

            try:
                final_state = await app.ainvoke(initial_state)
                final_path = final_state.get("final_article_path")
                if final_path:
                    game_specs = final_state.get("game_specs")
                    if game_specs:
                        if hasattr(game_specs, "name") and hasattr(game_specs, "slug"):
                            real_game_name = game_specs.name
                            real_game_slug = game_specs.slug
                            logger.info(f"Using game specs from DB: {real_game_name} ({real_game_slug})")
                        else:
                            real_game_name = game_specs.get("name") if isinstance(game_specs, dict) else None
                            real_game_slug = game_specs.get("slug") if isinstance(game_specs, dict) else None
                            logger.warning("Game specs format unexpected, using fallback")
                    else:
                        real_game_name = topic_data.get("game_name")
                        real_game_slug = topic_data.get("game_slug")
                        logger.info(f"No game specs from DB, using topic_data: {real_game_name} ({real_game_slug})")

                    if real_game_name and real_game_slug:
                        apply_game_link(final_path, real_game_name, real_game_slug)
                    else:
                        logger.warning(f"Missing game name or slug, skipping SEO links for: {topic_str}")

                    # Wait for image generation to complete
                    logger.info("Waiting for image generation to complete...")
                    try:
                        image_ref = await image_task
                        if not image_ref:
                            logger.warning("Cover generation failed (parallel task returned empty)")
                        else:
                            logger.info(f"Image generation completed: {image_ref}")
                    except Exception as image_error:
                        logger.warning(f"Cover generation failed (parallel task exception): {image_error}")
                        image_ref = ""

                    # Prepare local image path for Strapi upload and Telegram
                    local_image_path = OUTPUT_DIR / "images" / "covers" / f"{safe_name}.webp"

                    # Upload to Strapi (image will be uploaded as file if local path exists)
                    upload_success = await upload_article_to_strapi(
                        final_path,
                        topic_str,
                        image_path=str(local_image_path) if local_image_path.exists() else image_ref
                    )

                    if upload_success:
                        # Add to published set immediately
                        published_topics.add(topic_str.lower().strip())
                        published_slugs.add(safe_name)
                        existing_articles.append({
                            "slug": safe_name,
                            "topic": topic_str,
                            "created_at": datetime.now().isoformat()
                        })

                    # Update daily count (local state only, for rate limiting)
                    state["daily_count"] = int(state.get("daily_count", 0)) + 1
                    _save_state(state)
                    logger.info(f"SUCCESS | Saved to: {final_path} | Strapi: {'✓' if upload_success else '✗'}")

                    # Telegram Notification
                    try:
                        # 1. Send Cover + Status
                        caption = f"✅ Success: {topic_str}\n"
                        caption += f"Strapi: {'Published 🚀' if upload_success else 'Not uploaded ❌'}\n"

                        if local_image_path.exists():
                            await telegram_bot.send_photo(str(local_image_path), caption=caption)
                        else:
                            logger.warning(f"Local image not found at {local_image_path}, sending text.")
                            await telegram_bot.send_message(caption + f"\nImage URL: {image_ref}")

                        # 2. Send Markdown File
                        final_path_obj = Path(final_path) if final_path else None
                        if final_path_obj and final_path_obj.exists():
                            await telegram_bot.send_document(str(final_path_obj), caption=f"📄 {final_path_obj.name}")

                    except Exception as e:
                        logger.error(f"Failed to send Telegram notification: {e}")
                elif final_state.get("rag_chunks"):
                    logger.warning("PARTIAL | RAG indexed but compiler failed.")
                    if not image_task.done():
                        image_task.cancel()
                elif final_state.get("outline"):
                    logger.warning("PARTIAL | Outline created but no final file.")
                    if not image_task.done():
                        image_task.cancel()
                else:
                    logger.error("FAILED | Stopped early.")
                    if 'image_task' in locals() and not image_task.done():
                        image_task.cancel()
            except Exception as e:
                logger.error(f"EXCEPTION: {e}")
                if 'image_task' in locals() and not image_task.done():
                    image_task.cancel()
                if isinstance(e, RuntimeError) and "LLM failed 10 requests in a row" in str(e):
                    logger.error("Stopping daemon due to consecutive LLM failures.")
                    return

            del app
            del graph_builder


def _save_state(state: dict) -> None:
    """Save minimal daemon state (daily count and current position only)."""
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save daemon state: {e}")
