import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import chromadb
from rank_bm25 import BM25Okapi

from backend.app.config import Settings, get_settings
from backend.app.schemas import (
    CADSpecification,
    RetrievedChunk,
    RetrievalDiagnostics,
)
from backend.scripts.ingest import tokenize_code_and_text

logger = logging.getLogger(__name__)


class HybridCADRetriever:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.chroma_dir = Path(self.settings.chroma_persist_directory)
        self.collection_name = self.settings.chroma_collection_name
        self.bm25_index_path = self.chroma_dir / "__bm25_index.json"
        
        self.chroma_client = None
        self.chroma_collection = None
        self.bm25_index: Optional[BM25Okapi] = None
        self.bm25_docs: List[Dict[str, Any]] = []
        
        self._init_stores()

    def _init_stores(self):
        """Initializes ChromaDB persistent client and BM25 index."""
        try:
            if self.chroma_dir.exists():
                self.chroma_client = chromadb.PersistentClient(path=str(self.chroma_dir))
                self.chroma_collection = self.chroma_client.get_or_create_collection(name=self.collection_name)
        except Exception as e:
            logger.warning(f"Could not initialize ChromaDB client: {e}")

        try:
            if self.bm25_index_path.exists():
                with open(self.bm25_index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.bm25_docs = data.get("documents", [])
                tokenized_corpus = data.get("tokenized_corpus", [])
                if tokenized_corpus:
                    self.bm25_index = BM25Okapi(tokenized_corpus)
        except Exception as e:
            logger.warning(f"Could not initialize BM25 index: {e}")

    def construct_queries(self, spec: CADSpecification) -> List[str]:
        """Stage A: Derives focused retrieval queries from CAD specification."""
        queries = []
        
        # 1. Primary shape & description
        queries.append(f"FreeCAD {spec.object_description}")

        # 2. Operations & CAD functions
        ops = " ".join(spec.operations) if spec.operations else "cylinder cut boolean"
        queries.append(f"FreeCAD Part module {ops}")

        # 3. Features & geometry constraints
        for feat in spec.features[:2]:
            queries.append(f"FreeCAD Part.make{feat.feature_type.capitalize()} parameters constraints")

        # 4. Verified scripts & boolean combinations
        if "cut" in ops.lower() or "pocket" in spec.object_description.lower() or "hollow" in spec.object_description.lower():
            queries.append("FreeCAD hollow container cylinder coaxial cut closed bottom")
            queries.append("FreeCAD Part.makeCylinder and Shape.cut examples")

        # 5. Export formats
        if spec.output_formats:
            queries.append(f"FreeCAD export {' '.join(spec.output_formats)} Part.export")

        # Deduplicate queries preserving order
        unique_queries = []
        for q in queries:
            if q not in unique_queries:
                unique_queries.append(q)
        return unique_queries

    def dense_search(self, query: str, top_k: int = 15, where_filter: Optional[dict] = None) -> List[RetrievedChunk]:
        """Stage B: Dense semantic retrieval via ChromaDB."""
        if not self.chroma_collection:
            return []

        try:
            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where_filter,
            )
            chunks = []
            if results and results["ids"] and results["ids"][0]:
                for idx, doc_id in enumerate(results["ids"][0]):
                    content = results["documents"][0][idx]
                    metadata = results["metadatas"][0][idx] if results["metadatas"] else {}
                    distance = results["distances"][0][idx] if "distances" in results and results["distances"] else 0.5
                    # Convert distance to similarity score
                    score = 1.0 / (1.0 + distance)
                    chunks.append(RetrievedChunk(
                        document_id=doc_id,
                        content=content,
                        document_type=metadata.get("document_type", "unknown"),
                        cad_engine=metadata.get("cad_engine", "FreeCAD"),
                        operation=metadata.get("operation"),
                        source=metadata.get("source", ""),
                        score=score,
                        dense_rank=idx + 1,
                        metadata=metadata,
                    ))
            return chunks
        except Exception as e:
            logger.error(f"ChromaDB search failed for query '{query}': {e}")
            return []

    def bm25_search(self, query: str, top_k: int = 15) -> List[RetrievedChunk]:
        """Stage C: BM25 lexical retrieval."""
        if not self.bm25_index or not self.bm25_docs:
            return []

        tokenized_query = tokenize_code_and_text(query)
        if not tokenized_query:
            return []

        scores = self.bm25_index.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        chunks = []
        rank = 1
        for i in top_indices:
            score = float(scores[i])
            if score <= 0.0:
                continue
            doc = self.bm25_docs[i]
            chunks.append(RetrievedChunk(
                document_id=doc["document_id"],
                content=doc["content"],
                document_type=doc.get("document_type", "unknown"),
                cad_engine=doc.get("cad_engine", "FreeCAD"),
                operation=doc.get("operation"),
                source=doc.get("source", ""),
                score=score,
                bm25_rank=rank,
                metadata=doc,
            ))
            rank += 1
        return chunks

    def fuse_and_rerank(
        self,
        dense_results: List[RetrievedChunk],
        bm25_results: List[RetrievedChunk],
        query: str,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        """Stages E & F: Reciprocal Rank Fusion (RRF) and composite reranking."""
        rrf_constant = 60
        candidates: Dict[str, RetrievedChunk] = {}
        rrf_scores: Dict[str, float] = {}

        # Aggregate dense ranks
        for chunk in dense_results:
            candidates[chunk.document_id] = chunk
            rank = chunk.dense_rank or 50
            rrf_scores[chunk.document_id] = rrf_scores.get(chunk.document_id, 0.0) + (1.0 / (rrf_constant + rank))

        # Aggregate BM25 ranks
        for chunk in bm25_results:
            if chunk.document_id in candidates:
                cand = candidates[chunk.document_id]
                cand.bm25_rank = chunk.bm25_rank
            else:
                candidates[chunk.document_id] = chunk
            rank = chunk.bm25_rank or 50
            rrf_scores[chunk.document_id] = rrf_scores.get(chunk.document_id, 0.0) + (1.0 / (rrf_constant + rank))

        # Rerank candidates: composite weighting with code preference & lexical match bonus
        q_tokens = set(tokenize_code_and_text(query))
        
        for doc_id, chunk in candidates.items():
            base_rrf = rrf_scores.get(doc_id, 0.0)
            chunk.fused_score = base_rrf
            
            # Bonus for verified_script and high match density
            type_bonus = 1.3 if chunk.document_type == "verified_script" else 1.0
            
            # Content lexical overlap
            content_tokens = set(tokenize_code_and_text(chunk.content))
            overlap = len(q_tokens.intersection(content_tokens)) / max(1, len(q_tokens))
            
            rerank_score = (base_rrf * 100.0) * type_bonus + (overlap * 2.0)
            chunk.rerank_score = round(rerank_score, 4)

        ranked = sorted(candidates.values(), key=lambda c: c.rerank_score or 0.0, reverse=True)
        return ranked[:top_k]

    def retrieve(self, spec: CADSpecification) -> Tuple[List[RetrievedChunk], RetrievalDiagnostics]:
        """Runs the complete hybrid retrieval pipeline."""
        queries = self.construct_queries(spec)
        all_dense: List[RetrievedChunk] = []
        all_bm25: List[RetrievedChunk] = []
        
        seen_dense_ids: Set[str] = set()
        seen_bm25_ids: Set[str] = set()

        for q in queries:
            d_res = self.dense_search(q, top_k=self.settings.dense_top_k)
            for c in d_res:
                if c.document_id not in seen_dense_ids:
                    seen_dense_ids.add(c.document_id)
                    all_dense.append(c)

            b_res = self.bm25_search(q, top_k=self.settings.bm25_top_k)
            for c in b_res:
                if c.document_id not in seen_bm25_ids:
                    seen_bm25_ids.add(c.document_id)
                    all_bm25.append(c)

        # Fuse and rerank using the primary combined query
        combined_q = f"FreeCAD {spec.object_description} {' '.join(spec.operations)}"
        top_candidates = self.fuse_and_rerank(
            all_dense,
            all_bm25,
            query=combined_q,
            top_k=self.settings.rerank_top_k,
        )

        insufficient = len(top_candidates) == 0

        diagnostics = RetrievalDiagnostics(
            queries=queries,
            dense_results_count=len(all_dense),
            bm25_results_count=len(all_bm25),
            fused_count=len(seen_dense_ids.union(seen_bm25_ids)),
            selected_documents=top_candidates,
            insufficient_evidence=insufficient,
            notes=[
                f"Generated {len(queries)} focused queries from structured specification.",
                f"Combined {len(all_dense)} dense semantic and {len(all_bm25)} BM25 lexical candidates via RRF.",
                f"Reranked top {len(top_candidates)} documents prioritizing verified scripts and exact API signatures.",
            ],
        )

        return top_candidates, diagnostics
