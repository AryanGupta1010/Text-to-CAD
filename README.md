# Text-to-CAD RAG Agent

A complete, modular, locally runnable Text-to-CAD system featuring:
- **Hybrid Retrieval**: Combines dense vector retrieval (ChromaDB) and lexical retrieval (BM25) with Reciprocal Rank Fusion (RRF) and custom composite reranking.
- **Dynamic LLM Provider Switching**: Seamless runtime switching between local models (via Ollama) and Cloud LLMs (via OpenAI/OpenRouter compatible APIs) without server restarts.
- **Isolated Python CAD Execution**: Executes generated scripts in isolated job directories with static AST safety verification and timeouts.
- **Geometry Kernel**: Runs with FreeCAD (`freecadcmd` / Open CASCADE) when installed, or via the integrated Open CASCADE compatible geometry engine fallback.
- **Physical Geometry & Dimensional Validation**: Verifies topological manifoldness, watertightness, solid counts, bounding dimensions, and internal cavity volume subtraction.
- **Self-Healing Error Repair Loop**: LangGraph state machine with automatic failure classification and error-specific targeted RAG retrieval for bounded script repair.
- **Interactive 3D Visualization**: Real-time Three.js WebGL viewer rendering the actual generated STL/GLB geometry, with camera controls, grid/axes helpers, and dimension inspection HUD.
- **Editable Code Panel**: Inspect and edit generated Python scripts, re-run them against the CAD engine, inspect STDOUT/STDERR logs, and download artifacts (.step, .stl, .FCStd, .py).

---

## 1. System Architecture

```
Natural-Language CAD Request
             │
             ▼
Requirement Extraction LLM
             │
             ▼
Pydantic Specification Validation
      /               \
[Ambiguous]        [Valid]
     │                │
Clarification     Query Construction
                      │
                      ▼
               Hybrid Retrieval
                /           \
           Dense Search     BM25
                \           /
                 Result Fusion (RRF)
                      │
                      ▼
               Composite Reranking
                      │
                      ▼
               Context Assembly
                      │
                      ▼
               Code Generation
                      │
                      ▼
              Static AST Checks
                      │
                      ▼
              Isolated Execution
                      │
                      ▼
             Geometry Validation
                /           \
             [Pass]       [Fail]
               │            │
               │      Error Classification & Targeted RAG
               │            │
               │      Bounded Repair (Max Retries)
               │            │
               ▼            ▼
             Artifact Generation
             (STEP, STL, GLB, FCStd)
                      │
                      ▼
          Interactive 3D Viewer & Downloads
```

---

## 2. Project Directory Structure

```
Text-To-CAD/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI application endpoints
│   │   ├── config.py                   # Pydantic v2 settings & runtime updates
│   │   ├── schemas.py                  # Pydantic data schemas
│   │   ├── state.py                    # Typed workflow state
│   │   ├── graph.py                    # LangGraph orchestration state machine
│   │   ├── llm_provider.py             # Ollama, Cloud API, and Mock adapters
│   │   ├── requirement_extractor.py    # Structured CAD specification extractor
│   │   ├── retriever.py                # Hybrid dense + BM25 retriever & RRF
│   │   ├── context_builder.py          # Prompt context assembly
│   │   ├── code_generator.py           # FreeCAD Python script generator
│   │   ├── cad_executor.py             # Isolated execution & geometry kernel
│   │   ├── geometry_validator.py       # Mesh analysis & dimensional validation
│   │   └── error_repair.py             # Error classification & targeted repair
│   ├── scripts/
│   │   └── ingest.py                   # Ingestion pipeline for ChromaDB & BM25
│   ├── knowledge_base/
│   │   ├── api_docs/                   # FreeCAD Part, Export, and OCCT docs
│   │   ├── verified_scripts/           # Verified primitives & boolean operations
│   │   ├── feature_patterns/           # Hollow shapes & modeling patterns
│   │   └── error_fixes/                # Boolean failure & API error guides
│   ├── tests/
│   │   ├── test_specification.py       # Unit tests for requirement extraction
│   │   ├── test_provider.py            # Unit tests for provider switching
│   │   ├── test_retrieval.py           # Unit tests for hybrid retrieval
│   │   ├── test_code_generation.py     # Static checks and code generator tests
│   │   ├── test_geometry_validation.py # Geometry & bounding volume tests
│   │   └── test_end_to_end.py          # End-to-end integration test
│   ├── artifacts/                      # Isolated job directories & outputs
│   ├── cli.py                          # Terminal demo runner
│   ├── requirements.txt                # Python backend dependencies
│   ├── .env.example                    # Environment template
│   └── .env                            # Active backend configuration
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ProviderSettings.jsx    # LLM provider switcher & connection test
│   │   │   ├── PromptPanel.jsx         # Prompt input & diagnostics panel
│   │   │   ├── CodeEditor.jsx          # Editable Python code & execution logs
│   │   │   ├── ModelViewer.jsx         # Three.js interactive 3D model viewer
│   │   │   └── ValidationPanel.jsx     # Geometry validation checks & downloads
│   │   ├── services/
│   │   │   └── api.js                  # Frontend API client
│   │   ├── App.jsx                     # 3-panel UI orchestrator
│   │   ├── index.css                   # Theme and component styles
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── README.md
└── .gitignore
```

---

## 3. Installation & Setup

### Prerequisites
- **Python**: 3.10+ (tested on Python 3.11.4)
- **Node.js**: 18+ (tested on Node v24.16.0)
- **Ollama** (optional, for local LLM inference): [ollama.com](https://ollama.com)
- **FreeCAD** (optional, for native FreeCAD command-line execution): [freecad.org](https://www.freecad.org)

### Step 1: Install Backend Dependencies
```bash
python -m pip install -r backend/requirements.txt
```

### Step 2: Ingest the CAD Knowledge Base
Populate the ChromaDB vector database and BM25 lexical index:
```bash
python backend/scripts/ingest.py
```
*Output: Generates `backend/knowledge_base/chroma_db/` containing document embeddings and `__bm25_index.json`.*

### Step 3: Install Frontend Dependencies
```bash
cd frontend
npm install
cd ..
```

---

## 4. LLM Provider Configuration

The application allows switching between **Local Ollama**, **Cloud API (OpenAI/OpenRouter)**, and **Deterministic Mock** directly in the UI or via `.env`.

### Setting up Ollama
Ensure Ollama is running, then pull the target model:
```bash
ollama serve
ollama pull qwen3:latest
```

### Setting up Cloud LLM
Configure `backend/.env` or enter credentials directly in the UI settings:
```ini
DEFAULT_LLM_PROVIDER=ollama
CLOUD_PROVIDER=openai
CLOUD_API_KEY=your_api_key_here
CLOUD_BASE_URL=https://api.openai.com/v1
CLOUD_MODEL=gpt-4o-mini
```

---

## 5. Running the Application

### Option A: Run Backend API Server
```bash
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```
API Documentation will be available at: `http://localhost:8000/docs`

### Option B: Run Frontend Development Server
In a separate terminal:
```bash
cd frontend
npm run dev
```
Open your browser at: `http://localhost:5173`

### Option C: Run Command-Line Demo
Run the complete end-to-end pipeline directly in the terminal:
```bash
# With local Ollama
python backend/cli.py --provider ollama

# With deterministic mock mode (for offline verification)
python backend/cli.py --mock
```

---

## 6. Running Tests

Run the full pytest suite covering specification extraction, provider switching, hybrid retrieval, AST static safety checks, geometry validation, and end-to-end integration:
```bash
python -m pytest backend/tests -v
```

---

## 7. Working Features vs Configuration Checklist

| Feature | Status | Notes |
|---|---|---|
| Natural Language Requirement Extraction |  Working | Pydantic validation, unit normalization to mm, dimensional constraint checking |
| Ambiguity Clarification Handling |  Working | Returns targeted clarification questions before code generation |
| ChromaDB Dense Vector Retrieval |  Working | Uses local `all-MiniLM-L6-v2` embeddings |
| BM25 Lexical Retrieval |  Working | Tokenizes code symbols, API methods, and documentation |
| Reciprocal Rank Fusion (RRF) & Reranking |  Working | Combines rankings with code-priority weighting |
| LLM Provider Switching |  Working | Runtime switching between Ollama, Cloud API, and Mock without restarting |
| Static AST Code Safety Verification |  Working | Blocks unsafe imports (`os`, `subprocess`, `socket`) |
| CAD Isolated Subprocess Execution |  Working | Unique job directory, timeouts, artifact scanning |
| Physical Geometry & Dimension Validator |  Working | Watertight manifold check, bounding dimensions, internal cavity subtraction |
| Self-Healing Bounded Repair Loop |  Working | Error classification, targeted error RAG retrieval, bounded retries |
| Three.js Interactive 3D Model Viewer |  Working | Orbit controls, grid/axes helpers, bounding dimension HUD |
| Editable Python Code Panel |  Working | In-place code editor, "Run CAD Script" button, execution logs |
| Artifact Export & Download |  Working | STEP (`.step`), STL (`.stl`), GLB (`.glb`), FCStd, and Python script |
| Native FreeCAD Binary Detection |  Working | Auto-detects `FreeCADCmd` / falls back to integrated geometry kernel |
