
import json
import re
from ..config import SEGMENTS_FILE, PAINS_FILE, MODIFIERS_FILE, EXPANDED_KEYWORDS_FILE
from ..llm_client import LLMClient

class KeywordExpander:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def _read_list(self, filepath):
        with open(filepath, 'r') as f:
            content = f.read()
        return [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]

    def _clean_list_items(self, items):
        """
        Sanitization Layer:
        - Fixes encoding smart quotes
        - Removes banned terms (investors, roi, etc)
        - Fixes mixed logic (esports + crazy time/roulette)
        - Removes Cyrillic
        """
        cleaned = []
        
        blacklist = [
            # User specified
            "investor", "return on investment", "roi", "disputs", "disputes",
            # Legacy/Safety
            "penny pinchers", "serious investors", "skilled operators", 
            "daring adventurers", "budget conscious", "risk-seeking",
            "here is", "sure,", "certainly", "in this list",
            # New garbage filter
            "here's", "seeker-pro", "enthusiast", "extraordinaire",
            "addict", "obsessive", "hoarder", "cashier", "slinger",
            "term one", "frustrating loss"
        ]
        
        seen = set()
        
        for item in items:
            s = item.replace("\u2019", "'").replace("’", "'").replace("“", '"').replace("”", '"')
            s = s.strip()
            
            if not s:
                continue

            if s.count('-') > 2:
                continue
            
            if re.search(r'[а-яА-Я]', s):
                continue

            s_lower = s.lower()
            
            if any(bad in s_lower for bad in blacklist):
                continue
                
            if "esports" in s_lower and ("crazy time" in s_lower or "roulette" in s_lower):
                continue
            
            if len(s) < 3:
                continue

            if s not in seen:
                cleaned.append(s)
                seen.add(s)
                
        return cleaned

    def _expand_list(self, items, category):
        extra_constraint = ""
        cat_lower = category.lower()
        if "segment" in cat_lower or "pain" in cat_lower:
             extra_constraint = "Note: Exclude financial roles like investors or traders."

        prompt = f"""
        I have a list of {category}: {', '.join(items[:12])}...
        
        Task: Provide 10 more similar, natural English terms.
        
        Rules:
        - Output ONLY a comma-separated list.
        - Short, simple phrases (1-4 words).
        - No weird adjectives (extraordinaire, obsessive).
        - No hyphens.
        {extra_constraint}
        """
        response = self.llm.generate(prompt)
        
        new_items = [item.strip() for item in response.split(',') if item.strip()]
        
        parsed_new_items = []
        for item in new_items:
             s = re.sub(r'^\d+\.\s*', '', item)
             s = s.rstrip('.,;:')
             parsed_new_items.append(s)
             
        full_list = items + parsed_new_items
        
        return self._clean_list_items(full_list)

    def _generate_generic_seeds(self):
        print("Generating new Generic Seeds via LLM...")
        prompt = """
        Generate 100 generic commercial gambling keywords.
        Examples: online slots, blackjack sites, poker app, crypto casino, best betting sites.
        
        Rules:
        - Commercial intent keywords (what players actually search).
        - Short and concise (2-5 words).
        - Comma-separated list ONLY.
        - No numbering.
        """
        response = self.llm.generate(prompt, temperature=0.7)
        
        response = response.replace('\n', ',')
        seeds = [item.strip() for item in response.split(',') if item.strip()]
        
        pre_cleaned = [re.sub(r'^[\d\-\.\)]+\s*', '', s).strip('.,;:') for s in seeds]
        
        return self._clean_list_items(pre_cleaned)

    def run(self):
        print("--- Step 1: Expanding Keywords (Refactored) ---")
        
        if EXPANDED_KEYWORDS_FILE.exists():
            print(f"File {EXPANDED_KEYWORDS_FILE} already exists. Skipping expansion.")
            return
        
        segments = self._read_list(SEGMENTS_FILE)
        pains = self._read_list(PAINS_FILE)
        modifiers = self._read_list(MODIFIERS_FILE)

        print(f"Original Segments: {len(segments)}")
        print(f"Original Pains: {len(pains)}")
        print(f"Original Modifiers: {len(modifiers)}")

        data = {
            "segments": self._expand_list(segments, "player segments (who play casino games)"),
            "pains": self._expand_list(pains, "player pains/problems in online casinos"),
            "modifiers": self._expand_list(modifiers, "search modifiers/solutions for casino games"),
            "generic_seeds": self._generate_generic_seeds()
        }

        with open(EXPANDED_KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Keywords expanded and saved to {EXPANDED_KEYWORDS_FILE}")
