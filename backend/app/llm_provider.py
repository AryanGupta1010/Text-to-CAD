import abc
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
import httpx

from backend.app.config import Settings, get_settings
from backend.app.schemas import ProviderTestResponse

logger = logging.getLogger(__name__)


def clean_llm_output(text: str) -> str:
    """Strips thinking tags (<think>...</think>) and markdown backticks if present."""
    # Remove thinking tags
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    return text


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Robustly extracts JSON from an LLM response even if surrounded by markdown or preamble."""
    cleaned = clean_llm_output(text)
    
    # Try direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass
        
    # Try finding markdown ```json ... ``` block
    json_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if json_block:
        try:
            return json.loads(json_block.group(1).strip())
        except Exception:
            pass
            
    # Try finding outermost { ... }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = cleaned[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
            
    raise ValueError(f"Could not extract valid JSON from LLM output. Content snippet: {cleaned[:200]}")


def extract_python_code(text: str) -> str:
    """Extracts python code from markdown code blocks or clean text."""
    cleaned = clean_llm_output(text)
    
    # Check for ```python ... ```
    match = re.search(r"```python\s*([\s\S]*?)\s*```", cleaned)
    if match:
        return match.group(1).strip()
        
    # Check for general ``` ... ```
    match = re.search(r"```\s*([\s\S]*?)\s*```", cleaned)
    if match:
        return match.group(1).strip()
        
    return cleaned.strip()


class BaseLLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        """Generates a text completion given prompt and system instructions."""
        pass

    @abc.abstractmethod
    def test_connection(self) -> ProviderTestResponse:
        """Tests connectivity and reports capabilities."""
        pass

    @abc.abstractmethod
    def get_model_name(self) -> str:
        pass

    @abc.abstractmethod
    def get_provider_type(self) -> str:
        pass


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str, model_name: str):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    def get_provider_type(self) -> str:
        return "ollama"

    def get_model_name(self) -> str:
        return self.model_name

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        url = f"{self.base_url}/api/chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if json_mode:
            payload["format"] = "json"

        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                return clean_llm_output(content)
        except httpx.ConnectError:
            raise ConnectionError(f"Failed to connect to Ollama at {self.base_url}. Ensure Ollama is running.")
        except Exception as e:
            logger.error(f"Ollama generation failed: {str(e)}")
            raise RuntimeError(f"Ollama generation error: {str(e)}")

    def test_connection(self) -> ProviderTestResponse:
        t0 = time.time()
        url = f"{self.base_url}/api/tags"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                latency = round((time.time() - t0) * 1000, 2)
                
                # Check if configured model exists
                model_found = any(self.model_name in m for m in models)
                msg = f"Connected to Ollama. Configured model '{self.model_name}' "
                msg += "is ready." if model_found else f"NOT found in installed models: {models}."
                
                return ProviderTestResponse(
                    success=model_found,
                    provider="ollama",
                    model=self.model_name,
                    message=msg,
                    latency_ms=latency,
                    capabilities=["local_inference", "chat", "json_format"] if model_found else ["local_inference"],
                )
        except Exception as e:
            return ProviderTestResponse(
                success=False,
                provider="ollama",
                model=self.model_name,
                message=f"Could not connect to Ollama at {self.base_url}: {str(e)}",
                latency_ms=round((time.time() - t0) * 1000, 2),
                capabilities=[],
            )


class CloudProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str], base_url: str, model_name: str, provider_name: str = "openai"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.provider_name = provider_name

    def get_provider_type(self) -> str:
        return "cloud"

    def get_model_name(self) -> str:
        return self.model_name

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        if not self.api_key:
            raise ValueError("Cloud API key is not configured. Please supply an API key in Settings.")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return clean_llm_output(content)
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text
            # Never leak full auth keys in logs
            raise RuntimeError(f"Cloud LLM API error ({e.response.status_code}): {error_detail}")
        except Exception as e:
            raise RuntimeError(f"Cloud LLM request failed: {str(e)}")

    def test_connection(self) -> ProviderTestResponse:
        t0 = time.time()
        if not self.api_key:
            return ProviderTestResponse(
                success=False,
                provider="cloud",
                model=self.model_name,
                message="Cloud API key is missing. Enter a valid API key.",
                latency_ms=0,
                capabilities=[],
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                latency = round((time.time() - t0) * 1000, 2)
                if resp.status_code == 200:
                    return ProviderTestResponse(
                        success=True,
                        provider="cloud",
                        model=self.model_name,
                        message=f"Cloud provider connection verified successfully with model '{self.model_name}'.",
                        latency_ms=latency,
                        capabilities=["chat", "cloud_api", "json_mode"],
                    )
                else:
                    return ProviderTestResponse(
                        success=False,
                        provider="cloud",
                        model=self.model_name,
                        message=f"Cloud API returned error {resp.status_code}: {resp.text[:200]}",
                        latency_ms=latency,
                    )
        except Exception as e:
            return ProviderTestResponse(
                success=False,
                provider="cloud",
                model=self.model_name,
                message=f"Cloud connection failed: {str(e)}",
                latency_ms=round((time.time() - t0) * 1000, 2),
            )


class MockProvider(BaseLLMProvider):
    """Deterministic mock provider for offline testing and verification."""
    def __init__(self, model_name: str = "mock-qwen-cad"):
        self.model_name = model_name

    def get_provider_type(self) -> str:
        return "mock"

    def get_model_name(self) -> str:
        return self.model_name

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        lower_prompt = prompt.lower()

        # Code generation prompt takes precedence if explicitly asked for code / script
        if "generate the freecad python script" in lower_prompt or "generate the python script" in lower_prompt or "failed script" in lower_prompt:
            script = """import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    
    # Outer cylinder
    outer_radius = 30.0
    height = 100.0
    wall_thickness = 3.0
    bottom_thickness = 4.0
    inner_radius = outer_radius - wall_thickness
    
    outer_cyl = Part.makeCylinder(outer_radius, height)
    
    # Inner cylinder for hollow pocket with 1mm safety extension for clean top cut
    inner_cyl = Part.makeCylinder(inner_radius, height - bottom_thickness + 1.0)
    inner_cyl.translate(FreeCAD.Vector(0, 0, bottom_thickness))
    
    # Boolean cut
    container = outer_cyl.cut(inner_cyl)
    
    # Validate shape
    if not container.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "CylindricalContainer")
    shape_obj.Shape = container
    doc.recompute()

    # Exports
    container.exportStep("model.step")
    container.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
            return f"```python\n{script}\n```"
        
        # Requirement extraction prompt handling
        if json_mode or "cad specification" in lower_prompt or "extract requirements" in lower_prompt or "clarification" in lower_prompt:
            # Check for container specs
            outer_r = 30.0
            height = 100.0
            wall_t = 3.0
            bot_t = 4.0
            
            # Simple regex search for custom dimensions if mentioned
            r_match = re.search(r"outer\s*radius\s*(?:of)?\s*(\d+(?:\.\d+)?)", lower_prompt)
            if r_match:
                outer_r = float(r_match.group(1))
            h_match = re.search(r"height\s*(?:of)?\s*(\d+(?:\.\d+)?)", lower_prompt)
            if h_match:
                height = float(h_match.group(1))
            w_match = re.search(r"wall\s*thickness\s*(?:of)?\s*(\d+(?:\.\d+)?)", lower_prompt)
            if w_match:
                wall_t = float(w_match.group(1))
            b_match = re.search(r"bottom\s*thickness\s*(?:of)?\s*(\d+(?:\.\d+)?)", lower_prompt)
            if b_match:
                bot_t = float(b_match.group(1))
                
            inner_r = max(1.0, outer_r - wall_t)
            inner_h = max(1.0, height - bot_t)
            
            # Extract user request from extraction prompt if formatted as Request: "..."
            req_match = re.search(r'request:\s*["\']?(.*?)["\']?\s*\n', lower_prompt)
            req_text = req_match.group(1) if req_match else lower_prompt

            clarification = False
            questions = []
            if not ("radius" in req_text or "diameter" in req_text or "height" in req_text or "thickness" in req_text):
                clarification = True
                questions = ["Please specify the outer radius, container height, and wall thickness."]

            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": "Hollow cylindrical container with closed bottom and open top",
                "features": [
                    {
                        "feature_type": "cylinder",
                        "dimensions": {"radius": outer_r, "height": height},
                        "parameters": {"outer_cylinder": True},
                        "geometric_constraints": ["concentric"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    },
                    {
                        "feature_type": "cylinder_pocket",
                        "dimensions": {"radius": inner_r, "height": inner_h, "z_offset": bot_t},
                        "parameters": {"inner_cylinder": True},
                        "geometric_constraints": ["concentric", "coaxial"],
                        "dependencies": ["cylinder"],
                        "expected_properties": {"subtraction": True}
                    }
                ],
                "parameters": {
                    "outer_radius": outer_r,
                    "height": height,
                    "wall_thickness": wall_t,
                    "bottom_thickness": bot_t,
                    "inner_radius": inner_r
                },
                "constraints": ["concentric", "closed_bottom", "open_top"],
                "operations": ["create_outer_cylinder", "create_inner_cylinder", "translate_inner_cylinder", "boolean_cut"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Z-axis alignment", "Cylindrical symmetry"],
                "clarification_required": clarification,
                "clarification_questions": questions
            }
            return json.dumps(spec, indent=2)

        # Code generation prompt
        script = f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    
    # Outer cylinder
    outer_radius = 30.0
    height = 100.0
    wall_thickness = 3.0
    bottom_thickness = 4.0
    inner_radius = outer_radius - wall_thickness
    
    outer_cyl = Part.makeCylinder(outer_radius, height)
    
    # Inner cylinder for hollow pocket
    inner_cyl = Part.makeCylinder(inner_radius, height)
    inner_cyl.translate(FreeCAD.Vector(0, 0, bottom_thickness))
    
    # Boolean cut
    container = outer_cyl.cut(inner_cyl)
    
    # Validate shape
    if not container.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "CylindricalContainer")
    shape_obj.Shape = container
    doc.recompute()
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        return f"```python\n{script}\n```"

    def test_connection(self) -> ProviderTestResponse:
        return ProviderTestResponse(
            success=True,
            provider="mock",
            model=self.model_name,
            message="Mock provider is available for offline deterministic testing.",
            latency_ms=1.0,
            capabilities=["deterministic_mock", "offline"],
        )


class ProviderFactory:
    @staticmethod
    def get_provider(
        provider_type: Optional[str] = None,
        settings: Optional[Settings] = None,
    ) -> BaseLLMProvider:
        cfg = settings or get_settings()
        chosen = provider_type or cfg.default_llm_provider

        if chosen == "ollama":
            return OllamaProvider(base_url=cfg.ollama_base_url, model_name=cfg.ollama_model)
        elif chosen == "cloud":
            return CloudProvider(
                api_key=cfg.cloud_api_key,
                base_url=cfg.cloud_base_url,
                model_name=cfg.cloud_model,
                provider_name=cfg.cloud_provider,
            )
        elif chosen == "mock":
            return MockProvider()
        else:
            raise ValueError(f"Unknown provider type: {chosen}. Choose 'cloud', 'ollama', or 'mock'.")
