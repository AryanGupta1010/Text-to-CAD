import pytest
from backend.app.schemas import CADSpecification
from backend.app.retriever import HybridCADRetriever
from backend.app.context_builder import ContextBuilder


def test_hybrid_retriever_query_construction():
    retriever = HybridCADRetriever()
    spec = CADSpecification(
        object_description="Hollow cylindrical container with closed bottom",
        parameters={"outer_radius": 30.0, "height": 100.0, "wall_thickness": 3.0, "bottom_thickness": 4.0},
        operations=["create_outer_cylinder", "create_inner_cylinder", "boolean_cut"],
        output_formats=["STEP", "STL"],
    )
    queries = retriever.construct_queries(spec)
    assert len(queries) > 0
    assert any("cylinder" in q.lower() for q in queries)
    assert any("cut" in q.lower() or "boolean" in q.lower() for q in queries)


def test_hybrid_retrieval_returns_candidates():
    retriever = HybridCADRetriever()
    spec = CADSpecification(
        object_description="Hollow cylinder container",
        parameters={"outer_radius": 30.0, "height": 100.0},
        operations=["cut", "cylinder"],
    )
    chunks, diag = retriever.retrieve(spec)
    assert len(chunks) > 0
    assert diag.insufficient_evidence is False
    assert diag.dense_results_count > 0
    assert diag.bm25_results_count > 0
    # Top chunk should be a verified script or pattern
    assert any(c.document_type in ["verified_script", "feature_pattern"] for c in chunks)


def test_context_builder_assembly():
    retriever = HybridCADRetriever()
    spec = CADSpecification(
        object_description="Hollow cylinder",
        parameters={"outer_radius": 30.0, "height": 100.0},
        operations=["boolean_cut"],
    )
    chunks, _ = retriever.retrieve(spec)
    builder = ContextBuilder()
    context_str, doc_ids = builder.assemble(spec, chunks)

    assert "VALIDATED CAD SPECIFICATION" in context_str
    assert "RETRIEVED CAD API REFERENCE" in context_str
    assert len(doc_ids) > 0
