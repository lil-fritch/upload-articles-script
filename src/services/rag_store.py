import lancedb
import os
import shutil
from typing import List, Dict, Any, Callable
from sentence_transformers import SentenceTransformer
from src.utils.logger import setup_logger
from src.config import DB_DIR, settings

logger = setup_logger("rag_store")

class EphemeralRAG:
    """
    Manages a temporary LanceDB vector store for RAG with physical isolation per session.
    """
    def __init__(self):
        self.base_dir = DB_DIR / "lancedb_sessions"
        os.makedirs(self.base_dir, exist_ok=True)
        
        logger.info("Loading embedding model: paraphrase-multilingual-MiniLM-L12-v2")
        self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        
        self.current_session_path = None
        self.db = None
        self.tbl = None

    def init_session(self, session_id: str):
        """
        Initializes a fresh DB environment for a specific topic/session.
        Physically isolates data by creating a unique directory.
        """
        # Ensure previous session is closed/cleaned if necessary (though usually handled by cleanup)
        self.tbl = None
        
        # Create unique path
        safe_id = "".join(x for x in session_id if x.isalnum())[:50]
        self.current_session_path = self.base_dir / f"session_{safe_id}"
        
        # Enforce fresh start
        if self.current_session_path.exists():
            logger.info(f"Removing existing RAG session: {self.current_session_path}")
            shutil.rmtree(self.current_session_path)
        
        os.makedirs(self.current_session_path, exist_ok=True)
        
        logger.info(f"Connecting to LanceDB at {self.current_session_path}")
        self.db = lancedb.connect(str(self.current_session_path))
        self.tbl = None

    def index_chunks(self, chunks: List[str]):
        if not chunks:
            logger.warning("No chunks to index.")
            return

        # If data exists, drop it to be safe
        if "chunks" in self.db.table_names():
             self.db.drop_table("chunks")

        logger.info(f"Embedding {len(chunks)} chunks...")
        embeddings = self.model.encode(chunks)
        
        data = []
        for i, chunk in enumerate(chunks):
            # Extract source if possible
            source = "unknown"
            if "Source: " in chunk:
                 try:
                     parts = chunk.split("Source: ")
                     if len(parts) > 1:
                        source = parts[1].split("\n")[0].strip()
                 except:
                     pass
            
            data.append({
                "vector": embeddings[i],
                "text": chunk,
                "source": source,
                "id": i
            })
            
        self.tbl = self.db.create_table("chunks", data)
        logger.info(f"Indexed {len(data)} chunks.")

    def as_retriever(self, limit: int = 5) -> Callable[[str], List[str]]:
        """
        Returns a callable retriever function correctly bound to the current table.
        """
        def retrieve(query: str) -> List[str]:
            if not self.tbl:
                logger.warning("Retriever called but table is None.")
                return []
            try:
                query_vec = self.model.encode([query])[0]
                results = self.tbl.search(query_vec).limit(limit).to_list()
                return [r["text"] for r in results]
            except Exception as e:
                logger.error(f"Retrieval error: {e}")
                return []
        
        return retrieve

    def cleanup(self, force: bool = False):
        """
        Physically removes the session directory.
        """
        self.tbl = None
        self.db = None # Allow GC to close connection hopefully
        
        if self.current_session_path and self.current_session_path.exists():
            if settings.DEBUG and not force:
                logger.info(f"DEBUG: Keeping RAG session at {self.current_session_path}")
            else:
                logger.info(f"Cleaning up RAG session at {self.current_session_path}")
                try:
                    shutil.rmtree(self.current_session_path)
                except Exception as e:
                    logger.error(f"Failed to delete session dir: {e}")
        
        self.current_session_path = None
