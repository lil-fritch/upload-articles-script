import os
import re
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from src.utils.filename_utils import get_safe_filename
from src.config import OUTPUT_DIR, settings
from src.services.rag_store import EphemeralRAG

logger = setup_logger("compiler")

class CompilerNode:
    def __init__(self, rag_store: EphemeralRAG = None):
        self.rag_store = rag_store
        self.articles_dir = OUTPUT_DIR / "articles"
        os.makedirs(self.articles_dir, exist_ok=True)

    def add_cta(self, game_name: str) -> str:
        return f"""
<!-- CTA START -->
<div class="cta-box">
  <h3>Ready to Play {game_name}?</h3>
  <p>Claim your welcome bonus and start spinning today!</p>
  <a href="#" class="btn-primary">Play Real Money</a>
</div>
<!-- CTA END -->
"""

    def run(self, topic: str, outline: Dict[str, Any], sections: Dict[str, str], game_specs: Optional[Dict]) -> tuple[str, str]:
        """
        Assembles, saves the article, and cleans up RAG.
        Returns the path to the saved file.
        """
        if not outline or not sections:
            logger.error(f"Cannot compile article for '{topic}': Missing outline or sections.")
            return "", ""

        game_name = game_specs.get("name", "this game") if game_specs else topic
        main_title = outline.get("main_title", topic)
        
        # 1. Assemble Content
        lines = []
        
        # Frontmatter
        lines.append("---")
        lines.append(f"title: {main_title}")
        lines.append(f"description: {outline.get('meta_description', '')}")
        lines.append(f"keywords: {outline.get('keywords', [])}")
        lines.append("---")
        lines.append("")
        
        # H1
        lines.append(f"# {main_title}")
        lines.append("")
        
        # Sections
        # We need to respect the order from the outline
        outline_sections = outline.get("sections", [])
        
        for section in outline_sections:
            s_id = section.get("id")
            if s_id in sections:
                lines.append(sections[s_id])
                lines.append("")
            else:
                logger.warning(f"Section {s_id} missing from written drafts.")

        # CTA removed - will be added later via bulk script when ready
        # lines.append(self.add_cta(game_name))
        
        final_content = "\n".join(lines)
        
        # 2. Save File
        # Use TOPIC for filename to ensure determinism and allow pre-checks
        safe_name = get_safe_filename(topic)
        file_path = self.articles_dir / f"{safe_name}.md"
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(final_content)
            logger.info(f"Article saved to: {file_path}")
        except Exception as e:
            logger.error(f"Failed to save article to {file_path}: {e}")
            return "", ""

        # 3. Cleanup RAG
        if self.rag_store:
            try:
                self.rag_store.cleanup(force=True)
                logger.info("RAG cleanup successful.")
            except Exception as e:
                logger.error(f"RAG cleanup failed: {e}")

        return str(file_path), final_content
