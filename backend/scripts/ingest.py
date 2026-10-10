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
    tokens = re.findall(r"[A-Za-z0-9_\.]+", text.lower())
    return [t for t in tokens if len(t) > 1]


def chunk_markdown_file(file_path: Path) -> List[Dict[str, Any]]:
    """Chunks a markdown file by sections/headers preserving context."""
    text = file_path.read_text(encoding="utf-8")
    rel_path = str(file_path.as_posix())
    
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


def load_jsonl_chunks(file_path: Path) -> List[Dict[str, Any]]:
    """Loads pre-chunked FreeCAD knowledge chunks from freecad_rag_chunks.jsonl."""
    results = []
    with open(file_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                text = item.get("text", "").strip()
                if not text or len(text) < 5:
                    continue

                doc_id = item.get("id") or f"jsonl_{idx}"
                name = item.get("name") or doc_id
                results.append({
                    "document_id": doc_id,
                    "title": f"FreeCAD API: {name}",
                    "content": text,
                    "document_type": item.get("type", "python_api"),
                    "cad_engine": "FreeCAD",
                    "api_version": item.get("freecad_version", "1.0.2"),
                    "operation": str(item.get("name") or ""),
                    "source": str(file_path.name),
                    "validation_status": "passed",
                    "language": "python",
                })
            except Exception as e:
                logger.debug(f"Failed to parse line {idx} in {file_path}: {e}")
    return results


class KnowledgeBaseIngestion:
    def __init__(
        self,
        kb_dir: str = "backend/knowledge_base",
        chroma_dir: str = "backend/knowledge_base/chroma_db",
        collection_name: str = "cad_knowledge_base",
        jsonl_path: Optional[str] = "freecad_rag_chunks.jsonl",
    ):
        self.kb_dir = Path(kb_dir)
        self.chroma_dir = Path(chroma_dir)
        self.collection_name = collection_name
        self.bm25_index_path = self.chroma_dir / "__bm25_index.json"
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None

    def run_ingestion(self) -> Dict[str, Any]:
        logger.info(f"Starting ingestion from {self.kb_dir}...")
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        
        all_chunks: List[Dict[str, Any]] = []
        skipped_files: List[str] = []
        failed_files: List[str] = []

        # 1. Ingest Knowledge Base Markdown and Python Scripts
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

        # 2. Ingest freecad_rag_chunks.jsonl if present
        jsonl_candidates = [
            self.jsonl_path,
            Path("freecad_rag_chunks.jsonl"),
            Path(__file__).resolve().parent.parent.parent / "freecad_rag_chunks.jsonl",
            self.kb_dir / "freecad_rag_chunks.jsonl",
        ]
        found_jsonl = next((p for p in jsonl_candidates if p and p.is_file()), None)

        if found_jsonl:
            logger.info(f"Found {found_jsonl}. Parsing JSONL API chunks...")
            jsonl_chunks = load_jsonl_chunks(found_jsonl)
            all_chunks.extend(jsonl_chunks)
            logger.info(f"Loaded {len(jsonl_chunks)} chunks from {found_jsonl}.")

        logger.info(f"Total discovered chunks: {len(all_chunks)}.")

        # Deduplicate chunks by document_id
        unique_chunks_map = {c["document_id"]: c for c in all_chunks}
        unique_chunks = list(unique_chunks_map.values())
        logger.info(f"Unique chunks to index: {len(unique_chunks)}.")

        # 3. Ingest into ChromaDB in batches
        client = chromadb.PersistentClient(path=str(self.chroma_dir))
        collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Text-to-CAD Knowledge Base and FreeCAD API Reference"}
        )

        batch_size = 500
        total_batches = (len(unique_chunks) + batch_size - 1) // batch_size
        
        for b_idx in range(total_batches):
            batch = unique_chunks[b_idx * batch_size : (b_idx + 1) * batch_size]
            ids = [c["document_id"] for c in batch]
            documents = [c["content"] for c in batch]
            metadatas = [
                {
                    "title": str(c["title"])[:250],
                    "document_type": str(c["document_type"])[:50],
                    "cad_engine": str(c["cad_engine"])[:50],
                    "api_version": str(c["api_version"])[:50],
                    "operation": str(c.get("operation") or "")[:100],
                    "source": str(c["source"])[:250],
                    "validation_status": str(c["validation_status"])[:50],
                    "language": str(c["language"])[:50],
                    "document_id": str(c["document_id"])[:100],
                }
                for c in batch
            ]

            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"Upserted batch {b_idx + 1}/{total_batches} ({len(ids)} chunks) into ChromaDB.")

        # 4. Build BM25 Index
        logger.info("Building BM25 lexical index...")
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
            json.dump(bm25_data, f)
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
