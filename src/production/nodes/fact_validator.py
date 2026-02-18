from typing import TypedDict, List, Optional, Literal, Dict, Any
import json
from src.llm_client import LLMClient
from src.utils.logger import setup_logger

logger = setup_logger("fact_validator")

class AnalysisData(TypedDict):
    query_intent: Literal["GAME_SPECIFIC", "GENERIC", "BRAND"]
    detected_game_name: Optional[str]
    is_real_game: bool

class FactsData(TypedDict):
    provider: Optional[str]
    rtp: Optional[str]
    volatility: Optional[str]
    has_jackpot: bool
    features: List[str]

class DecisionData(TypedDict):
    match_status: Literal["EXACT_MATCH", "FEATURE_MISMATCH", "NON_EXISTENT_GAME", "LOGICAL_CONTRADICTION", "GENERIC_QUERY"]
    selected_writing_strategy: Literal["DIRECT_REVIEW", "MYTH_BUSTER", "GENRE_OVERVIEW", "STRATEGY_GUIDE", "GENERIC_GUIDE"]
    pivot_reason: str

class CurrencyFormat(TypedDict):
    min_bet: str
    max_bet: str

class TechnicalSpecs(TypedDict):
    mechanics_type: Literal["PAYLINES", "CLUSTER_PAYS", "PAY_ANYWHERE", "MEGAWAYS", "INSTANT_WIN"]
    rtp_single_value: Optional[str]
    currency_format: CurrencyFormat

class ArticlePassport(TypedDict):
    analysis: AnalysisData
    decision: DecisionData
    facts: FactsData
    technical_specs: TechnicalSpecs

class FactValidatorNode:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def run(self, topic: str, search_results: List[Dict]) -> ArticlePassport:
        
        # Prepare search summary similar to Strategist
        search_summary = "\n".join([
            f"- Title: {res.get('title', 'No Title')}\n  Snippet: {res.get('description', 'No Description')}" 
            for res in search_results
        ])

        prompt = f"""
Role: You are an expert Gambling Fact-Checker and Content Strategist.
Your goal is to validate the user's query against search results to prevent AI hallucinations.

USER QUERY: "{topic}"

SEARCH SNIPPETS:
{search_summary}

---
TASK:
Analyze if the User Query corresponds to a real, existing game with the requested features.
Determine the "Truth Status" and select the best writing strategy.

definitions:
1. EXACT_MATCH: Game exists AND has the requested feature (e.g., "Starburst NetEnt").
2. FEATURE_MISMATCH: Game exists, but requested feature is missing (e.g., "Starburst Progressive Jackpot").
3. NON_EXISTENT_GAME: Query looks like a game name, but no such game exists in snippets (e.g., "Evoplay Lottery Ticket" if only general lottery info exists).
4. LOGICAL_CONTRADICTION: Query asks for impossible combo (e.g., "Safe High Volatility Slot").
5. GENERIC_QUERY: Query is about a genre/type, not a specific game name (e.g., "Best high rtp slots").

MAPPING RULES (match_status -> selected_writing_strategy):
- EXACT_MATCH -> DIRECT_REVIEW
- FEATURE_MISMATCH -> MYTH_BUSTER
- NON_EXISTENT_GAME -> GENRE_OVERVIEW
- LOGICAL_CONTRADICTION -> STRATEGY_GUIDE
- GENERIC_QUERY -> GENERIC_GUIDE

OUTPUT SCHEMA (JSON Only):
{{
  "analysis": {{
    "query_intent": "GAME_SPECIFIC | GENERIC | BRAND",
    "detected_game_name": "String OR null", 
    "is_real_game": true/false
  }},
  "decision": {{
    "match_status": "Status from definitions",
    "selected_writing_strategy": "Strategy from mapping",
    "pivot_reason": "Explain why this strategy was chosen."
  }},
  "facts": {{
    "provider": "String OR null",
    "rtp": "String OR null",
    "volatility": "String OR null",
    "has_jackpot": true/false,
    "features": ["found feature 1", "found feature 2"]
  }},
  "technical_specs": {{
    "mechanics_type": "PAYLINES | CLUSTER_PAYS | PAY_ANYWHERE | MEGAWAYS | INSTANT_WIN",
    "rtp_single_value": "96.50%", 
    "currency_format": {{
      "min_bet": "$0.20",
      "max_bet": "$100"
    }}
  }}
}}

INSTRUCTIONS:
- Be strict. If the specific game name shows no results, mark NON_EXISTENT_GAME.
- Extract ONLY verified facts from snippets. Do not halluncinate RTP or Provider.
- If NON_EXISTENT_GAME, 'facts' should be empty or general.

NORMALIZATION RULES (CRITICAL):
1. RTP Fix: If multiple RTPs found (95.5, 96.5), select the HIGHEST ONE and put it in 'rtp_single_value'.
2. Mechanics Classifier:
    - If snippets contain "Scatter Pays", "Pay Anywhere", "Wins all ways" -> "PAY_ANYWHERE".
    - If snippets contain "Cluster", "Group of 5+" -> "CLUSTER_PAYS".
    - If "Megaways" -> "MEGAWAYS".
    - Default/Standard -> "PAYLINES".
    - Be precise. 'Gates of Olympus' clones are ALWAYS 'PAY_ANYWHERE'. 'Reactoonz' is 'CLUSTER_PAYS'.
3. Currency Normalizer:
    - Convert bare numbers to currency strings.
    - If "min bet: 20", assume it is 0.20 unless High Limit Context. -> "$0.20".
    - Always include symbol ($/€/£).
"""
        response = await self.llm.async_generate(prompt, temperature=0.0)
        
        try:
            # Basic cleanup
            cleaned = response.strip()
            # Remove markdown code blocks if present
            if "```" in cleaned:
                # Extract content inside the first code block
                parts = cleaned.split("```")
                for part in parts:
                    if "{" in part and "}" in part:
                        cleaned = part
                        if cleaned.startswith("json"):
                             cleaned = cleaned[4:]
                        break
            
            # Find the first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                cleaned = cleaned[start:end+1]
            
            passport = json.loads(cleaned)
            
            # --- VALIDATION & REPAIR ---
            # Ensure all required top-level keys exist
            defaults = {
                "analysis": {"query_intent": "GENERIC", "detected_game_name": None, "is_real_game": False},
                "decision": {
                    "match_status": "GENERIC_QUERY", 
                    "selected_writing_strategy": "GENERIC_GUIDE", 
                    "pivot_reason": "Fallback: Missing decision data in LLM response."
                },
                "facts": {"provider": None, "rtp": None, "volatility": None, "has_jackpot": False, "features": []},
                "technical_specs": {
                     "mechanics_type": "PAYLINES",
                     "rtp_single_value": "Unknown",
                     "currency_format": {"min_bet": "$0.10", "max_bet": "$100"}
                 }
            }

            for key, default_val in defaults.items():
                if key not in passport or not isinstance(passport[key], dict):
                    logger.warning(f"Passport missing '{key}', using default.")
                    passport[key] = default_val

            # Ensure sub-keys for decision exist (since we log them)
            if "match_status" not in passport["decision"]:
                passport["decision"]["match_status"] = "GENERIC_QUERY"
            if "selected_writing_strategy" not in passport["decision"]:
                passport["decision"]["selected_writing_strategy"] = "GENERIC_GUIDE"

            logger.info(f"Passport Generated: {passport['decision']['match_status']} -> {passport['decision']['selected_writing_strategy']}")
            return passport

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to parse Passport JSON. Error: {e}. Response: {response[:200]}")
            # Fallback safe passport
            return {
                "analysis": {"query_intent": "GENERIC", "detected_game_name": None, "is_real_game": False},
                "decision": {"match_status": "GENERIC_QUERY", "selected_writing_strategy": "GENERIC_GUIDE", "pivot_reason": "Fallback due to parse error"},
                "facts": {"provider": None, "rtp": None, "volatility": None, "has_jackpot": False, "features": []},
                "technical_specs": {
                     "mechanics_type": "PAYLINES",
                     "rtp_single_value": "Unknown",
                     "currency_format": {"min_bet": "$0.10", "max_bet": "$100"}
                 }
            }
