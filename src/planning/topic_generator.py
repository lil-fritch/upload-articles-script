
import sqlite3
import json
import csv
import random
from ..config import LOGIC_MAP_FILE, DB_FILE, GENERATED_TOPICS_FILE, EXPANDED_KEYWORDS_FILE, OUTPUT_DIR
from .game_selector import GameSelector
from ..llm_client import LLMClient

class TopicGenerator:
    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client
        self.generic_seeds = []
        
        self.templates = {
            "standard": [
                 "{modifier} {seed} for {segment}",
                 "best {modifier} {seed} for {segment}",
                 "top {modifier} {seed} for {segment}",
                 "{seed} with {modifier} for {segment}",
            ],
            "feature_focus": [
                "{modifier} {seed} for {segment}",
                "best {seed} with {modifier} for {segment}",
            ],
            "financial_focus": [
                "{modifier} {seed} for {segment}",
                "{seed} with {modifier} for {segment}",
                "best {modifier} {seed} sites for {segment}"
            ],
            "strategy_focus": [
                "{modifier} {seed} strategy for {segment}",
                "{modifier} {seed} tips for {segment}",
                "how to win at {seed} for {segment} ({modifier})" 
            ]
        }
        
        # Compatibility Matrix: Seed Category -> Allowed Modifier Categories
        self.compatibility = {
            "GAME": ["FEATURE", "GAMEPLAY", "TRUST", "BONUS"],    
            "PLATFORM": ["FINANCIAL", "TRUST", "BONUS", "FEATURE"], 
            "BONUS": ["FINANCIAL", "TRUST", "GAME", "PLATFORM"],                 
            "INFO": ["GAMEPLAY", "GAME"]                          
        }

    def _get_games(self, limit=5000):
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='games';")
            if not cursor.fetchone():
                return []
            
            cursor.execute(f"SELECT name FROM games ORDER BY RANDOM() LIMIT {limit}")
            games = [row[0] for row in cursor.fetchall()]
            conn.close()
            return games
        except Exception as e:
            print(f"DB Error: {e}")
            return []

    def _get_modifiers_for_segment(self, segment, segment_map, universal_mods):
        specifics = segment_map.get(segment, [])
        return list(set(specifics + universal_mods))

    def _get_category(self, term, classification_map, default="INFO"):
        if not classification_map:
            return default
        return classification_map.get(term, default)
    
    def _is_compatible(self, seed_cat, mod_cat):
        allowed = self.compatibility.get(seed_cat, [])
        if not allowed:
             return True
        return mod_cat in allowed

    def _select_template(self, seed, modifier, seed_cat, mod_cat):
        if seed_cat == "GAME" or mod_cat == "FEATURE":
             return random.choice(self.templates["feature_focus"] + self.templates["standard"])
        elif mod_cat == "FINANCIAL":
             return random.choice(self.templates["financial_focus"])
        elif seed_cat == "STRATEGY" or mod_cat == "GAMEPLAY":
             return random.choice(self.templates["strategy_focus"])
        return random.choice(self.templates["standard"])

    def run(self):
        print("--- Step 3: Generating Topics (Optimized) ---")
        if not LOGIC_MAP_FILE.exists():
             raise FileNotFoundError(f"Logic map missing at {LOGIC_MAP_FILE}. Run logic mapper first.")

        # Ensure seeds are loaded
        if hasattr(self, 'generic_seeds') and not self.generic_seeds:
             if EXPANDED_KEYWORDS_FILE.exists():
                 with open(EXPANDED_KEYWORDS_FILE, 'r') as f:
                     dk = json.load(f)
                     self.generic_seeds = dk.get('generic_seeds', [])
                     print(f"Loaded {len(self.generic_seeds)} Generic Seeds.")
        
        # Load Logic Map
        with open(LOGIC_MAP_FILE, 'r') as f:
            data = json.load(f)

        universal_mods = data.get('universal_modifiers', [])
        if not universal_mods:
             universal_mods = data.get('all_modifiers', [])
             
        segment_map = data.get('segment_map', {})
        all_segments = data.get('all_segments', [])
        
        classification = data.get('classification', {})
        seed_classes = classification.get('seed_class', {})
        mod_classes = classification.get('modifier_class', {})
        
        default_seed_cat = "GAME"
        default_mod_cat = "FEATURE"

        
        print(f"Connecting to database at {DB_FILE}...")
        
        selector = GameSelector(self.llm)
        game_library = selector.get_games_with_tiers() # Returns { "GameName": TierInt }
        
        print(f"Loaded {len(game_library)} classified games from DB")
        
        all_topics = []
        
        print("Generating topics...")
        
        seen_topics = set()
         
        print("Processing Generic Seeds...")
        for seg in all_segments:
            specifics = segment_map.get(seg, [])
            valid_mods = list(set(specifics + universal_mods))
            
            for mod in valid_mods:
                mod_cat = self._get_category(mod, mod_classes, default=default_mod_cat)
                
                for seed in self.generic_seeds:
                    seed_cat = self._get_category(seed, seed_classes, default=default_seed_cat)
                    if self._is_compatible(seed_cat, mod_cat):
                         template = self._select_template(seed, mod, seed_cat, mod_cat)
                    else:
                         template = random.choice(self.templates["standard"])

                    topic = template.format(segment=seg, modifier=mod, seed=seed)
                    topic = self._clean_topic(topic)
                    
                    if topic not in seen_topics:
                        all_topics.append(["generic", topic])
                        seen_topics.add(topic)

        print(f"Generated {len(all_topics)} generic topics. Now processing {len(game_library)} games...")

       
        next_log_threshold = 50000
        for game, tier in game_library.items():
            seed_cat = "GAME"

            if tier == 3:
                # Tier 3: Generate basic topics but still thematic
                # Focus on core intents: review, demo, play, bonus
                BASIC_SEGMENTS = ["beginners", "new players", "casual players"]
                CORE_INTENT = ["review", "demo", "play", "bonus", "casino"]
                
                for seg in BASIC_SEGMENTS:
                    specifics = segment_map.get(seg, [])
                    full_mods = list(set(specifics + universal_mods))
                    # Filter to core intents only
                    active_mods = [m for m in full_mods if any(k in m.lower() for k in CORE_INTENT)]
                    
                    for mod in active_mods[:10]:  # Limit modifiers to avoid explosion
                        mod_cat = self._get_category(mod, mod_classes, default=default_mod_cat)
                        
                        if self._is_compatible(seed_cat, mod_cat):
                            template = self._select_template(game, mod, seed_cat, mod_cat)
                        else:
                            template = random.choice(self.templates["standard"])
                        
                        topic = template.format(segment=seg, modifier=mod, seed=game)
                        topic = self._clean_topic(topic)
                        
                        if topic not in seen_topics:
                            all_topics.append(["game_specific", topic])
                            seen_topics.add(topic)
                
                # Also add the basic review topic
                topic = f"{game} Review & Demo Play"
                if topic not in seen_topics:
                    all_topics.append(["game_specific", topic])
                    seen_topics.add(topic)
                continue

            selected_segments = []
            if tier == 1:
                PRIORITY_SEGMENTS = [
                    "beginners", "high rollers", "experienced players", "mobile players",
                    "bonus hunters", "crypto players", "new players", "professional players",
                    "low budget players", "casual players"
                ]
                selected_segments = [s for s in all_segments if s in PRIORITY_SEGMENTS]
                if not selected_segments:
                    selected_segments = all_segments[:10]

            elif tier == 2:
                TIER2_SEGMENTS = ["beginners", "high rollers", "mobile players", "bonus hunters"]
                selected_segments = [s for s in all_segments if s in TIER2_SEGMENTS]
                if not selected_segments:
                     selected_segments = all_segments[:4]
            else:
                selected_segments = []

            for seg in selected_segments:
                specifics = segment_map.get(seg, [])
                full_mods = list(set(specifics + universal_mods))
                
                if tier == 1:
                    active_mods = full_mods # All modifiers (~50-100 topics)
                elif tier == 2:
                    CORE_INTENT = ["review", "demo", "play", "bonus", "casino"]
                    active_mods = [m for m in full_mods if any(k in m.lower() for k in CORE_INTENT)]
                else: 
                    active_mods = []

                for mod in active_mods:
                    mod_cat = self._get_category(mod, mod_classes, default=default_mod_cat)
                    
                    if self._is_compatible(seed_cat, mod_cat):
                         template = self._select_template(game, mod, seed_cat, mod_cat)
                    else:
                         template = random.choice(self.templates["standard"])

                    topic = template.format(segment=seg, modifier=mod, seed=game)
                    topic = self._clean_topic(topic)
                    
                    if topic not in seen_topics:
                        all_topics.append(["game_specific", topic])
                        seen_topics.add(topic)
                        
            if len(all_topics) >= next_log_threshold:
                print(f"  ...generated {len(all_topics)} topics so far...")
                next_log_threshold += 50000

        print(f"Generated {len(all_topics)} topics total.")

        with open(GENERATED_TOPICS_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Type", "Topic"])
            writer.writerows(all_topics)
        
        print(f"Total topics generated: {len(all_topics)}")
        print(f"Saved to {GENERATED_TOPICS_FILE}")

    def _clean_topic(self, topic):
        topic = topic.replace("..", ".").replace("  ", " ").strip()
        topic = topic.replace(" :", ":")
        return topic.replace("best best", "best").replace("top best", "top").replace("best top", "best")
