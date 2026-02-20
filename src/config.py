import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM Config (Loaded from .env)
    LLM_API_URL: str = "http://localhost:11434"
    LLM_API_KEY: str = "" # Added for external providers
    LLM_MODEL_FAST: str = "llama3.2:latest"
    LLM_MODEL_QUALITY: str = "qwen2.5-coder:32b"
    LLM_DELAY: float = 1.0 # Delay between requests in seconds

    # Search Config
    SEARCHXNG_HOST: str = "" # Default empty, should be set in env
    JINA_API_KEY: str = ""   # Added for Jina Reader

    # RAG Config
    LLM_EMBEDDING_MODEL: str = "nomic-embed-text" 

    # Strapi Config
    STRAPI_API_URL: str = "https://strapi.safercase.app/api/games"
    STRAPI_ARTICLES_API_URL: str = "http://localhost:1337/api/blog-posts"
    STRAPI_API_TOKEN: str = ""
    SLOTS_LAUNCH_TOKEN: str = ""

    # Image Generation Config
    IMAGE_API_URL: str = "http://localhost"
    # IMAGE_API_KEY is now shared with LLM_API_KEY
    IMAGE_MODEL: str = "exolabs/FLUX.1-dev-8bit"
    IMAGE_POLL_INTERVAL: float = 10.0
    IMAGE_MAX_WAIT: float = 1500

    # Text Generation Polling Config (for async LLM APIs)
    TEXT_POLL_INTERVAL: float = 1.0
    TEXT_MAX_WAIT: float = 300

    # Telegram Config
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Langfuse Config
    LANGFUSE_SECRET_KEY: str = ""

    # Langfuse Config
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com" # often mapped from LANGFUSE_BASE_URL in .env

    DEBUG: bool = False # Debug mode to skip cleanup and reuse data
    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = "ignore"

settings = Settings()

# Base Paths (Static, no need for .env usually)
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
SOURCE_DIR = DATA_DIR / "source"
DB_DIR = DATA_DIR / "db"
OUTPUT_DIR = DATA_DIR / "output"

# Files
DB_FILE = DB_DIR / "slotslaunch.db"
EXPANDED_KEYWORDS_FILE = OUTPUT_DIR / "expanded_keywords.json"
LOGIC_MAP_FILE = OUTPUT_DIR / "segment_modifier_map.json"
GENERATED_TOPICS_FILE = OUTPUT_DIR / "generated_topics.csv"

# Source Files
SEGMENTS_FILE = SOURCE_DIR / "Core_player_segments.md"
PAINS_FILE = SOURCE_DIR / "PLAYER_PAINS.md"
MODIFIERS_FILE = SOURCE_DIR / "PAIN-DRIVEN-MODIFIER-LISTS.md"

# Easy Access Constants
LLM_API_URL = settings.LLM_API_URL
LLM_API_KEY = settings.LLM_API_KEY
LLM_MODEL_FAST = settings.LLM_MODEL_FAST
LLM_MODEL_QUALITY = settings.LLM_MODEL_QUALITY
LLM_DELAY = settings.LLM_DELAY
LLM_EMBEDDING_MODEL = settings.LLM_EMBEDDING_MODEL
SEARCHXNG_HOST = settings.SEARCHXNG_HOST

IMAGE_API_URL = settings.IMAGE_API_URL
IMAGE_API_KEY = settings.LLM_API_KEY
IMAGE_MODEL = settings.IMAGE_MODEL
IMAGE_POLL_INTERVAL = settings.IMAGE_POLL_INTERVAL
IMAGE_MAX_WAIT = settings.IMAGE_MAX_WAIT

TEXT_POLL_INTERVAL = settings.TEXT_POLL_INTERVAL
TEXT_MAX_WAIT = settings.TEXT_MAX_WAIT

# Default for legacy code (planning phase uses fast model)
LLM_MODEL = settings.LLM_MODEL_FAST
