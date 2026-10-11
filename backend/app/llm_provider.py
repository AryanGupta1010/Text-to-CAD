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
    """Strips thinking tags (<think>...</think>) while preserving any actual content/code/JSON."""
    if not text:
        return ""

    # 1. If proper </think> closing tag exists:
    if "</think>" in text:
        after = text.split("</think>", 1)[1].strip()
        if after:
            return after
        # If nothing after </think>, look inside <think>...</think> for code or JSON
        inside = text.split("</think>", 1)[0]
        inside = re.sub(r"^.*?<think>", "", inside, flags=re.DOTALL).strip()
        if inside:
            return inside

    # 2. If unclosed <think> tag:
    if "<think>" in text:
        # Check if there is markdown code block or JSON inside the unclosed thinking
        code_block = re.search(r"```(?:python|json)?\s*([\s\S]*?)(?:```|$)", text)
        if code_block and code_block.group(1).strip():
            return code_block.group(0).strip()
        # If there's a JSON structure {...}
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            return text[first_brace:last_brace + 1].strip()
        # Check for python CAD code
        if "import FreeCAD" in text or "import Part" in text or "Part." in text:
            indices = [i for i in [text.find("import FreeCAD"), text.find("import Part"), text.find("Part.")] if i != -1]
            if indices:
                return text[min(indices):].strip()
        # If only pure thought text without any code/json, strip <think> tag prefix
        return re.sub(r"^.*?<think>\s*", "", text, flags=re.DOTALL).strip()

    return text.strip()


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Robustly extracts JSON from an LLM response even if surrounded by markdown, thinking tags, or preamble."""
    if not text:
        raise ValueError("LLM returned empty output.")
        
    cleaned = clean_llm_output(text)

    # Try direct parse on cleaned or raw
    for candidate_str in [cleaned, text]:
        try:
            return json.loads(candidate_str)
        except Exception:
            pass

    # Try finding markdown ```json ... ``` block in cleaned or text
    for candidate_str in [cleaned, text]:
        json_block = re.search(r"```(?:json)?\s*([\s\S]*?)(?:```|$)", candidate_str)
        if json_block:
            try:
                return json.loads(json_block.group(1).strip())
            except Exception:
                pass

    # Try finding outermost { ... }
    for candidate_str in [cleaned, text]:
        first_brace = candidate_str.find("{")
        last_brace = candidate_str.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = candidate_str[first_brace : last_brace + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass

    # Relaxed JSON repair (replace single quotes, strip trailing commas)
    for candidate_str in [cleaned, text]:
        first_brace = candidate_str.find("{")
        last_brace = candidate_str.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = candidate_str[first_brace : last_brace + 1]
            relaxed = re.sub(r",\s*([\]}])", r"\1", candidate)
            try:
                return json.loads(relaxed)
            except Exception:
                pass

    raise ValueError(f"Could not extract valid JSON from LLM output. Content snippet: {cleaned[:200] if cleaned else text[:200]}")


def extract_python_code(text: str) -> str:
    """Robustly extracts python code from markdown blocks, unclosed blocks, or plain code."""
    cleaned = clean_llm_output(text)

    code = ""
    # 1. Check for ```python ... (closed with ``` or unclosed at EOF)
    for candidate_str in [cleaned, text]:
        match = re.search(r"```python\s*([\s\S]*?)(?:```|$)", candidate_str)
        if match and ("FreeCAD" in match.group(1) or "Part" in match.group(1) or "def " in match.group(1)):
            code = match.group(1).strip()
            break

    # 2. Check for generic ``` ...
    if not code:
        for candidate_str in [cleaned, text]:
            match = re.search(r"```\s*([\s\S]*?)(?:```|$)", candidate_str)
            if match and ("FreeCAD" in match.group(1) or "Part" in match.group(1) or "def " in match.group(1)):
                code = match.group(1).strip()
                break

    # 3. Check for raw code starting with import
    if not code:
        for candidate_str in [cleaned, text]:
            import_idx = candidate_str.find("import FreeCAD")
            if import_idx == -1:
                import_idx = candidate_str.find("import Part")
            if import_idx != -1:
                code_part = candidate_str[import_idx:]
                code_part = re.sub(r"```.*$", "", code_part, flags=re.DOTALL).strip()
                code = code_part
                break

    # 4. If code uses Part. or FreeCAD. calls without imports
    if not code:
        for candidate_str in [cleaned, text]:
            if "Part." in candidate_str or "FreeCAD." in candidate_str:
                code_part = re.sub(r"```.*$", "", candidate_str, flags=re.DOTALL).strip()
                code = code_part
                break

    if not code:
        code = cleaned.strip() or text.strip()

    # Prepend essential CAD imports if Part or FreeCAD references exist without import
    if code and ("Part." in code or "FreeCAD." in code or "doc." in code):
        if "import FreeCAD" not in code:
            code = "import FreeCAD\n" + code
        if "import Part" not in code:
            code = "import Part\n" + code

    return code


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
        sys_content = (system or "").strip()
        if json_mode:
            sys_content += "\nRespond strictly with a valid JSON object matching the requested schema. Enclose JSON in ```json and ``` code block."
        messages.append({"role": "system", "content": sys_content.strip()})

        user_content = prompt
        if json_mode and "```json" not in prompt:
            user_content += "\n\nProvide ONLY the structured JSON output enclosed in ```json ... ``` markdown block."
        messages.append({"role": "user", "content": user_content})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 4096,
                "top_k": 40,
                "top_p": 0.9,
            },
        }

        try:
            # timeout=None allows local LLMs to run as long as needed without arbitrary cutoffs
            with httpx.Client(timeout=None) as client:
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


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter Cloud Provider supporting hundreds of models via OpenRouter's unified API."""
    def __init__(
        self,
        api_key: Optional[str],
        base_url: str = "https://openrouter.ai/api/v1",
        model_name: str = "anthropic/claude-3.5-sonnet",
    ):
        self.api_key = api_key
        self.base_url = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self.model_name = model_name or "anthropic/claude-3.5-sonnet"

    def get_provider_type(self) -> str:
        return "openrouter"

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
            raise ValueError("OpenRouter API key is missing. Please provide your OpenRouter API key in Provider Settings.")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "Text-To-CAD",
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
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return clean_llm_output(content)
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"OpenRouter API error ({e.response.status_code}): {e.response.text[:300]}")
        except Exception as e:
            raise RuntimeError(f"OpenRouter request failed: {str(e)}")

    def test_connection(self) -> ProviderTestResponse:
        t0 = time.time()
        if not self.api_key or not self.api_key.strip():
            return ProviderTestResponse(
                success=False,
                provider="openrouter",
                model=self.model_name,
                message="OpenRouter API key is missing. Enter a valid key starting with 'sk-or-v1-'.",
                latency_ms=0,
                capabilities=[],
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "Text-To-CAD",
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
                        provider="openrouter",
                        model=self.model_name,
                        message=f"OpenRouter verified successfully with '{self.model_name}'.",
                        latency_ms=latency,
                        capabilities=["chat", "openrouter_routing", "json_mode"],
                    )
                else:
                    return ProviderTestResponse(
                        success=False,
                        provider="openrouter",
                        model=self.model_name,
                        message=f"OpenRouter returned error ({resp.status_code}): {resp.text[:200]}",
                        latency_ms=latency,
                    )
        except Exception as e:
            return ProviderTestResponse(
                success=False,
                provider="openrouter",
                model=self.model_name,
                message=f"OpenRouter connection failed: {str(e)}",
                latency_ms=round((time.time() - t0) * 1000, 2),
            )


class GoogleStudioProvider(BaseLLMProvider):
    """Google AI Studio (Gemini) provider supporting direct Gemini API keys."""
    def __init__(
        self,
        api_key: Optional[str],
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
        model_name: str = "gemini-2.0-flash",
    ):
        self.api_key = api_key
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
        # Normalize model name - strip models/ prefix if present
        clean_model = model_name or "gemini-2.0-flash"
        if clean_model.startswith("models/"):
            clean_model = clean_model[len("models/"):]
        self.model_name = clean_model

    def get_provider_type(self) -> str:
        return "google_studio"

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
            raise ValueError("Google AI Studio API key is missing. Please provide your Gemini API key in Provider Settings.")

        # Attempt 1: Google's official OpenAI-compatible endpoint
        try:
            return self._generate_openai_compat(prompt, system, json_mode, temperature)
        except Exception as err:
            logger.warning(f"Google Studio OpenAI-compatible endpoint error: {err}. Attempting native generateContent fallback.")
            return self._generate_native(prompt, system, json_mode, temperature)

    def _generate_openai_compat(
        self,
        prompt: str,
        system: Optional[str],
        json_mode: bool,
        temperature: float,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
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

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return clean_llm_output(content)

    def _generate_native(
        self,
        prompt: str,
        system: Optional[str],
        json_mode: bool,
        temperature: float,
    ) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key.strip()}"
        combined_prompt = f"{system}\n\n{prompt}" if system else prompt
        
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": combined_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
            },
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"Google AI Studio returned no candidate responses: {data}")
            parts = candidates[0].get("content", {}).get("parts", [])
            content = parts[0].get("text", "") if parts else ""
            return clean_llm_output(content)

    def test_connection(self) -> ProviderTestResponse:
        t0 = time.time()
        if not self.api_key or not self.api_key.strip():
            return ProviderTestResponse(
                success=False,
                provider="google_studio",
                model=self.model_name,
                message="Google AI Studio API key is missing. Enter your Gemini API key from https://aistudio.google.com.",
                latency_ms=0,
                capabilities=[],
            )

        # Test OpenAI-compatible endpoint first
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
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
                        provider="google_studio",
                        model=self.model_name,
                        message=f"Connected to Google AI Studio successfully with '{self.model_name}'.",
                        latency_ms=latency,
                        capabilities=["chat", "gemini_multimodal", "json_mode"],
                    )
                # Fall back to native endpoint ping
                native_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key.strip()}"
                native_resp = client.post(
                    native_url,
                    json={"contents": [{"parts": [{"text": "ping"}]}], "generationConfig": {"maxOutputTokens": 5}},
                )
                latency_native = round((time.time() - t0) * 1000, 2)
                if native_resp.status_code == 200:
                    return ProviderTestResponse(
                        success=True,
                        provider="google_studio",
                        model=self.model_name,
                        message=f"Connected to Google AI Studio (Native) successfully with '{self.model_name}'.",
                        latency_ms=latency_native,
                        capabilities=["chat", "gemini_native", "json_mode"],
                    )
                return ProviderTestResponse(
                    success=False,
                    provider="google_studio",
                    model=self.model_name,
                    message=f"Google Studio returned error ({resp.status_code}): {resp.text[:200]}",
                    latency_ms=latency,
                )
        except Exception as e:
            return ProviderTestResponse(
                success=False,
                provider="google_studio",
                model=self.model_name,
                message=f"Google AI Studio connection failed: {str(e)}",
                latency_ms=round((time.time() - t0) * 1000, 2),
            )


class MockProvider(BaseLLMProvider):
    """Deterministic mock provider for offline testing and multi-shape verification."""
    def __init__(self, model_name: str = "mock-cad-engine"):
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

        # 1. Code Generation
        if "generate the freecad python script" in lower_prompt or "generate the python script" in lower_prompt or "failed script" in lower_prompt:
            return self._generate_mock_script(lower_prompt)

        # 2. Requirement Extraction
        if json_mode or "cad specification" in lower_prompt or "extract requirements" in lower_prompt or "clarification" in lower_prompt:
            return self._extract_mock_spec(lower_prompt)

        # Default fallback script
        return self._generate_mock_script(lower_prompt)

    def _extract_mock_spec(self, lower_prompt: str) -> str:
        """Extracts multi-shape specifications for box, cube, cylinder, hollow container, bushing, sphere."""
        # Check if prompt lacks any explicit numerical dimension
        has_numbers = bool(re.search(r"\d+", lower_prompt))
        if not has_numbers:
            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": "Ambiguous CAD request without dimensions",
                "features": [],
                "parameters": {},
                "constraints": [],
                "operations": [],
                "output_formats": ["STEP", "STL"],
                "assumptions": [],
                "clarification_required": True,
                "clarification_questions": ["Please specify the key dimensions (such as radius or length/width, and height) in mm."]
            }
            return json.dumps(spec, indent=2)

        # Isolate the user's actual request from the prompt template
        req_match = re.search(r'request:\s*["\']?(.*?)["\']?(?:\n\n|\nremember|$)', lower_prompt, flags=re.DOTALL)
        target_text = req_match.group(1).strip() if req_match else lower_prompt

        # Detect shape type strictly on the user request text
        is_l_pipe = any(k in target_text for k in ["l-shape", "l-shaped", "elbow", "90-degree", "90 degree", "curved bend", "curved pipe"]) or ("pipe" in target_text and ("bend" in target_text or "bent" in target_text or "curve" in target_text))
        is_hex = not is_l_pipe and any(k in target_text for k in ["hex", "hexagon", "hexagonal"])
        is_cone = not is_l_pipe and any(k in target_text for k in ["cone", "frustum", "nozzle", "funnel"])
        is_box = not is_l_pipe and not is_hex and not is_cone and (any(k in target_text for k in ["cube", "box", "block", "enclosure", "rectangular plate", "plate", "prism", "cuboid"]) or bool(re.search(r"\d+\s*(?:x|\*)\s*\d+\s*(?:x|\*)\s*\d+", target_text)))
        is_sphere = not is_l_pipe and any(k in target_text for k in ["sphere", "ball", "globe"])
        is_bushing = not is_l_pipe and any(k in target_text for k in ["bushing", "flanged pipe", "straight pipe", "tube", "washer", "spacer", "sleeve"])
        is_hollow_container = not is_l_pipe and not is_bushing and (any(k in target_text for k in ["container", "cup", "can", "pot", "pocket"]) or ("hollow" in target_text and "cylinder" in target_text))
        is_solid_cylinder = not is_l_pipe and not is_hollow_container and not is_bushing and any(k in target_text for k in ["cylinder", "rod", "pin", "shaft", "disc", "disk", "round bar"])

        params: Dict[str, float] = {}

        # 0. L-Shaped / Bent Pipe
        if is_l_pipe:
            od_m = re.search(r"outer\s*diameter\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            outer_r = float(od_m.group(1)) / 2.0 if od_m else 10.0
            if not od_m:
                or_m = re.search(r"outer\s*radius\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
                if or_m:
                    outer_r = float(or_m.group(1))

            id_m = re.search(r"inner\s*diameter\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            inner_r = float(id_m.group(1)) / 2.0 if id_m else 7.0
            if not id_m:
                ir_m = re.search(r"inner\s*radius\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
                if ir_m:
                    inner_r = float(ir_m.group(1))

            side_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*long", target_text)
            l1 = float(side_m.group(1)) if side_m else 100.0
            l2 = l1
            l1_m = re.search(r"(?:length\s*1|arm\s*1|section\s*1)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if l1_m:
                l1 = float(l1_m.group(1))
            l2_m = re.search(r"(?:length\s*2|arm\s*2|section\s*2)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if l2_m:
                l2 = float(l2_m.group(1))

            bend_r = 30.0
            br_m = re.search(r"(?:bend\s*radius|curve\s*radius)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if br_m:
                bend_r = float(br_m.group(1))

            params = {
                "outer_radius": outer_r,
                "inner_radius": inner_r,
                "length_1": l1,
                "length_2": l2,
                "bend_radius": bend_r,
                "bend_angle": 90.0,
                "wall_thickness": round(outer_r - inner_r, 4),
            }
            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"3D L-shaped hollow pipe with 90-degree curved bend (L1={l1}mm, L2={l2}mm, OD={outer_r*2}mm, ID={inner_r*2}mm)",
                "features": [
                    {
                        "feature_type": "l_shaped_pipe",
                        "dimensions": params,
                        "parameters": {"shape": "elbow_bend", "bend_angle": 90.0},
                        "geometric_constraints": ["tangent_continuous", "smooth_bend"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True, "is_hollow": True}
                    }
                ],
                "parameters": params,
                "constraints": ["90_degree_bend", "hollow"],
                "operations": ["create_path_wire", "create_outer_profile", "create_inner_profile", "sweep_outer", "sweep_inner", "boolean_cut"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["XZ plane bend orientation", "Smooth tangential arc transition"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 1. Box / Cube
        elif is_box:
            # Check for cube side: "40mm cube", "cube of 40mm", "side of 50mm"
            cube_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*cube|(?:cube\s*(?:of|with\s*side)?|side)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if cube_match:
                s = float(cube_match.group(1) or cube_match.group(2))
                params["length"] = s
                params["width"] = s
                params["height"] = s
            else:
                # Length, width, height or dimensions like 100x60x10
                dim3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)", target_text)
                if dim3:
                    params["length"] = float(dim3.group(1))
                    params["width"] = float(dim3.group(2))
                    params["height"] = float(dim3.group(3))
                else:
                    l_m = re.search(r"length\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
                    w_m = re.search(r"width\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
                    h_m = re.search(r"(?:height|thickness)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
                    params["length"] = float(l_m.group(1)) if l_m else 60.0
                    params["width"] = float(w_m.group(1)) if w_m else 40.0
                    params["height"] = float(h_m.group(1)) if h_m else 25.0

            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"Rectangular box or enclosure ({params['length']} x {params['width']} x {params['height']} mm)",
                "features": [
                    {
                        "feature_type": "box",
                        "dimensions": params,
                        "parameters": {"centered": False},
                        "geometric_constraints": ["orthogonal"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    }
                ],
                "parameters": params,
                "constraints": ["orthogonal_faces"],
                "operations": ["create_box"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Origin at base corner (0,0,0)"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 2. Sphere
        elif is_sphere:
            r_match = re.search(r"(?:radius|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if "diameter" in target_text and r_match:
                params["radius"] = float(r_match.group(1)) / 2.0
            elif r_match:
                params["radius"] = float(r_match.group(1))
            else:
                params["radius"] = 25.0

            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"Solid sphere with radius {params['radius']} mm",
                "features": [
                    {
                        "feature_type": "sphere",
                        "dimensions": params,
                        "parameters": {},
                        "geometric_constraints": ["spherical_symmetry"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    }
                ],
                "parameters": params,
                "constraints": ["spherical_symmetry"],
                "operations": ["create_sphere"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Centered at origin"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 2b. Cone / Frustum
        elif is_cone:
            r1_m = re.search(r"(?:bottom\s*radius|base\s*radius|radius1|radius)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            r1 = float(r1_m.group(1)) if r1_m else 25.0
            r2_m = re.search(r"(?:top\s*radius|radius2)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            r2 = float(r2_m.group(1)) if r2_m else 0.0
            h_m = re.search(r"(?:height|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            h = float(h_m.group(1)) if h_m else 60.0
            params = {"radius1": r1, "radius2": r2, "height": h}
            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"Cone with bottom radius {r1} mm, top radius {r2} mm, and height {h} mm",
                "features": [
                    {
                        "feature_type": "cone",
                        "dimensions": params,
                        "parameters": {},
                        "geometric_constraints": ["conical_symmetry"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    }
                ],
                "parameters": params,
                "constraints": ["conical_symmetry"],
                "operations": ["create_cone"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Origin at base coordinate"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 2c. Hexagonal Prism
        elif is_hex:
            r_m = re.search(r"(?:radius|size)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            r = float(r_m.group(1)) if r_m else 25.0
            h_m = re.search(r"(?:height|thickness|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            h = float(h_m.group(1)) if h_m else 40.0
            params = {"radius": r, "height": h}
            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"Hexagonal prism with radius {r} mm and height {h} mm",
                "features": [
                    {
                        "feature_type": "hexagonal_prism",
                        "dimensions": params,
                        "parameters": {},
                        "geometric_constraints": ["hexagonal_symmetry"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    }
                ],
                "parameters": params,
                "constraints": ["hexagonal_symmetry"],
                "operations": ["create_hexagonal_polygon", "extrude_face"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Origin at base coordinate"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 3. Bushing / Pipe / Tube
        elif is_bushing:
            outer_r = 25.0
            inner_r = 15.0
            length = 60.0
            r_out = re.search(r"(?:outer\s*radius|outer\s*dia)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if r_out:
                outer_r = float(r_out.group(1)) if "radius" in r_out.group(0) else float(r_out.group(1)) / 2.0
            r_in = re.search(r"(?:inner\s*radius|inner\s*dia|bore)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if r_in:
                inner_r = float(r_in.group(1)) if "radius" in r_in.group(0) else float(r_in.group(1)) / 2.0
            l_m = re.search(r"(?:length|height)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if l_m:
                length = float(l_m.group(1))

            params = {"outer_radius": outer_r, "inner_radius": inner_r, "height": length}
            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"Bushing / pipe with outer radius {outer_r} mm, bore {inner_r} mm, and length {length} mm",
                "features": [
                    {
                        "feature_type": "cylinder",
                        "dimensions": {"radius": outer_r, "height": length},
                        "parameters": {"role": "outer_body"},
                        "geometric_constraints": ["concentric"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    },
                    {
                        "feature_type": "cylinder_pocket",
                        "dimensions": {"radius": inner_r, "height": length + 2.0},
                        "parameters": {"role": "through_hole"},
                        "geometric_constraints": ["coaxial"],
                        "dependencies": ["cylinder"],
                        "expected_properties": {"subtraction": True}
                    }
                ],
                "parameters": params,
                "constraints": ["concentric", "through_hole"],
                "operations": ["create_outer_cylinder", "create_inner_cylinder", "boolean_cut"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Z-axis alignment"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 4. Solid Cylinder
        elif is_solid_cylinder:
            r = 20.0
            h = 50.0
            r_m = re.search(r"(?:radius|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if r_m:
                r = float(r_m.group(1)) if "radius" in r_m.group(0) else float(r_m.group(1)) / 2.0
            h_m = re.search(r"(?:height|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if h_m:
                h = float(h_m.group(1))

            params = {"radius": r, "height": h}
            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"Solid cylinder with radius {r} mm and height {h} mm",
                "features": [
                    {
                        "feature_type": "cylinder",
                        "dimensions": params,
                        "parameters": {},
                        "geometric_constraints": ["cylindrical_symmetry"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    }
                ],
                "parameters": params,
                "constraints": ["cylindrical_symmetry"],
                "operations": ["create_cylinder"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Z-axis alignment"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 5. Hollow Cylindrical Container
        elif is_hollow_container:
            outer_r = 30.0
            height = 100.0
            wall_t = 3.0
            bot_t = 4.0

            r_match = re.search(r"outer\s*radius\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if r_match:
                outer_r = float(r_match.group(1))
            h_match = re.search(r"height\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if h_match:
                height = float(h_match.group(1))
            w_match = re.search(r"wall\s*thickness\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if w_match:
                wall_t = float(w_match.group(1))
            b_match = re.search(r"bottom\s*thickness\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if b_match:
                bot_t = float(b_match.group(1))

            inner_r = max(1.0, outer_r - wall_t)
            inner_h = max(1.0, height - bot_t)

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
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

        # 6. Smart Generic Custom Shape
        else:
            nums = [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", target_text)]
            dim3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)", target_text)
            if dim3:
                l, w, h = float(dim3.group(1)), float(dim3.group(2)), float(dim3.group(3))
                params = {"length": l, "width": w, "height": h}
            elif len(nums) >= 3:
                params = {"length": nums[0], "width": nums[1], "height": nums[2]}
            elif len(nums) == 1:
                params = {"length": nums[0], "width": nums[0], "height": nums[0]}
            elif len(nums) == 2:
                params = {"radius": nums[0], "height": nums[1]}
            else:
                params = {"length": 50.0, "width": 50.0, "height": 50.0}

            f_type = "cylinder" if "radius" in params else "box"
            spec = {
                "cad_engine": "FreeCAD",
                "units": "mm",
                "object_description": f"Custom 3D CAD design",
                "features": [
                    {
                        "feature_type": f_type,
                        "dimensions": params,
                        "parameters": {},
                        "geometric_constraints": ["orthogonal" if f_type == "box" else "cylindrical_symmetry"],
                        "dependencies": [],
                        "expected_properties": {"is_solid": True}
                    }
                ],
                "parameters": params,
                "constraints": ["orthogonal" if f_type == "box" else "cylindrical_symmetry"],
                "operations": [f"create_{f_type}"],
                "output_formats": ["STEP", "STL"],
                "assumptions": ["Origin at base coordinate"],
                "clarification_required": False,
                "clarification_questions": []
            }
            return json.dumps(spec, indent=2)

    def _generate_mock_script(self, lower_prompt: str) -> str:
        """Generates appropriate executable FreeCAD Python script for the requested shape."""
        target_text = lower_prompt[:500]
        is_l_pipe = any(k in target_text for k in ["l-shape", "l-shaped", "elbow", "90-degree", "90 degree", "curved bend", "curved pipe"]) or ("pipe" in target_text and ("bend" in target_text or "bent" in target_text or "curve" in target_text))
        is_box = not is_l_pipe and any(k in target_text for k in ["cube", "box", "enclosure", "rectangular plate"])
        is_sphere = not is_l_pipe and any(k in target_text for k in ["sphere", "ball"])
        is_cone = not is_l_pipe and any(k in target_text for k in ["cone", "frustum", "nozzle", "funnel"])
        is_hex = not is_l_pipe and any(k in target_text for k in ["hex", "hexagon", "hexagonal", "prism"])
        is_bushing = not is_l_pipe and any(k in target_text for k in ["bushing", "flanged pipe", "straight pipe", "tube", "washer", "spacer", "ring"])
        is_solid_cyl = not is_l_pipe and not is_bushing and any(k in target_text for k in ["solid cylinder", "rod", "pin", "shaft"])

        if is_l_pipe:
            od_m = re.search(r"outer\s*diameter\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            outer_radius = float(od_m.group(1)) / 2.0 if od_m else 10.0
            if not od_m:
                or_m = re.search(r"outer\s*radius\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
                if or_m:
                    outer_radius = float(or_m.group(1))

            id_m = re.search(r"inner\s*diameter\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            inner_radius = float(id_m.group(1)) / 2.0 if id_m else 7.0
            if not id_m:
                ir_m = re.search(r"inner\s*radius\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
                if ir_m:
                    inner_radius = float(ir_m.group(1))

            l_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*long", target_text)
            length_1 = float(l_m.group(1)) if l_m else 100.0
            length_2 = length_1
            l1_m = re.search(r"(?:length\s*1|arm\s*1|l1)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if l1_m:
                length_1 = float(l1_m.group(1))
            l2_m = re.search(r"(?:length\s*2|arm\s*2|l2)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if l2_m:
                length_2 = float(l2_m.group(1))
            bend_radius = 30.0
            br_m = re.search(r"(?:bend\s*radius|curve\s*radius)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if br_m:
                bend_radius = float(br_m.group(1))

            script = f"""import FreeCAD
import Part
import math

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    outer_radius = {outer_radius}
    inner_radius = {inner_radius}
    length_1 = {length_1}
    length_2 = {length_2}
    bend_radius = {bend_radius}

    s1 = max(10.0, length_1 - bend_radius)
    s2 = max(10.0, length_2 - bend_radius)

    # Trajectory path in XZ plane
    p0 = FreeCAD.Vector(0, 0, 0)
    p1 = FreeCAD.Vector(0, 0, s1)
    line1 = Part.makeLine(p0, p1)

    arc_center = FreeCAD.Vector(bend_radius, 0, s1)
    p_mid = FreeCAD.Vector(bend_radius - bend_radius * math.cos(math.pi / 4), 0, s1 + bend_radius * math.sin(math.pi / 4))
    p2 = FreeCAD.Vector(bend_radius, 0, s1 + bend_radius)
    arc = Part.Arc(p1, p_mid, p2).toShape()

    p3 = FreeCAD.Vector(length_2, 0, s1 + bend_radius)
    line2 = Part.makeLine(p2, p3)

    path_wire = Part.Wire([line1, arc, line2])

    outer_circle = Part.makeCircle(outer_radius, p0, FreeCAD.Vector(0, 0, 1))
    outer_face = Part.Face(Part.Wire([outer_circle]))
    outer_pipe = outer_face.makePipe(path_wire)

    inner_circle = Part.makeCircle(inner_radius, p0, FreeCAD.Vector(0, 0, 1))
    inner_face = Part.Face(Part.Wire([inner_circle]))
    inner_pipe = inner_face.makePipe(path_wire)

    pipe = outer_pipe.cut(inner_pipe)
    if not pipe.isValid():
        raise RuntimeError("Generated L-shaped pipe geometry is invalid")

    shape_obj = doc.addObject("Part::Feature", "LShapedPipe")
    shape_obj.Shape = pipe
    doc.recompute()

    pipe.exportStep("model.step")
    pipe.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        elif is_box:
            cube_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*cube|(?:cube\s*(?:of|with\s*side)?|side)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            dim3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)", target_text)
            lm = re.search(r"length\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            wm = re.search(r"width\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            hm = re.search(r"(?:height|thickness)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if cube_m:
                s = float(cube_m.group(1) or cube_m.group(2))
                l, w, h = s, s, s
            elif dim3:
                l, w, h = float(dim3.group(1)), float(dim3.group(2)), float(dim3.group(3))
            else:
                l = float(lm.group(1)) if lm else 60.0
                w = float(wm.group(1)) if wm else 40.0
                h = float(hm.group(1)) if hm else 25.0

            script = f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    length = {l}
    width = {w}
    height = {h}
    
    box = Part.makeBox(length, width, height)
    if not box.isValid():
        raise RuntimeError("Generated box geometry is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = box
    doc.recompute()

    box.exportStep("model.step")
    box.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        elif is_sphere:
            rm = re.search(r"(?:radius|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            radius = float(rm.group(1)) if rm else 25.0
            if "diameter" in target_text and rm: radius = radius / 2.0
            script = f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    radius = {radius}
    
    sphere = Part.makeSphere(radius)
    if not sphere.isValid():
        raise RuntimeError("Generated sphere geometry is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = sphere
    doc.recompute()

    sphere.exportStep("model.step")
    sphere.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        elif is_cone:
            r1_m = re.search(r"(?:bottom\s*radius|base\s*radius|radius1|radius)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            r1 = float(r1_m.group(1)) if r1_m else 25.0
            r2_m = re.search(r"(?:top\s*radius|radius2)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            r2 = float(r2_m.group(1)) if r2_m else 0.0
            hm = re.search(r"(?:height|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            height = float(hm.group(1)) if hm else 60.0
            script = f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    radius1 = {r1}
    radius2 = {r2}
    height = {height}
    
    cone = Part.makeCone(radius1, radius2, height)
    if not cone.isValid():
        raise RuntimeError("Generated cone geometry is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = cone
    doc.recompute()

    cone.exportStep("model.step")
    cone.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        elif is_hex:
            rm = re.search(r"(?:radius|size)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            radius = float(rm.group(1)) if rm else 25.0
            hm = re.search(r"(?:height|thickness|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            height = float(hm.group(1)) if hm else 40.0
            script = f"""import FreeCAD
import Part
import math

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    radius = {radius}
    height = {height}
    
    pts = []
    for i in range(6):
        ang = i * (2.0 * math.pi / 6.0)
        pts.append(FreeCAD.Vector(radius * math.cos(ang), radius * math.sin(ang), 0))
    pts.append(pts[0])
    
    wire = Part.makePolygon(pts)
    face = Part.Face(wire)
    solid = face.extrude(FreeCAD.Vector(0, 0, height))
    if not solid.isValid():
        raise RuntimeError("Generated hexagonal prism geometry is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = solid
    doc.recompute()

    solid.exportStep("model.step")
    solid.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        elif is_bushing:
            outer_radius = 25.0
            inner_radius = 15.0
            height = 60.0
            ro_m = re.search(r"(?:outer\s*radius|outer\s*dia)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if ro_m: outer_radius = float(ro_m.group(1)) if "radius" in ro_m.group(0) else float(ro_m.group(1)) / 2.0
            ri_m = re.search(r"(?:inner\s*radius|inner\s*dia|bore)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if ri_m: inner_radius = float(ri_m.group(1)) if "radius" in ri_m.group(0) else float(ri_m.group(1)) / 2.0
            hm = re.search(r"(?:height|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            if hm: height = float(hm.group(1))

            script = f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    outer_radius = {outer_radius}
    inner_radius = {inner_radius}
    height = {height}
    
    outer_cyl = Part.makeCylinder(outer_radius, height)
    cutter = Part.makeCylinder(inner_radius, height + 2.0)
    cutter.translate(FreeCAD.Vector(0, 0, -1.0))
    
    bushing = outer_cyl.cut(cutter)
    if not bushing.isValid():
        raise RuntimeError("Generated bushing geometry is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = bushing
    doc.recompute()

    bushing.exportStep("model.step")
    bushing.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        elif is_solid_cyl:
            rm = re.search(r"(?:radius|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            hm = re.search(r"(?:height|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", target_text)
            radius = float(rm.group(1)) if rm else 20.0
            if "diameter" in target_text and rm: radius = radius / 2.0
            height = float(hm.group(1)) if hm else 50.0

            script = f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    radius = {radius}
    height = {height}
    
    cyl = Part.makeCylinder(radius, height)
    if not cyl.isValid():
        raise RuntimeError("Generated cylinder geometry is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = cyl
    doc.recompute()

    cyl.exportStep("model.step")
    cyl.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        elif any(k in target_text for k in ["container", "cup", "can", "pot"]) or ("hollow" in target_text and "cylinder" in target_text):
            # Hollow cylindrical container
            script = """import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    outer_radius = 30.0
    height = 100.0
    wall_thickness = 3.0
    bottom_thickness = 4.0
    inner_radius = outer_radius - wall_thickness
    
    outer_cyl = Part.makeCylinder(outer_radius, height)
    inner_cyl = Part.makeCylinder(inner_radius, height - bottom_thickness + 1.0)
    inner_cyl.translate(FreeCAD.Vector(0, 0, bottom_thickness))
    
    container = outer_cyl.cut(inner_cyl)
    if not container.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = container
    doc.recompute()

    container.exportStep("model.step")
    container.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
        else:
            # Custom solid matching extracted prompt dimensions
            nums = [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", target_text)]
            dim3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)", target_text)
            l = float(dim3.group(1)) if dim3 else (nums[0] if len(nums) > 0 else 50.0)
            w = float(dim3.group(2)) if dim3 else (nums[1] if len(nums) > 1 else l)
            h = float(dim3.group(3)) if dim3 else (nums[2] if len(nums) > 2 else l)
            script = f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    length = {l}
    width = {w}
    height = {h}
    
    box = Part.makeBox(length, width, height)
    if not box.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = box
    doc.recompute()

    box.exportStep("model.step")
    box.exportStl("model.stl")
    doc.saveAs("model.FCStd")
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
        elif chosen == "openrouter":
            return OpenRouterProvider(
                api_key=cfg.openrouter_api_key,
                base_url=cfg.openrouter_base_url,
                model_name=cfg.openrouter_model,
            )
        elif chosen == "google_studio":
            return GoogleStudioProvider(
                api_key=cfg.google_studio_api_key,
                base_url=cfg.google_studio_base_url,
                model_name=cfg.google_studio_model,
            )
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
            raise ValueError(f"Unknown provider type: {chosen}. Choose 'openrouter', 'google_studio', 'cloud', 'ollama', or 'mock'.")
