import asyncio
import os
import re
from typing import List, Dict, Any
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from src.services.scraper import ScraperService
from src.services.rag_store import EphemeralRAG
from src.utils.logger import setup_logger
from src.config import OUTPUT_DIR

logger = setup_logger("scraper_indexer")

class ScraperIndexerNode:
    def __init__(self):
        self.scraper = ScraperService()
        self.rag_store = EphemeralRAG()
        
        headers_to_split_on = [
            ("#", "H1"),
            ("##", "H2"),
            ("###", "H3"),
        ]
        self.header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, 
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def _smart_split(self, markdown_text: str, source_url: str) -> List[str]:
        """
        Splits markdown into labeled chunks preserving header context.
        """
        if not markdown_text:
            return []
            
        header_splits = self.header_splitter.split_text(markdown_text)
        
        final_docs = self.text_splitter.split_documents(header_splits)
        
        chunks = []
        for doc in final_docs:
            headers = [doc.metadata.get(key) for key in ["H1", "H2", "H3"] if doc.metadata.get(key)]
            context_str = " > ".join(headers) if headers else "General"
            
            chunk_content = f"Source: {source_url}\nContext: {context_str}\n\n{doc.page_content}"
            chunks.append(chunk_content)
        
        clean_chunks = [
            chunk for idx, chunk in enumerate(chunks) 
            if not self._is_garbage_chunk(final_docs[idx].page_content)
        ]
        
        garbage_count = len(chunks) - len(clean_chunks)
        if garbage_count > 0:
            logger.debug(f"Dropped {garbage_count} garbage chunks from {source_url}")

        return clean_chunks
    
    @staticmethod
    def _is_garbage_chunk(text: str) -> bool:
        # 1. Базовая проверка длины
        if len(text) < 100:
            return True
            
        text_lower = text.lower()

        critical_garbage_triggers = [
            "verify you are human", "checking your browser", "access denied", 
            "403 forbidden", "blocked by network security", "cloudflare", "ray id:", 
            "confirm you are a human", "target url returned error",
            
            "session expired", "forgot password", "two factor authentication",
            "create account", "join today and get", "enter your e-mail address",
            
            "based on your ip address", "detected that you are visiting",
            "gambling regulations in germany",
            
            "html local storage", "indexeddb", "storage duration", 
            "ytidb", "yt-remote", "last_result_entry_key",
            "tap to unmute", "you're signed out", "videos you watch may be added",
            
            "consent selection", "do not sell or share", "powered by cookiebot",
            "strictly necessary cookies"
        ]
        
        if any(trigger in text_lower for trigger in critical_garbage_triggers):
            return True

        cookie_context_triggers = [
            "cookie declaration", "consent id", "marketing cookies", 
            "withdraw your consent", "google analytics", "privacy policy", 
            "use cookies", "all rights reserved", "cookie settings",
            "we use cookies", "personalise content"
        ]
        
        cookie_matches = sum(1 for t in cookie_context_triggers if t in text_lower)
        if cookie_matches >= 2:
            return True

        # 4. Плотность ссылок
        links = re.findall(r'\[.*?\]\(.*?\)', text)
        link_char_count = sum(len(l) for l in links)
        if len(text) > 0 and (link_char_count / len(text)) > 0.4:
            return True

        return False
    
    async def run(self, topic: str, search_results: List[Dict[str, Any]], limit: int = 5):
        """
        Scrapes top search results, splits them, and indexes them.
        Returns (chunks, retriever).
        """
        # Switch to topic specific index for safety/debug persistence
        # Simple sanitization for table name: logic similar to filename but strict alphanumeric
        safe_index_name = "".join(x for x in topic if x.isalnum()).lower()[:50]
        if not safe_index_name:
            safe_index_name = "generic_index"
            
        # Use INIT_SESSION for physical isolation
        self.rag_store.init_session(safe_index_name)

        urls = [res.get('url') for res in search_results if res.get('url')][:limit]

        if not urls:
            logger.warning("No URLs to scrape.")
            return [], None

        logger.info(f"Scraping {len(urls)} URLs...")
        
        try:
            raw_contents = await self._scrape_all(urls)
        except Exception as e:
            logger.error(f"Critical error in scraping loop: {e}")
            return [], None
        finally:
            try:
                await self.scraper.close()
            except Exception:
                pass
        
        all_chunks = []
        for i, content in enumerate(raw_contents):
            url = urls[i]

            if isinstance(content, Exception):
                logger.warning(f"Skipping {url} due to scrape error: {content}")
                continue
            
            if not content:
                continue
            
            # Split logic
            try:
                chunks = self._smart_split(content, url)
                if chunks:
                    logger.debug(f"URL {url}: Generated {len(chunks)} clean chunks.")
                    all_chunks.extend(chunks)
            except Exception as e:
                logger.error(f"Error splitting content from {url}: {e}")

        logger.info(f"Total chunks generated: {len(all_chunks)}")
        
        retriever = None
        if all_chunks:
            # Indexing
            logger.info("Indexing chunks...")
            self.rag_store.index_chunks(all_chunks)
            retriever = self.rag_store.as_retriever()
            logger.info("Indexing complete. Retriever ready.")

        return all_chunks, retriever

    async def _scrape_all(self, urls):
        tasks = [self.scraper.fetch_content(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=True)