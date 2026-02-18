import argparse
import sys
import os
import traceback
import csv
import random
import asyncio
from src.llm_client import LLMClient
from src.config import OUTPUT_DIR
from src.utils.logger import setup_logger
from src.utils.filename_utils import get_safe_filename
from src.production.daemon import run_daemon_mode

# Planning Modules
from src.planning.keyword_expander import KeywordExpander
from src.planning.logic_mapper import LogicMapper
from src.planning.topic_generator import TopicGenerator

from src.production.graph import GraphBuilder

logger = setup_logger("main")

GENERATED_TOPICS_PATH = OUTPUT_DIR / "generated_topics.csv"
ARTICLES_DIR = OUTPUT_DIR / "articles"

def run_planning_phase(llm):
    logger.info("--- Running Phase 1: Planning ---")
    # 1. Expand Keywords
    expander = KeywordExpander(llm)
    expander.run()
    
    # 2. Map Logic
    mapper = LogicMapper(llm)
    mapper.run()
    
    # 3. Generate Topics
    generator = TopicGenerator(llm_client=llm)
    generator.run()

async def run_production_phase(llm, limit):
    logger.info("--- Running Phase 2: Production ---")
    logger.info(f"Goal: Write {limit} articles.")

    # Modified to read from generated_topics.csv randomly avoiding duplicates
    GENERATED_TOPICS_PATH = OUTPUT_DIR / "generated_topics.csv"
    ARTICLES_DIR = OUTPUT_DIR / "articles"
    
    if not GENERATED_TOPICS_PATH.exists():
        logger.error(f"Topics file not found at {GENERATED_TOPICS_PATH}. Run planning phase first.")
        # Fallback to old behavior or return? simpler to return if no file
        return

    # Read all topics
    all_topics = []
    try:
        with open(GENERATED_TOPICS_PATH, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            # Check header
            header = next(reader, None)
            
            for row in reader:
                if len(row) >= 2:
                    # Assuming format: Type, Topic
                    t_type = row[0].strip()
                    t_topic = row[1].strip()
                    if t_topic: # ensure not empty
                        all_topics.append({"type": t_type, "topic": t_topic})
    except Exception as e:
        logger.error(f"Error reading topics csv: {e}")
        return

    # Filter existing articles
    available_topics = []
    if not ARTICLES_DIR.exists():
        os.makedirs(ARTICLES_DIR, exist_ok=True)

    for t in all_topics:
        safe_name = get_safe_filename(t["topic"])
        md_path = ARTICLES_DIR / f"{safe_name}.md"
        if not md_path.exists():
            available_topics.append(t)
            
    logger.info(f"Found {len(all_topics)} total topics. {len(available_topics)} are available (not written yet).")
    
    if not available_topics:
        logger.info("No new topics to write.")
        return

    # Random selection
    if len(available_topics) > limit:
        current_topics = random.sample(available_topics, limit)
    else:
        current_topics = available_topics
        logger.info(f"Requested {limit}, but only {len(current_topics)} available.")
    
    for i, topic_data in enumerate(current_topics):
        # --- ISOLATION FIX: Initialize Graph PER ARTICLE to ensure 100% clean state ---
        logger.info(f"[Article {i+1}/{limit}] Initializing Fresh Graph...")
        graph_builder = GraphBuilder(llm)
        app = graph_builder.build()
        # ------------------------------------------------------------------------------

        if isinstance(topic_data, dict):
            topic_str = topic_data.get("topic", "")
        else:
            topic_str = str(topic_data)
            topic_data = {"topic": topic_str, "type": "generic"}

        safe_name = get_safe_filename(topic_str)
        existing_path = OUTPUT_DIR / "articles" / f"{safe_name}.md"
        
        if existing_path.exists():
            logger.info(f"[Article {i+1}/{limit}] SKIP: File already exists at {existing_path}")
            continue

        logger.info(f"[Article {i+1}/{limit}] Starting process for: {topic_str}")

        initial_state = {
            "topic_data": topic_data,
            "game_specs": None,
            "specs_missing": True,
            "search_queries": [],
            "search_results": [],
            "outline": None,
            "rag_chunks": []
        }
        
        try:
            final_state = await app.ainvoke(initial_state)
            
            final_path = final_state.get('final_article_path')
            if final_path:
                 logger.info(f"[Article {i+1}] SUCCESS | Saved to: {final_path}")
            elif final_state.get('rag_chunks'):
                 logger.warning(f"[Article {i+1}] PARTIAL | RAG indexed but compiler failed.")
            elif final_state.get('outline'):
                logger.warning(f"[Article {i+1}] PARTIAL | Outline created but no final file.")
            else:
                 logger.error(f"[Article {i+1}] FAILED | Stopped early.")

        except Exception as e:
            logger.error(f"[Article {i+1}] EXCEPTION: {e}")
            traceback.print_exc()

        # Explicitly clean up to free resources immediately
        del app
        del graph_builder

def main():
    parser = argparse.ArgumentParser(description="Programmatic SEO Pipeline")
    parser.add_argument("--mode", choices=["planning", "production", "daemon"], default="daemon", help="Pipeline phase to run")
    parser.add_argument("--limit", type=int, default=10, help="Number of articles to generate in production mode")
    parser.add_argument("--save-covers", action="store_true", help="Save generated covers to disk")
    
    args = parser.parse_args()

    logger.info("==========================================")
    logger.info(f"Starting Pipeline | Mode: {args.mode.upper()}")
    logger.info("==========================================")
    
    try:
        # Init Shared Resources
        llm = LLMClient()
        
        if args.mode == "planning":
            run_planning_phase(llm)
        elif args.mode == "production":
            asyncio.run(run_production_phase(llm, args.limit))
        elif args.mode == "daemon":
            asyncio.run(run_daemon_mode(llm, save_covers=args.save_covers))
        
        logger.info("==========================================")
        logger.info("Pipeline Finished Successfully.")
        logger.info("==========================================")

    except Exception as e:
        logger.critical(f"Pipeline Failed: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
