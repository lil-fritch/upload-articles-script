from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import json

class BaseAgent(ABC):
    """
    Abstract base class for all agents in the system.
    """
    def __init__(self, llm_client, role: str, goal: str):
        self.llm = llm_client
        self.role = role
        self.goal = goal

    @abstractmethod
    def run(self, input_data: Any) -> Any:
        """
        Main entry point for the agent to perform its task.
        """
        pass

    def generate_json(self, prompt: str, temperature: float = 0.7) -> Dict:
        """
        Helper method to generate JSON output using the LLM.
        Directs the LLM to output valid JSON and attempts to parse it.
        """
        system_instruction = (
            f"You are a {self.role}. Your goal is: {self.goal}.\n"
            "IMPORTANT: Output ONLY valid JSON."
        )
        full_prompt = f"{system_instruction}\n\n{prompt}"
        
        response_text = self.llm.generate(full_prompt, temperature)
        try:
            # First, try to just load it. Sometimes it works if it's pure JSON.
            # But often there's extra text.
            
            # Helper: extract content between first { and last }
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            
            if start != -1 and end != -1:
                potential_json = response_text[start:end]
                return json.loads(potential_json)
            
            # If that failed or no braces found, let's try regex for markdown blocks
            import re
            markdown_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if markdown_match:
                 return json.loads(markdown_match.group(1))
                 
            # Last ditch: try loading the whole text
            return json.loads(response_text)

        except (json.JSONDecodeError, ValueError) as e:
             # print(f"Error parsing JSON from agent {self.role}. Raw response: {response_text[:100]}...")
             # Maybe retry or just return empty?
             # Let's print the error for debugging but return empty dict
             print(f"Error parsing JSON from agent {self.role}: {e}")
             print(f"Raw response start: {response_text[:200]}")
             return {}
    
    def generate_text(self, prompt: str, temperature: float = 0.7) -> str:
        """
        Helper method to generate plain text.
        """
        system_instruction = f"You are a {self.role}. Your goal is: {self.goal}."
        full_prompt = f"{system_instruction}\n\n{prompt}"
        return self.llm.generate(full_prompt, temperature)
