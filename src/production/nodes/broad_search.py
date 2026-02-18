import asyncio
import json
import os
import hashlib
from src.services.search_xng import SearchXNGService, WebpageSnippet
from src.utils.logger import setup_logger
from src.config import settings, OUTPUT_DIR

logger = setup_logger("broad_search")

class BroadSearchNode:
    def __init__(self, search_service: SearchXNGService = None):
        self.search_service = search_service or SearchXNGService()

    async def run(self, queries: list[str]) -> list[dict]:
        results = []
        tasks = [self.search_service.search(q, max_results=5) for q in queries]
        
        # Execute all searches
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        seen_urls = set()
        aggregated_snippets = []

        for i, query_results in enumerate(batch_results):
            if isinstance(query_results, list):
                logger.debug(f"Query '{queries[i]}' returned {len(query_results)} results.")
                for snippet in query_results:
                    if isinstance(snippet, WebpageSnippet):
                        if snippet.url not in seen_urls:
                            seen_urls.add(snippet.url)
                            aggregated_snippets.append(snippet.to_dict())
            else:
                logger.error(f"Error in search for '{queries[i]}': {query_results}")

        return aggregated_snippets
