import json
import re
import datetime
from src.llm_client import LLMClient
from src.utils.logger import setup_logger

logger = setup_logger("query_gen")

class QueryGeneratorNode:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def run(self, topic: str, game_specs: dict = None) -> list[str]:
        """
        Generates search queries based on the topic and optional game specs.
        """
        specs_context = ""
        if game_specs:
            specs_context = f"Context about the game:\nName: {game_specs.get('name')}\nProvider: {game_specs.get('provider')}\nType: {game_specs.get('type')}\n"
        

        current_year = datetime.date.today().year
        specs_context = self._format_specs_for_prompt(game_specs)

        prompt = f"""
        Role: You are an elite SEO Strategist designed to construct high-precision search queries for Google.

        Task: Generate a list of 3-5 Google search queries to gather comprehensive data for an article on:
        TOPIC: "{topic}"

        {specs_context}
        ---

        Guidelines:
        1. **Focus on Gaps:** Compare the TOPIC with the Context Data. Search ONLY for missing information.
        2. **Intent Diversity:** Cover these angles:
           - *Commercial:* Best casinos/bonuses (include "{current_year}").
           - *Informational:* Rules, hidden features, free play.
           - *Social Proof:* Real discussions (e.g., use "site:reddit.com").
        3. **Language:** English.

        Output Format:
        Return a valid JSON object with a single key "queries" containing the list of strings.
        STRICT JSON ONLY. No comments (// or #). No intro text.
        Example: {{ "queries": ["query 1", "query 2", "query 3"] }}
        """
        
        response = await self.llm.async_generate(prompt, temperature=0.5)
        
        cleaned_response = response.strip()
        json_match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
        
        if json_match:
            cleaned_response = json_match.group(0)
        
        cleaned_response = re.sub(r'^\s*//.*$', '', cleaned_response, flags=re.MULTILINE)
        cleaned_response = re.sub(r'/\*.*?\*/', '', cleaned_response, flags=re.DOTALL)
        cleaned_response = re.sub(r',\s*([\]}])', r'\1', cleaned_response)
        
        try:
            data = json.loads(cleaned_response)
            
            if isinstance(data, dict) and "queries" in data:
                return data["queries"]
            elif isinstance(data, list):
                return data
            else:
                return list(data.values())[0] if data else [topic]
                
        except json.JSONDecodeError:
            print(f"JSON Parsing Error. Raw response: {response}")
            return [
                f"{topic} review",
                f"{topic} bonuses {current_year}",
                f"{topic} strategy"
            ]

    def _format_specs_for_prompt(self, game_specs: dict) -> str:
        if not game_specs:
            return "Context Data: None (Find everything via search)."

        readable_specs = []
        
        if game_specs.get('name'):
            readable_specs.append(f"Game Name: {game_specs['name']}")
        
        if game_specs.get('provider'):
            readable_specs.append(f"Provider: {game_specs['provider']}")
            
        if game_specs.get('type'):
            readable_specs.append(f"Game Type: {game_specs['type']}")

        if game_specs.get('rtp') and str(game_specs['rtp']).strip():
            readable_specs.append(f"RTP: {game_specs['rtp']}")
        
        if game_specs.get('max_win') and str(game_specs['max_win']).strip():
            readable_specs.append(f"Max Win: {game_specs['max_win']}")
            
        themes_raw = game_specs.get('themes')
        if themes_raw:
            try:
                themes_list = json.loads(themes_raw) if isinstance(themes_raw, str) else themes_raw
                theme_names = [t['name'] for t in themes_list if 'name' in t]
                if theme_names:
                    readable_specs.append(f"Themes: {', '.join(theme_names)}")
            except:
                pass

        missing_fields = []
        if not game_specs.get('rtp'): missing_fields.append("RTP")
        if not game_specs.get('max_win'): missing_fields.append("Max Win")
        if not game_specs.get('min_bet'): missing_fields.append("Min/Max Bets")

        output = "KNOWN FACTS (Do not search for these):\n"
        output += "\n".join(f"- {line}" for line in readable_specs)
        
        if missing_fields:
            output += "\n\nMISSING DATA (PRIORITY to search):\n"
            output += f"We explicitly lack: {', '.join(missing_fields)}. Please generate queries to find these specifically."
            
        return output