import os
import shutil
from pathlib import Path
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # LLM Settings
    default_llm_provider: Literal["cloud", "ollama", "mock", "openrouter", "google_studio"] = "ollama"
    
    # Cloud Provider Settings (OpenAI / Generic)
    cloud_provider: str = "openai"
    cloud_api_key: Optional[str] = None
    cloud_base_url: str = "https://api.openai.com/v1"
    cloud_model: str = "gpt-4o-mini"
    
    # OpenRouter Provider Settings
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "anthropic/claude-3.5-sonnet"

    # Google AI Studio Provider Settings
    google_studio_api_key: Optional[str] = None
    google_studio_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    google_studio_model: str = "gemini-2.0-flash"
    
    # Ollama Provider Settings
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:latest"
    
    # Independent Embedding Settings
    embedding_provider: Literal["chroma_default", "ollama", "cloud"] = "chroma_default"
    embedding_model: str = "all-MiniLM-L6-v2"
    ollama_embedding_model: str = "qwen3-embedding:4b"
    
    # Vector DB and Retrieval
    chroma_persist_directory: str = "backend/knowledge_base/chroma_db"
    chroma_collection_name: str = "cad_knowledge_base"
    bm25_top_k: int = 15
    dense_top_k: int = 15
    rerank_top_k: int = 5
    
    # CAD Runtime
    freecad_bin_path: Optional[str] = None
    cad_execution_timeout_seconds: int = 120
    max_repair_attempts: int = 2
    allow_unsafe_execution: bool = False
    
    # Artifacts & Paths
    artifacts_dir: str = "backend/artifacts"
    knowledge_base_dir: str = "backend/knowledge_base"
    
    # Network
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    def get_resolved_freecad_path(self) -> Optional[str]:
        """Auto-detects FreeCAD executable if not explicitly set."""
        if self.freecad_bin_path and Path(self.freecad_bin_path).is_file():
            return self.freecad_bin_path
        
        # Check PATH
        for cmd in ["freecadcmd", "freecad", "FreeCADCmd", "FreeCAD"]:
            found = shutil.which(cmd)
            if found:
                return found
        
        # Check Windows typical paths
        possible_patterns = [
            r"C:\Program Files\FreeCAD*\bin\freecadcmd.exe",
            r"C:\Program Files\FreeCAD*\bin\FreeCADCmd.exe",
            r"C:\Program Files\FreeCAD*\bin\FreeCAD.exe",
            r"C:\Program Files (x86)\FreeCAD*\bin\freecadcmd.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeCAD*\bin\freecadcmd.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeCAD*\bin\FreeCADCmd.exe"),
        ]
        
        import glob
        for pattern in possible_patterns:
            matches = glob.glob(pattern)
            if matches:
                cli_matches = [m for m in matches if "cmd" in m.lower()]
                return cli_matches[0] if cli_matches else matches[0]
                
        return None


# Global active settings instance
_active_settings = Settings()


def get_settings() -> Settings:
    return _active_settings


def update_runtime_settings(**kwargs) -> Settings:
    """Dynamically update settings at runtime without server restart."""
    global _active_settings
    current_dict = _active_settings.model_dump()
    for k, v in kwargs.items():
        if k in current_dict and v is not None:
            current_dict[k] = v
    _active_settings = Settings(**current_dict)
    return _active_settings
