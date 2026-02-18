import sqlite3
import logging # Still import logging for module level variable if needed, but lets use ours
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from src.config import DB_DIR
from src.utils.logger import setup_logger

logger = setup_logger("db_check")

class GameSpecs(BaseModel):
    game_id: int = Field(..., alias="id")
    name: str
    slug: Optional[str] = None
    provider: Optional[str] = None
    rtp: Optional[str] = None
    type: Optional[str] = None
    themes: Optional[str] = None
    min_bet: Optional[str] = None
    max_bet: Optional[str] = None
    max_win: Optional[str] = Field(None, alias="max_win_per_spin")
    autoplay: Optional[str] = None
    # Add other fields as needed
    
    class Config:
        populate_by_name = True

class LocalDBCheck:
    def __init__(self, db_path: str = None):
        if db_path is None:
            self.db_path = DB_DIR / "slotslaunch.db"
        else:
            self.db_path = db_path
            
    def get_connection(self):
        return sqlite3.connect(self.db_path)
        
    def find_game_in_topic(self, topic: str) -> Optional[GameSpecs]:
        """
        Attempts to find a game mentioned in the topic by checking against the local DB.
        Strategy: Fetch all game names and find longest substring match.
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Fetch all names. optimizing could be FTS or similar but for 30k rows strict scan is usually ok for offline tasks
            # If performance is issues, we can optimize.
            cursor.execute("SELECT id, name FROM games")
            all_games = cursor.fetchall()
            
            # Simple heuristic: Longest matching name in topic
            # Case insensitive match
            topic_lower = topic.lower()
            
            best_match = None
            max_len = 0
            
            for g_id, g_name in all_games:
                if g_name.lower() in topic_lower:
                    if len(g_name) > max_len:
                        best_match = (g_id, g_name)
                        max_len = len(g_name)
            
            if best_match:
                g_id = best_match[0]
                logger.debug(f"Found game match: {best_match[1]} (ID: {g_id}) for topic: {topic}")
                return self.get_game_specs(g_id)
            else:
                logger.debug(f"No game match found for topic: {topic}")
                return None
                
        except Exception as e:
            logger.error(f"Error checking local DB: {e}")
            return None
        finally:
            conn.close()

    def get_game_specs(self, game_id: int) -> GameSpecs:
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
            row = cursor.fetchone()
            if row:
                # Convert row to dict
                data = dict(row)
                # Helper cleanup or parsing can happen here
                return GameSpecs(**data)
            return None
        finally:
            conn.close()
