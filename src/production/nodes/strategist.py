from typing import List, TypedDict, Dict, Any, Optional
import json
from src.llm_client import LLMClient
from src.production.nodes.fact_validator import ArticlePassport
from src.utils.logger import setup_logger

logger = setup_logger("strategist")

class ArticleSection(TypedDict):
    id: int
    title: str          # Заголовок H2
    user_intent: str    # Какую боль закрываем
    key_points: List[str] # О чем писать (тезисы)
    rag_query: str      # Что искать в Vector Store для этой секции (опционально)

class ArticleOutline(TypedDict):
    main_title: str     # Кликбейтный H1
    seo_slug: str       # URL
    sections: List[ArticleSection]

class StrategistNode:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def _clean_json_string(self, text: str) -> str:
        """
        Robustly extracts JSON object from text.
        """
        text = text.strip()
        # Remove markdown code blocks
        if "```" in text:
            # Find the first code block
            parts = text.split("```")
            for part in parts:
                if "{" in part and "}" in part:
                    text = part
                    if text.startswith("json"):
                         text = text[4:]
                    break
        
        # Find outer braces
        start = text.find("{")
        end = text.rfind("}")
        
        if start != -1 and end != -1:
            text = text[start:end+1]
            
        return text

    async def run(self, topic: str, game_specs: Optional[Dict], search_results: List[Dict], passport: Optional[ArticlePassport] = None) -> ArticleOutline:
        
        # Prepare search summary
        # Safely handle missing title/desc keys
        search_summary = "\n".join([
            f"- {res.get('title', 'No Title')}: {res.get('description', 'No Description')}" 
            for res in search_results
        ])

        # Prepare specs string
        specs_str = json.dumps(game_specs, indent=2) if game_specs else "No specific game data found in DB."

        # Prepare Passport Strategy Info
        strategy_info = ""
        if passport:
            decision = passport.get("decision", {})
            facts = passport.get("facts", {})
            strategy_info = f"""
--- PIVOT STRATEGY INSTRUCTIONS (MUST FOLLOW) ---
MATCH STATUS: {decision.get('match_status')}
STRATEGY: {decision.get('selected_writing_strategy')}
REASON: {decision.get('pivot_reason')}

VERIFIED FACTS (Use these, ignore hallucinations):
{json.dumps(facts, indent=2)}

STRATEGY GUIDELINES:
- IF DIRECT_REVIEW: Standard extensive review.
- IF MYTH_BUSTER: Debunk the myth with a compelling, unique title. Vary your title structure — use questions ("Does [Topic] Really Exist?"), benefit-driven angles ("The Real Way to..."), or direct statements ("Why [Topic] Doesn't Work"). Never use the same title pattern twice.
- IF GENRE_OVERVIEW: Do NOT review a single game. Review the category/provider.
- IF STRATEGY_GUIDE: Focus on "How to Play/Win" rather than specs.
- Avoid repeating the same facts across multiple sections. Distribute key specs so each section has a unique angle.
- For MYTH_BUSTER, include at least one section with a practical alternative path (demo play, bonus types, low-wagering options, where to play) without naming specific casinos or inventing offers.
-------------------------------------------------
"""

        prompt = f"""
Role: You are a Senior Content Strategist.
Your goal is to create a structured article outline based on the provided topic, facts, and writing strategy.

TOPIC: "{topic}"

{strategy_info}

SPECS:
{specs_str}

SEARCH SUMMARY:
{search_summary}

OUTPUT SCHEMA:
Return a JSON object with keys: 'main_title' (string), 'seo_slug' (string), 'sections' (list of objects).
Each section object must have: 'id' (integer), 'title', 'user_intent', 'key_points', 'rag_query', 'description'.

ADDITIONAL REQUIREMENTS:
- Each section must have distinct key_points. Do not repeat the same metric (RTP, volatility, max win) in more than one section.
- Ensure the outline creates a clear progression: hook -> facts -> features -> alternatives/where-to-play -> conclusion.

EXAMPLE JSON:
{{
  "main_title": "Title Here",
  "seo_slug": "url-slug",
  "sections": [
    {{
      "id": 1,
      "title": "Introduction",
      "user_intent": "Hook the reader",
      "key_points": ["Discuss RTP", "Mention max win"],
      "rag_query": "game basic info"
    }}
  ]
}}

STRICT JSON. No comments. No trailing commas.
"""
        response = await self.llm.async_generate(prompt, temperature=0.4)
        
        # Clean up code blocks if present
        cleaned_response = self._clean_json_string(response)
             
        try:
            outline = json.loads(cleaned_response)
            
            # Post-processing to ensure IDs are sequential integers
            if "sections" in outline and isinstance(outline["sections"], list):
                for i, section in enumerate(outline["sections"]):
                    section["id"] = i + 1
            
            return outline
        except json.JSONDecodeError:
            logger.error(f"Failed to parse outline JSON. Response was: {response[:200]}...")
            # Fallback or error handling
            return None
