import pytest
from backend.app.config import get_settings, update_runtime_settings
from backend.app.llm_provider import ProviderFactory, MockProvider, CloudProvider, OllamaProvider


def test_provider_factory_mock():
    provider = ProviderFactory.get_provider("mock")
    assert isinstance(provider, MockProvider)
    assert provider.get_provider_type() == "mock"
    res = provider.test_connection()
    assert res.success is True


def test_provider_runtime_switching():
    settings = get_settings()
    # Switch to mock
    update_runtime_settings(default_llm_provider="mock")
    p1 = ProviderFactory.get_provider()
    assert p1.get_provider_type() == "mock"

    # Switch to ollama
    update_runtime_settings(default_llm_provider="ollama")
    p2 = ProviderFactory.get_provider()
    assert p2.get_provider_type() == "ollama"


def test_cloud_provider_missing_key():
    cloud = CloudProvider(api_key=None, base_url="https://api.openai.com/v1", model_name="gpt-4o-mini")
    test_res = cloud.test_connection()
    assert test_res.success is False
    assert "missing" in test_res.message.lower()


def test_secret_not_leaked_in_str():
    cloud = CloudProvider(api_key="secret-sk-12345", base_url="https://api.openai.com/v1", model_name="gpt-4o-mini")
    # Verify str/repr doesn't expose raw secret in standard representations
    assert "secret-sk-12345" not in repr(cloud.get_provider_type())
