import json
import logging
from typing import List, Tuple
from backend.app.schemas import CADSpecification, RetrievedChunk

logger = logging.getLogger(__name__)


class ContextBuilder:
    def __init__(self, token_budget: int = 4000):
        self.token_budget = token_budget

    def assemble(self, spec: CADSpecification, chunks: List[RetrievedChunk]) -> Tuple[str, List[str]]:
        """
        Assembles a concise, structured prompt context containing verified scripts,
        API specifications, and dimensional constraints.
        Returns (assembled_context_str, source_document_ids).
        """
        doc_ids = []
        sections = []

        # 1. Validated CAD Specification
        spec_summary = {
            "object_description": spec.object_description,
            "units": spec.units,
            "parameters": spec.parameters,
            "constraints": spec.constraints,
            "operations": spec.operations,
            "output_formats": spec.output_formats,
            "features": [f.model_dump() for f in spec.features],
        }
        sections.append("### VALIDATED CAD SPECIFICATION ###\n" + json.dumps(spec_summary, indent=2))

        # 2. Retrieved Official CAD Knowledge & Verified Scripts (Top 2, compact snippets)
        sections.append("### RETRIEVED CAD API REFERENCE & VERIFIED SCRIPTS ###")
        
        # Sort chunks to place verified scripts first
        sorted_chunks = sorted(
            chunks,
            key=lambda c: 0 if c.document_type == "verified_script" else 1,
        )

        char_budget = 1800
        used_chars = 0
        for chunk in sorted_chunks[:2]:
            doc_ids.append(chunk.document_id)
            title = chunk.metadata.get("title", chunk.document_id)
            source = chunk.source
            doc_type = chunk.document_type
            
            # Keep snippet concise to ensure fast local LLM prompt evaluation
            clean_content = chunk.content.strip()
            if len(clean_content) > 600:
                clean_content = clean_content[:600] + "\n... [truncated]"
            
            snippet = f"--- [{doc_type.upper()}] {title} (ID: {chunk.document_id}) ---\n"
            snippet += clean_content + "\n"
            
            if used_chars + len(snippet) < char_budget:
                sections.append(snippet)
                used_chars += len(snippet)

        # 3. Geometric Best Practices (Concise)
        sections.append("""### MODELING BEST PRACTICES ###
1. Hollow Cylinders: `inner_cyl = Part.makeCylinder(inner_radius, height - bottom_thickness + 1.0, FreeCAD.Vector(0,0,bottom_thickness))`
2. Verification: Verify `shape.isValid()` before adding to doc.
3. Export: Call `container.exportStep("model.step")` and `container.exportStl("model.stl")`.
""")

        assembled = "\n\n".join(sections)
        return assembled, doc_ids
        return assembled, doc_ids
