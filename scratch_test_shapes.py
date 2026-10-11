from backend.app.requirement_extractor import RequirementExtractor
from backend.app.code_generator import CADCodeGenerator
from backend.app.cad_executor import CADExecutor
from backend.app.llm_provider import MockProvider

prompts = [
    "Make a 50mm cube",
    "Create a solid cylinder with radius 20mm and height 80mm",
    "Create a 3D L-shaped hollow pipe with a smooth 90-degree curved bend connecting two straight sections. Make the pipe 100 mm long on each side, with an outer diameter of 20 mm and an inner diameter of 14 mm.",
    "Create a rectangular plate of 120 x 80 x 15 mm",
    "Create a hollow cylindrical container with outer radius 35 mm and height 90 mm",
]

prov = MockProvider()
extractor = RequirementExtractor(prov)
generator = CADCodeGenerator(prov)
executor = CADExecutor()

for i, p in enumerate(prompts):
    spec = extractor.extract(p)
    res = generator.generate(spec, "", [])
    mesh, desc, info = executor._build_geometry_mesh_from_script(res["script"])
    print(f"Test {i+1}: '{p[:50]}...'")
    print(f"  -> Features: {[f.feature_type for f in spec.features]}")
    print(f"  -> Params: {spec.parameters}")
    print(f"  -> Synthesized: {desc} (info type: {info.get('type')})")
    print()
