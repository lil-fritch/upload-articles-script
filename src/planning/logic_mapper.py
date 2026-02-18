
import json
import re
from ..config import EXPANDED_KEYWORDS_FILE, LOGIC_MAP_FILE
from ..llm_client import LLMClient

class LogicMapper:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def run(self):
        print("--- Step 2: Mapping Logic (Simplified) ---")
        
        if LOGIC_MAP_FILE.exists():
            print(f"File {LOGIC_MAP_FILE} already exists. Skipping mapping.")
            return

        if not EXPANDED_KEYWORDS_FILE.exists():
            raise FileNotFoundError("Expanded keywords file missing. Run expansion first.")
        
      
        with open(EXPANDED_KEYWORDS_FILE, 'r') as f:
            data = json.load(f)
        
        segments = data.get('segments', [])
        modifiers = data.get('modifiers', [])
        seeds = data.get('generic_seeds', [])

        print(f"Loaded {len(segments)} segments, {len(modifiers)} modifiers, {len(seeds)} seeds.")
        print("Skipping complex LLM mapping to maximize speed and volume.")

        final_data = {
            "universal_modifiers": modifiers, # VALID FOR ALL
            "all_segments": segments,
            "all_modifiers": modifiers
        }

        with open(LOGIC_MAP_FILE, 'w') as f:
            json.dump(final_data, f, indent=2)
        print(f"Logic map saved to {LOGIC_MAP_FILE} (Ready for generation)")
