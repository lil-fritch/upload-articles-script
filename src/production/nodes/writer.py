import re
import json
from typing import Any, Dict, List, Optional
from src.production.nodes.fact_validator import ArticlePassport
from src.llm_client import LLMClient
from src.utils.logger import setup_logger

logger = setup_logger("writer")

class SectionWriterNode:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def retrieve_context(self, retriever: Any, query: str, limit: int = 4) -> str:
        """
        Uses the ephemeral retriever to find relevant chunks for the section.
        """
        if not retriever:
            return ""
        
        try:
            # Retrieve chunks
            chunks = retriever(query) # The retriever is a callable lambda/function
            # Take top 'limit' chunks
            top_chunks = chunks[:limit]
            return "\n\n".join(top_chunks)
        except Exception as e:
            logger.error(f"Retrieval failed for query '{query}': {e}")
            return ""

    def format_specs(self, game_specs: Optional[Dict[str, Any]]) -> str:
        if not game_specs:
            return "No verifiable data specs available from database."
        
        # Simple formatting of specs
        lines = ["--- GAME DATABASE SPECS (AXIOM) ---"]
        for k, v in game_specs.items():
            if v is not None:
                lines.append(f"{k}: {v}")
        lines.append("-----------------------------------")
        return "\n".join(lines)

    async def write_section(self, topic: str, section: Dict[str, Any], specs_text: str, context_text: str, passport: Optional[ArticlePassport] = None) -> str:
        section_title = section.get("title", "")
        # Если в section есть ключи 'user_intent' или 'key_points' (из этапа Strategist), добавляем их
        section_intent = section.get("user_intent", "Inform and engage")
        key_points = section.get("key_points", [])
        
        # Превращаем список поинтов в текст
        points_str = "\n".join([f"- {p}" for p in key_points]) if key_points else "Cover the section topic comprehensively."

        # Pass strategy instructions
        strategy_info = ""
        if passport:
            decision = passport.get("decision", {})
            facts = passport.get("facts", {})
            tech_specs = passport.get("technical_specs", {})
            
            # Safe access to nested technical specs
            rtp_val = tech_specs.get("rtp_single_value", "N/A")
            mech_type = tech_specs.get("mechanics_type", "PAYLINES")
            currency = tech_specs.get("currency_format", {"min_bet": "$0.10", "max_bet": "$100"})
            min_bet = currency.get("min_bet", "$0.10")
            max_bet = currency.get("max_bet", "$100")

            strategy_info = f"""
STRICT STRATEGY INSTRUCTIONS:
- Strategy: {decision.get('selected_writing_strategy')}
- Pivot Reason: {decision.get('pivot_reason')}
- Verified Facts: {json.dumps(facts)}

--- CRITICAL: ONE TRUTH POLICY (Overrides all other data) ---
1. RTP: You MUST use "{rtp_val}" as the definitive RTP. Ignore all other RTP values found in context.
2. BETS: You MUST use "{min_bet}" to "{max_bet}". Never use bare numbers like "20".
3. MECHANICS:
   - Type: {mech_type}
   - IF 'PAY_ANYWHERE': DO NOT use words 'lines', 'connected', 'adjacent', 'touching'. Use '8+ matching symbols anywhere'.
   - IF 'CLUSTER_PAYS': Use 'touching horizontally or vertically'.
   - IF 'PAYLINES': Use standard paylines terminology.
-------------------------------------------------------------
- Do not invent facts not listed in the 'Verified Facts' section.
"""

        prompt = f"""
Role: You are a Conversion-Focused iGaming Copywriter. 
Your goal is to write a compelling section for a slot review that drives player interest while remaining factual.

TOPIC: "{topic}"
SECTION TITLE: "{section_title}"
PLAYER INTENT: {section_intent}

INPUT DATA:
1. HARD SPECS (Axioms - Never deviate): 
{specs_text}

2. STRATEGY POINTS (Must cover these):
{points_str}

3. RESEARCH CONTEXT (Use for depth/details):
{context_text}

4. STRATEGY COMPLIANCE:
{strategy_info}

--------------------------------------------------
STRICT PROHIBITIONS (Violations = Failure):
1. NO EXTERNAL LINKS: Do not include URLs, domain names (e.g., sigma.world), or hyperlinks.
2. NO CITATIONS: Do not write "According to [Source]". Integrate facts naturally.
3. NO FAKE CASINOS: Do not invent casino names. Do not use placeholders like [TOP_CASINO]. instead, use generic terms like "top-rated online casinos", "trusted operators", or "licensed sites".
4. NO COMPETITOR MENTIONS: Do not mention other review sites (e.g., SlotCatalog, BigWinBoard).
--------------------------------------------------

WRITING INSTRUCTIONS:
- Tone: Expert, enthusiastic, but grounded in math (RTP/Volatility).
- Formatting: Use clean Markdown ONLY. Use **bold** for key metrics (NOT HTML tags like <b>).
- Structure: Divide content into logical subsections with ## H2 or ### H3 headers where appropriate. Do not write one solid block of text.
- Conflict Resolution: If Research Context contradicts Hard Specs, TRUST HARD SPECS.
- Flow: Do not start with "In this section...". Jump straight into the value.
- Anti-repetition: Do not repeat the same metric (RTP, volatility, max win) more than once in this section. If it is not essential to this section, omit it.
- Anti-repetition: Avoid reusing identical phrases from other sections. This section must add new value or angle.
- Myth-buster pivot: If debunking a claim, state the truth naturally in your own words — vary your phrasing across articles. Then offer a practical alternative path (demo play, welcome bonus types, low-wagering offers, where to play) without naming specific casinos or inventing offers.
- Advice: Prefer 2-3 concrete, actionable tips over generic filler.
- Headings: Use markdown headers (## or ###) for subsections, NOT HTML.

OUTPUT:
Write ONLY the content for the section "{section_title}".
Do NOT prefix content with labels like "Hook:", "Introduction:", "Key Points:", etc. Start directly with the content.
"""

        content = await self.llm_client.async_generate(prompt)
        content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)
        content = re.sub(r'https?://\S+', '', content)
        content = re.sub(r'\b\w+\.(com|org|net|io|world)\b', '', content)

        return content.strip()

    async def run(self, topic: str, outline: Dict, game_specs: Dict, retriever: Any, passport: Optional[ArticlePassport] = None) -> Dict[str, str]:
        """
        Iterates over sections and writes them up.
        """
        if not outline or "sections" not in outline:
            logger.warning("No outline provided to writer.")
            return {}

        logger.info(f"Writing {len(outline['sections'])} sections for '{topic}'...")
        
        specs_text = self.format_specs(game_specs)
        written_sections = {}

        for section in outline["sections"]:
            s_id = section.get("id")
            s_title = section.get("title")
            
            query = f"{s_title} {section.get('description', '')}"
            
            logger.debug(f"Retrieving context for section: '{s_title}'")
            context_text = self.retrieve_context(retriever, query)
            
            logger.debug(f"Writing section: '{s_title}'")
            content = await self.write_section(topic, section, specs_text, context_text, passport)
            
            written_sections[s_id] = content
            logger.info(f"Completed section {s_id}: {s_title}")

        return written_sections
