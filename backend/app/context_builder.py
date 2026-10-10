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

        # 2. Retrieved Official CAD Knowledge & Verified Scripts
        sections.append("### RETRIEVED CAD API REFERENCE & VERIFIED SCRIPTS ###")
        
        # Sort chunks to place verified scripts first
        sorted_chunks = sorted(
            chunks,
            key=lambda c: 0 if c.document_type == "verified_script" else 1,
        )

        for chunk in sorted_chunks:
            doc_ids.append(chunk.document_id)
            title = chunk.metadata.get("title", chunk.document_id)
            source = chunk.source
            doc_type = chunk.document_type
            
            snippet = f"--- [{doc_type.upper()}] {title} (Source: {source}, ID: {chunk.document_id}) ---\n"
            snippet += chunk.content.strip() + "\n"
            sections.append(snippet)

        # 3. Geometric Edge Cases & Best Practices
        sections.append("""### MODELING BEST PRACTICES & KERNEL CONSTRAINTS ###
1. Clean Face Subtraction: When cutting an open-top container, extend the cutting cylinder height by +1.0 mm beyond the top face, and translate it by bottom_thickness along Z:
   `inner_cyl = Part.makeCylinder(inner_radius, height - bottom_thickness + 1.0, FreeCAD.Vector(0, 0, bottom_thickness), FreeCAD.Vector(0, 0, 1))`
2. Verification: Check `shape.isValid()` and `not shape.isNull()` before adding to document.
3. Export: If output formats include STEP and STL, call:
   `container.exportStep("model.step")`
   `container.exportStl("model.stl")`
   `doc.saveAs("model.FCStd")`
4. Parameters: Define variables at top of function matching specification parameters.
""")

        assembled = "\n\n".join(sections)
        return assembled, doc_ids
