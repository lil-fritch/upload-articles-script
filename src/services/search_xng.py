import os
import asyncio
import aiohttp
import json
import ssl
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

# Assuming you might want to use your config.py, but for now using os.environ as fallback
try:
    from src.config import settings
    SEARCHXNG_HOST_DEFAULT = getattr(settings, "SEARCHXNG_HOST", None)
except ImportError:
    SEARCHXNG_HOST_DEFAULT = None

@dataclass
class WebpageSnippet:
    url: str
    title: str
    description: str
    content_full: Optional[str] = None
    
    def to_dict(self):
        return asdict(self)

class SearchXNGService:
    """
    Service to interact with SearchXNG API.
    """
    def __init__(self, host: str = None):
        self.host = host or SEARCHXNG_HOST_DEFAULT or os.environ.get("SEARCHXNG_HOST")
        
        if not self.host:
             # Just a warning, as we might set it later or in .env
             print("Warning: SEARCHXNG_HOST not set.")
             return

        if not self.host.endswith("/search"):
            self.host = (
                f"{self.host}/search"
                if not self.host.endswith("/")
                else f"{self.host}search"
            )

    async def search(
        self, query: str, max_results: int = 10
    ) -> List[WebpageSnippet]:
        """Perform a search using SearchXNG API."""
        if not self.host:
            print("Error: SearchXNG host is not configured.")
            return []
            
        # Create SSL context that is permissive (if needed for self-signed certs etc)
        # Using default context usually works unless it's a specific internal setup
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                params = {
                    "q": query,
                    "format": "json",
                }
                
                async with session.get(self.host, params=params) as response:
                    # Return empty if status is not 200 to avoid crashing
                    if response.status != 200:
                        print(f"SearchXNG returned status {response.status}")
                        return []
                        
                    results = await response.json()
                    
                    # SearchXNG format usually has 'results' key
                    snippets = []
                    for result in results.get("results", []):
                        snippets.append(WebpageSnippet(
                            url=result.get("url", ""),
                            title=result.get("title", ""),
                            description=result.get("content", "") or result.get("snippet", ""),
                        ))
                    
                    return snippets[:max_results]
        except Exception as e:
            print(f"Error during SearchXNG search: {e}")
            return []
