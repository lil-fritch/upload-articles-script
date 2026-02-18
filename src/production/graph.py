from typing import TypedDict, Optional, Dict, Any, List
from langgraph.graph import StateGraph, END
from src.planning.db_check import LocalDBCheck
from src.production.nodes.query_generator import QueryGeneratorNode
from src.production.nodes.broad_search import BroadSearchNode
from src.production.nodes.strategist import StrategistNode, ArticleOutline
from src.production.nodes.fact_validator import FactValidatorNode, ArticlePassport
from src.production.nodes.scraper_indexer import ScraperIndexerNode
from src.production.nodes.writer import SectionWriterNode
from src.production.nodes.compiler import CompilerNode
from src.utils.logger import setup_logger

logger = setup_logger("graph")

class ProductionState(TypedDict):
    """
    State for the article generation workflow.
    """
    topic_data: Dict[str, Any]
    game_specs: Optional[Dict[str, Any]]
    specs_missing: bool
    search_queries: List[str]
    search_results: List[Dict[str, Any]]
    article_passport: Optional[ArticlePassport]
    outline: Optional[ArticleOutline]
    rag_chunks: List[str]
    retriever: Any  # EphemeralRAG retriever function
    article_sections: Dict[str, str] # Final written content parts
    final_article_path: str # Path to saved article
    final_article_text: str # Full article content

class GraphBuilder:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.db_checker = LocalDBCheck()
        
        # Initialize nodes
        self.query_generator_node = QueryGeneratorNode(llm_client)
        self.broad_search_node = BroadSearchNode()
        self.fact_validator_node = FactValidatorNode(llm_client)
        self.strategist_node = StrategistNode(llm_client)
        self.scraper_indexer_node = ScraperIndexerNode()
        self.writer_node = SectionWriterNode(llm_client)
        # Share the RAG store instance so compiler can clean it up
        self.compiler_node = CompilerNode(rag_store=self.scraper_indexer_node.rag_store)

    def build(self):
        workflow = StateGraph(ProductionState)
        
        # Add Nodes
        workflow.add_node("local_db_check", self.run_local_db_check)
        workflow.add_node("query_generator", self.run_query_generator)
        workflow.add_node("broad_search", self.run_broad_search)
        workflow.add_node("fact_validator", self.run_fact_validator)
        workflow.add_node("strategist", self.run_strategist)
        workflow.add_node("scraper_indexer", self.run_scraper_indexer)
        workflow.add_node("section_writer", self.run_section_writer)
        workflow.add_node("compiler", self.run_compiler)
        
        # Set Entry Point
        workflow.set_entry_point("local_db_check")
        
        # Add Edges
        workflow.add_edge("local_db_check", "query_generator")
        workflow.add_edge("query_generator", "broad_search")
        workflow.add_edge("broad_search", "fact_validator")
        workflow.add_edge("fact_validator", "strategist")
        workflow.add_edge("strategist", "scraper_indexer")
        workflow.add_edge("scraper_indexer", "section_writer")
        workflow.add_edge("section_writer", "compiler")
        workflow.add_edge("compiler", END)
        
        return workflow.compile()

    async def run_local_db_check(self, state: ProductionState):
        topic = state["topic_data"].get("topic", "")
        specs = self.db_checker.find_game_in_topic(topic)
        
        if specs:
            logger.info(f"DB CHECK: Found valid specs for '{specs.name}'")
            return {
                "game_specs": specs.model_dump(),
                "specs_missing": False
            }
        else:
            logger.warning(f"DB CHECK: No game specs found for topic '{topic}'")
            return {
                "game_specs": None,
                "specs_missing": True
            }

    async def run_query_generator(self, state: ProductionState):
        topic = state["topic_data"].get("topic", "")
        game_specs = state.get("game_specs")
        
        logger.debug(f"Generating queries for: '{topic}'")
        queries = await self.query_generator_node.run(topic, game_specs)
        logger.info(f"QUERY GEN: Generated {len(queries)} search queries.")
        return {"search_queries": queries}

    async def run_broad_search(self, state: ProductionState):
        queries = state.get("search_queries", [])
        if not queries:
             return {"search_results": []}

        logger.debug(f"Executing broad search with {len(queries)} queries...")
        results = await self.broad_search_node.run(queries)
        logger.info(f"BROAD SEARCH: Found {len(results)} unique results.")
        return {"search_results": results}

    async def run_fact_validator(self, state: ProductionState):
        topic = state["topic_data"].get("topic", "")
        search_results = state.get("search_results", [])
        
        logger.info(f"VALIDATING FACTS for topic: '{topic}'")
        passport = await self.fact_validator_node.run(topic, search_results)
        
        # Log the strategy decision
        strategy = passport.get("decision", {}).get("selected_writing_strategy", "UNKNOWN")
        logger.info(f"STRATEGY SELECTED: {strategy}")
        
        return {"article_passport": passport}

    async def run_strategist(self, state: ProductionState):
        topic = state["topic_data"].get("topic", "")
        game_specs = state.get("game_specs")
        search_results = state.get("search_results", [])
        passport = state.get("article_passport")
        
        logger.debug(f"Creating outline for: '{topic}'")
        outline = await self.strategist_node.run(topic, game_specs, search_results, passport)
        if outline:
             logger.info(f"STRATEGIST: Created outline '{outline.get('main_title')}'")
        else:
             logger.error("STRATEGIST: Failed to generate outline.")
        return {"outline": outline}

    async def run_scraper_indexer(self, state: ProductionState):
        """
        Node: Scraper & Indexer
        """
        topic = state["topic_data"].get("topic", "")
        search_results = state.get("search_results", [])
        logger.info("RAG INGEST: Starting content scraping and indexing...")
        
        # New signature returns chunks AND retriever
        chunks, retriever = await self.scraper_indexer_node.run(topic, search_results, limit=len(search_results))
        
        if retriever:
            logger.info("RAG INGEST: No new chunks (cached or empty), but retriever is ready.")
            
        return {"rag_chunks": chunks, "retriever": retriever}

    async def run_section_writer(self, state: ProductionState):
        """
        Node: Section Writer
        """
        topic = state["topic_data"].get("topic", "")
        outline = state.get("outline")
        specs = state.get("game_specs")
        passport = state.get("article_passport")
        retriever = state.get("retriever")

        if not outline:
            logger.error("WRITER: No outline found in state.")
            return {"article_sections": {}}

        logger.info(f"WRITER: Starting generation for '{topic}'")
        sections = await self.writer_node.run(topic, outline, specs, retriever, passport)
        
        logger.info(f"WRITER: Finished writing {len(sections)} sections.")
        return {"article_sections": sections}

    async def run_compiler(self, state: ProductionState):
        """
        Node: Compiler (Finalizer)
        """
        topic = state["topic_data"].get("topic", "")
        # Safely get topic details for logging, defaulting to 'Unknown Topic' if not provided
        logger.info(f"COMPILER: Assembling article for '{topic}'...")
        
        outline = state.get("outline")
        sections = state.get("article_sections")
        game_specs = state.get("game_specs")
        
        final_path, final_text = self.compiler_node.run(topic, outline, sections, game_specs)

        if final_path:
            logger.info(f"COMPILER: Success! Article saved at {final_path}")
        else:
            logger.error("COMPILER: Failed to save article.")

        return {"final_article_path": final_path, "final_article_text": final_text}
