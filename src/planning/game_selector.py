
import sqlite3
import json
import re
import math
from ..config import DB_FILE, OUTPUT_DIR
from ..llm_client import LLMClient

class GameSelector:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.conn = None

    def _get_conn(self):
        if not self.conn:
            self.conn = sqlite3.connect(DB_FILE)
            self.conn.create_function("RTP_VAL", 1, self._rtp_to_float)
        return self.conn

    def _rtp_to_float(self, rtp_str):
        if not rtp_str: return 0.0
        try:
            cleaned = re.sub(r'[^\d\.]', '', str(rtp_str))
            val = float(cleaned)
            if 0 <= val <= 100:
                return val
            return 0.0
        except:
            return 0.0

    def _fetch_providers_stats(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT provider, COUNT(*) as c 
            FROM games 
            WHERE provider IS NOT NULL AND provider != '' 
            GROUP BY provider 
            ORDER BY c DESC
        """)
        return cursor.fetchall()

    def _classify_providers_with_llm(self, provider_names):
        all_names = provider_names
        BATCH_SIZE = 120 
        
        batches = [all_names[i:i + BATCH_SIZE] for i in range(0, len(all_names), BATCH_SIZE)]
        full_mapping = {}
        
        print(f"Classifying {len(all_names)} providers in {len(batches)} batches via LLM...")
        
        for i, batch in enumerate(batches):
            print(f"  Processing Batch {i+1}/{len(batches)} ({len(batch)} providers)...")
            
            prompt = f"""
            Act as an iGaming Industry Expert.
            Classify these Casino Game Providers into 3 Tiers based on GLOBAL POPULARITY and REPUTATION.
            
            Providers: {', '.join(batch)}

            Return ONLY a raw JSON object: {{"ProviderName": TierNumber}}.
            
            Tier 1: Absolute Market Leaders (e.g. Pragmatic, Evolution, NetEnt, Play'n GO, Games Global, IGT, Amusnet).
            Tier 2: Strong Popular Studios (e.g. Nolimit, Push Gaming, Spinomenal, Playson, Betsoft, Spribe, BGaming).
            Tier 3: Classic, Niche, Small or Unknown Studios.

            JSON ONLY. No markdown.
            """
            
            try:
                response = self.llm.generate(prompt, temperature=0.1)
                
                clean_resp = response.replace('```json', '').replace('```', '').strip()
                batch_map = {}
                
                match = re.search(r'\{.*\}', clean_resp, re.DOTALL)
                if match:
                    batch_map = json.loads(match.group(0))
                elif clean_resp.startswith('{'):
                    batch_map = json.loads(clean_resp)
                
                for k, v in batch_map.items():
                    try:
                        val = 3
                        if isinstance(v, int):
                            val = v
                        elif isinstance(v, str):
                            digits = re.findall(r'\d+', v)
                            if digits: val = int(digits[0])
                        
                        if val in [1, 2, 3]:
                            full_mapping[k] = val
                        else:
                            full_mapping[k] = 3
                    except:
                        pass
                        
            except Exception as e:
                print(f"  Error in Batch {i+1}: {e}")
                
        return full_mapping

    def get_games_with_tiers(self):
        print("Fetching and classifying usage of ALL games...")
        
        providers_stats = self._fetch_providers_stats() # [(name, count), ...]
        all_db_providers = [p[0] for p in providers_stats]
        
        # CONFIG/CACHE LOGIC: User-Editable Tier Configuration
        # We use a user-editable JSON file as the source of truth.
        # If providers are missing from this file, we ask LLM to classify them and APPEND to the file.
        config_file = OUTPUT_DIR / "provider_tiers.json"
        
        tiers_map = {}
        
        # 1. Load existing config if available
        if config_file.exists():
            print(f"Loading provider tiers from config: {config_file}")
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    tiers_map = json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}. Starting fresh.")
                tiers_map = {}

        # 2. Identify missing providers
        existing_keys = set(tiers_map.keys())
        missing_providers = [p for p in all_db_providers if p not in existing_keys]
        
        if missing_providers:
            print(f"Found {len(missing_providers)} providers not in config. Classifying them...")
            new_classifications = self._classify_providers_with_llm(missing_providers)
            
            # Merge new results into map
            tiers_map.update(new_classifications)
            
            # Ensure ANY provider that failed LLM classification gets a default Tier 3 entry
            # so we don't re-run it next time.
            for p in missing_providers:
                if p not in tiers_map:
                    tiers_map[p] = 3
            
            # 3. Save updated map back to file (User can now edit this file!)
            print(f"Updating config file with new classifications: {config_file}")
            with open(config_file, 'w', encoding='utf-8') as f:
                # Sort keys for easier user editing
                sorted_map = dict(sorted(tiers_map.items()))
                json.dump(sorted_map, f, indent=2, ensure_ascii=False)
        else:
            print("All providers already classified in config.")
        
        # 4. Use the map to build final classifications
        final_provider_tiers = {}
        for name, count in providers_stats:
            # Direct lookup (we know it's there because we just filled gaps)
            final_provider_tiers[name] = tiers_map.get(name, 3)
        
        print("Detailed Provider Tiers (First 10):")
        for p, c in providers_stats[:10]:
             print(f"  {p}: Tier {final_provider_tiers.get(p)}")

        # 3. Fetch All Games and assign Tiers
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT name, provider FROM games WHERE provider IS NOT NULL AND provider != ''")
        all_games = cursor.fetchall()
        
        game_library = {}
        for game_name, provider in all_games:
            p_tier = final_provider_tiers.get(provider, 3)
            game_library[game_name] = p_tier
            
        print(f"Classified {len(game_library)} games.")
        
        # Stats
        tier_counts = {1: 0, 2: 0, 3: 0}
        for t in game_library.values():
            tier_counts[t] = tier_counts.get(t, 0) + 1
            
        print(f"Tier Breakdown: {tier_counts}")
        return game_library

    # Legacy method kept for compatibility if needed, but we prefer get_games_with_tiers
    def select_games(self, total_limit=2000):
        print("Warning: select_games is deprecated. Use get_games_with_tiers instead.")
        return []
