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
        
        # Filter out conflicting verified scripts (e.g. don't feed hollow container script when building a box or L-pipe)
        feature_types = [f.feature_type.lower() for f in spec.features]
        desc = spec.object_description.lower()
        is_l_pipe = "l_shaped_pipe" in feature_types or any("bend" in f or "pipe" in f for f in feature_types) or "bend" in desc or "elbow" in desc
        is_box = any(f in ["box", "cube", "plate", "prism"] for f in feature_types) or any(k in desc for k in ["box", "cube", "plate", "block"])
        is_sphere = "sphere" in feature_types or "sphere" in desc or "spherical" in desc
        is_container = "container" in desc or ("wall_thickness" in spec.parameters and "bottom_thickness" in spec.parameters)

        def is_relevant_chunk(c: RetrievedChunk) -> bool:
            c_text = (c.content + " " + c.metadata.get("title", "")).lower()
            if (is_box or is_l_pipe or is_sphere) and not is_container:
                if "hollow_container" in c_text or "closed bottom" in c_text:
                    return False
            return True

        relevant_chunks = [c for c in chunks if is_relevant_chunk(c)]
        if not relevant_chunks:
            relevant_chunks = chunks

        # Sort chunks to place verified scripts first
        sorted_chunks = sorted(
            relevant_chunks,
            key=lambda c: 0 if c.document_type == "verified_script" else 1,
        )

        char_budget = 1800
        used_chars = 0
        for chunk in sorted_chunks[:2]:
            doc_ids.append(chunk.document_id)
            title = chunk.metadata.get("title", chunk.document_id)
            source = chunk.source
            doc_type = chunk.document_type
            
            clean_content = chunk.content.strip()
            if len(clean_content) > 600:
                clean_content = clean_content[:600] + "\n... [truncated]"
            
            snippet = f"--- [{doc_type.upper()}] {title} (ID: {chunk.document_id}) ---\n"
            snippet += clean_content + "\n"
            
            if used_chars + len(snippet) < char_budget:
                sections.append(snippet)
                used_chars += len(snippet)

        # 3. Shape-Targeted Geometric Best Practices
        if is_l_pipe:
            practices = """### MODELING BEST PRACTICES (SWEPT / L-SHAPED HOLLOW PIPE) ###
1. Trajectory wire in XZ plane: `path_wire = Part.Wire([line1, arc, line2])`
2. Cross-section circular faces:
   `outer_face = Part.Face(Part.Wire([Part.makeCircle(outer_radius, p0, FreeCAD.Vector(0,0,1))]))`
   `inner_face = Part.Face(Part.Wire([Part.makeCircle(inner_radius, p0, FreeCAD.Vector(0,0,1))]))`
3. Sweeps & Boolean subtraction:
   `outer_pipe = outer_face.makePipe(path_wire)`
   `inner_pipe = inner_face.makePipe(path_wire)`
   `pipe = outer_pipe.cut(inner_pipe)`
4. Verification: Check `shape.isValid()` before export.
5. Export: Call `shape.exportStep("model.step")` and `shape.exportStl("model.stl")`."""
        elif is_box:
            practices = """### MODELING BEST PRACTICES (BOX / CUBE / PLATE / ENCLOSURE) ###
1. Solid Box: `box = Part.makeBox(length, width, height)`
2. Ensure `length`, `width`, `height` variables are explicitly assigned numbers matching specification.
3. Verification: Check `box.isValid()` before export.
4. Export: Call `box.exportStep("model.step")` and `box.exportStl("model.stl")`."""
        elif is_sphere:
            practices = """### MODELING BEST PRACTICES (SPHERE) ###
1. Solid Sphere: `sphere = Part.makeSphere(radius)`
2. Verification: Check `sphere.isValid()` before export.
3. Export: Call `sphere.exportStep("model.step")` and `sphere.exportStl("model.stl")`."""
        elif is_container:
            practices = """### MODELING BEST PRACTICES (HOLLOW CONTAINER) ###
1. Outer Shell: `outer_cyl = Part.makeCylinder(outer_radius, height)`
2. Inner Pocket: `inner_cyl = Part.makeCylinder(inner_radius, height - bottom_thickness + 1.0, FreeCAD.Vector(0,0,bottom_thickness))`
3. Boolean Cut: `container = outer_cyl.cut(inner_cyl)`
4. Verification: Check `container.isValid()` before export.
5. Export: Call `container.exportStep("model.step")` and `container.exportStl("model.stl")`."""
        else:
            practices = """### MODELING BEST PRACTICES ###
1. Primitives: Use `Part.makeBox(l, w, h)`, `Part.makeCylinder(r, h)`, or `Part.makeSphere(r)`.
2. Verification: Check `shape.isValid()` before adding to document.
3. Export: Call `shape.exportStep("model.step")` and `shape.exportStl("model.stl")`."""

        sections.append(practices)
        assembled = "\n\n".join(sections)
        return assembled, doc_ids
