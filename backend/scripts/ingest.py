import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from rank_bm25 import BM25Okapi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest")


def compute_doc_id(source: str, content: str) -> str:
    """Generates a stable, reproducible document ID."""
    hasher = hashlib.sha256()
    hasher.update(source.encode("utf-8"))
    hasher.update(b"::")
    hasher.update(content.strip().encode("utf-8"))
    return f"doc_{hasher.hexdigest()[:16]}"


def tokenize_code_and_text(text: str) -> List[str]:
    """Tokenizes text preserving code symbols, camelCase, snake_case, and dots."""
    # Split on whitespace and certain delimiters but retain dots and underscores in identifiers
    tokens = re.findall(r"[A-Za-z0-9_\.]+", text.lower())
    return [t for t in tokens if len(t) > 1]


def chunk_markdown_file(file_path: Path) -> List[Dict[str, Any]]:
    """Chunks a markdown file by sections/headers preserving context."""
    text = file_path.read_text(encoding="utf-8")
    rel_path = str(file_path.as_posix())
    
    # Split by level 1, 2, or 3 markdown headers
    sections = re.split(r"(^#{1,3}\s+.*$)", text, flags=re.MULTILINE)
    
    chunks = []
    current_title = file_path.stem.replace("_", " ").title()
    current_content = ""
    
    for part in sections:
        part = part.strip()
        if not part:
            continue
        if part.startswith("#"):
            if current_content:
                chunks.append({
                    "title": current_title,
                    "content": current_content.strip(),
                    "source": rel_path,
                })
            current_title = part.lstrip("#").strip()
            current_content = part + "\n\n"
        else:
            current_content += part + "\n\n"
            
    if current_content:
        chunks.append({
            "title": current_title,
            "content": current_content.strip(),
            "source": rel_path,
        })
        
    results = []
    for c in chunks:
        # Determine category from folder
        doc_type = "api_docs"
        if "feature_patterns" in rel_path:
            doc_type = "feature_pattern"
        elif "error_fixes" in rel_path:
            doc_type = "error_fix"
            
        doc_id = compute_doc_id(rel_path, c["content"])
        results.append({
            "document_id": doc_id,
            "title": c["title"],
            "content": c["content"],
            "document_type": doc_type,
            "cad_engine": "FreeCAD",
            "api_version": "1.0/1.1",
            "operation": c["title"].lower(),
            "source": rel_path,
            "validation_status": "passed",
            "language": "markdown",
        })
    return results


def chunk_python_script(file_path: Path) -> List[Dict[str, Any]]:
    """Chunks a verified Python script preserving complete functions and headers."""
    content = file_path.read_text(encoding="utf-8")
    rel_path = str(file_path.as_posix())
    
    # Determine operation from folder / filename
    operation = file_path.stem
    doc_id = compute_doc_id(rel_path, content)
    
    return [{
        "document_id": doc_id,
        "title": f"Verified Script: {file_path.stem.replace('_', ' ').title()}",
        "content": content.strip(),
        "document_type": "verified_script",
        "cad_engine": "FreeCAD",
        "api_version": "1.0/1.1",
        "operation": operation,
        "source": rel_path,
        "validation_status": "passed",
        "language": "python",
    }]


class KnowledgeBaseIngestion:
    def __init__(
        self,
        kb_dir: str = "backend/knowledge_base",
        chroma_dir: str = "backend/knowledge_base/chroma_db",
        collection_name: str = "cad_knowledge_base",
    ):
        self.kb_dir = Path(kb_dir)
        self.chroma_dir = Path(chroma_dir)
        self.collection_name = collection_name
        self.bm25_index_path = self.chroma_dir / "__bm25_index.json"

    def run_ingestion(self) -> Dict[str, Any]:
        logger.info(f"Starting ingestion from {self.kb_dir}...")
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        
        all_chunks: List[Dict[str, Any]] = []
        skipped_files: List[str] = []
        failed_files: List[str] = []

        # Find all .md and .py files
        for root, _, files in os.walk(self.kb_dir):
            if "chroma_db" in root:
                continue
            for f in files:
                f_path = Path(root) / f
                if f.endswith(".md"):
                    try:
                        chunks = chunk_markdown_file(f_path)
                        all_chunks.extend(chunks)
                    except Exception as e:
                        logger.error(f"Failed to chunk markdown {f_path}: {e}")
                        failed_files.append(str(f_path))
                elif f.endswith(".py"):
                    try:
                        chunks = chunk_python_script(f_path)
                        all_chunks.extend(chunks)
                    except Exception as e:
                        logger.error(f"Failed to chunk python script {f_path}: {e}")
                        failed_files.append(str(f_path))
                else:
                    skipped_files.append(str(f_path))

        logger.info(f"Discovered {len(all_chunks)} chunks across documentation and verified scripts.")

        # Deduplicate chunks by document_id
        unique_chunks_map = {c["document_id"]: c for c in all_chunks}
        unique_chunks = list(unique_chunks_map.values())

        # Ingest into ChromaDB
        client = chromadb.PersistentClient(path=str(self.chroma_dir))
        collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Text-to-CAD Knowledge Base and FreeCAD API Reference"}
        )

        ids = [c["document_id"] for c in unique_chunks]
        documents = [c["content"] for c in unique_chunks]
        metadatas = [
            {
                "title": c["title"],
                "document_type": c["document_type"],
                "cad_engine": c["cad_engine"],
                "api_version": c["api_version"],
                "operation": str(c.get("operation") or ""),
                "source": c["source"],
                "validation_status": c["validation_status"],
                "language": c["language"],
                "document_id": c["document_id"],
            }
            for c in unique_chunks
        ]

        if ids:
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"Successfully upserted {len(ids)} documents into ChromaDB collection '{self.collection_name}'.")

        # Build BM25 Index
        corpus = [tokenize_code_and_text(c["content"]) for c in unique_chunks]
        bm25_data = {
            "metadata": {
                "total_documents": len(unique_chunks),
                "collection_name": self.collection_name,
            },
            "documents": unique_chunks,
            "tokenized_corpus": corpus,
        }
        
        with open(self.bm25_index_path, "w", encoding="utf-8") as f:
            json.dump(bm25_data, f, indent=2)
        logger.info(f"Successfully saved BM25 index to {self.bm25_index_path}.")

        summary = {
            "total_chunks_ingested": len(unique_chunks),
            "chroma_collection": self.collection_name,
            "skipped_files_count": len(skipped_files),
            "failed_files_count": len(failed_files),
            "status": "success",
        }
        return summary


if __name__ == "__main__":
    ingestor = KnowledgeBaseIngestion()
    res = ingestor.run_ingestion()
    print("Ingestion Summary:", json.dumps(res, indent=2))
