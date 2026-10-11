import React, { useState, useEffect } from 'react';
import {
  Settings2,
  Cpu,
  CheckCircle2,
  XCircle,
  Loader2,
  Key,
  Globe,
  RefreshCw,
  Eye,
  EyeOff,
  ExternalLink,
  Sparkles,
  Zap,
} from 'lucide-react';
import { fetchProviders, testProviderConfig, applyProviderSettings, fetchCadEngineStatus } from '../services/api';

const OPENROUTER_MODELS = [
  { id: 'anthropic/claude-3.5-sonnet', label: 'Claude 3.5 Sonnet (Recommended for CAD Code)' },
  { id: 'deepseek/deepseek-chat', label: 'DeepSeek Chat (V3 / Reasoning)' },
  { id: 'meta-llama/llama-3.3-70b-instruct', label: 'Llama 3.3 70B Instruct' },
  { id: 'google/gemini-2.0-flash-001', label: 'Gemini 2.0 Flash 001' },
  { id: 'qwen/qwen-2.5-coder-32b-instruct', label: 'Qwen 2.5 Coder 32B' },
  { id: 'openai/gpt-4o', label: 'OpenAI GPT-4o' },
];

const GOOGLE_STUDIO_MODELS = [
  { id: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash (Recommended - Ultra Fast)' },
  { id: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro (Deep Spatial Reasoning)' },
  { id: 'gemini-1.5-flash', label: 'Gemini 1.5 Flash (Balanced)' },
  { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash (Preview)' },
];

export default function ProviderSettings({ onProviderChanged }) {
  const [isOpen, setIsOpen] = useState(false);
  const [providerType, setProviderType] = useState(() => localStorage.getItem('text2cad_provider') || 'google_studio');

  // Google AI Studio settings
  const [googleStudioApiKey, setGoogleStudioApiKey] = useState(() => localStorage.getItem('text2cad_google_key') || '');
  const [googleStudioBaseUrl, setGoogleStudioBaseUrl] = useState('https://generativelanguage.googleapis.com/v1beta/openai');
  const [googleStudioModel, setGoogleStudioModel] = useState(() => localStorage.getItem('text2cad_google_model') || 'gemini-2.5-flash');
  const [showGoogleKey, setShowGoogleKey] = useState(false);

  // OpenRouter settings
  const [openrouterApiKey, setOpenrouterApiKey] = useState(() => localStorage.getItem('text2cad_openrouter_key') || '');
  const [openrouterBaseUrl, setOpenrouterBaseUrl] = useState('https://openrouter.ai/api/v1');
  const [openrouterModel, setOpenrouterModel] = useState(() => localStorage.getItem('text2cad_openrouter_model') || 'anthropic/claude-3.5-sonnet');
  const [showOpenRouterKey, setShowOpenRouterKey] = useState(false);

  // Ollama settings
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState('http://localhost:11434');
  const [ollamaModel, setOllamaModel] = useState('qwen3:latest');

  // Cloud (Generic / OpenAI) settings
  const [cloudProvider, setCloudProvider] = useState('openai');
  const [cloudApiKey, setCloudApiKey] = useState('');
  const [cloudBaseUrl, setCloudBaseUrl] = useState('https://api.openai.com/v1');
  const [cloudModel, setCloudModel] = useState('gpt-4o-mini');
  const [showCloudKey, setShowCloudKey] = useState(false);

  // Status & testing
  const [testResult, setTestResult] = useState(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [cadEngine, setCadEngine] = useState(null);

  useEffect(() => {
    loadStatus();
  }, []);

  // Broadcast provider info to parent whenever keys or provider change
  useEffect(() => {
    if (onProviderChanged) {
      onProviderChanged({
        provider: providerType,
        google_studio_api_key: googleStudioApiKey,
        google_studio_model: googleStudioModel,
        openrouter_api_key: openrouterApiKey,
        openrouter_model: openrouterModel,
        ollama_base_url: ollamaBaseUrl,
        ollama_model: ollamaModel,
      });
    }
  }, [providerType, googleStudioApiKey, googleStudioModel, openrouterApiKey, openrouterModel]);

  const loadStatus = async () => {
    try {
      // Auto-sync stored credentials from localStorage to backend on mount
      const savedProvider = localStorage.getItem('text2cad_provider') || providerType;
      const savedGoogleKey = localStorage.getItem('text2cad_google_key');
      const savedGoogleModel = localStorage.getItem('text2cad_google_model');
      const savedORKey = localStorage.getItem('text2cad_openrouter_key');
      const savedORModel = localStorage.getItem('text2cad_openrouter_model');

      if (savedGoogleKey || savedORKey || savedProvider) {
        await applyProviderSettings({
          provider: savedProvider,
          google_studio_api_key: savedGoogleKey || undefined,
          google_studio_model: savedGoogleModel || googleStudioModel,
          openrouter_api_key: savedORKey || undefined,
          openrouter_model: savedORModel || openrouterModel,
          ollama_base_url: ollamaBaseUrl,
          ollama_model: ollamaModel,
        }).catch(() => {});
      }

      const providers = await fetchProviders();
      const current = providers.find((p) => p.current);
      if (current && !localStorage.getItem('text2cad_provider')) {
        setProviderType(current.provider_id);
      }
      const cad = await fetchCadEngineStatus();
      setCadEngine(cad);
    } catch (e) {
      console.warn('Could not load status on mount:', e);
    }
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await testProviderConfig({
        provider: providerType,
        google_studio_api_key: googleStudioApiKey || undefined,
        google_studio_base_url: googleStudioBaseUrl,
        google_studio_model: googleStudioModel,
        openrouter_api_key: openrouterApiKey || undefined,
        openrouter_base_url: openrouterBaseUrl,
        openrouter_model: openrouterModel,
        cloud_provider: cloudProvider,
        cloud_api_key: cloudApiKey || undefined,
        cloud_base_url: cloudBaseUrl,
        cloud_model: cloudModel,
        ollama_base_url: ollamaBaseUrl,
        ollama_model: ollamaModel,
      });
      setTestResult(res);
    } catch (e) {
      setTestResult({
        success: false,
        message: e.message || 'Connection test failed',
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleApplySettings = async () => {
    setIsSaving(true);
    try {
      localStorage.setItem('text2cad_provider', providerType);
      if (googleStudioApiKey) localStorage.setItem('text2cad_google_key', googleStudioApiKey);
      if (googleStudioModel) localStorage.setItem('text2cad_google_model', googleStudioModel);
      if (openrouterApiKey) localStorage.setItem('text2cad_openrouter_key', openrouterApiKey);
      if (openrouterModel) localStorage.setItem('text2cad_openrouter_model', openrouterModel);

      await applyProviderSettings({
        provider: providerType,
        google_studio_api_key: googleStudioApiKey || undefined,
        google_studio_base_url: googleStudioBaseUrl,
        google_studio_model: googleStudioModel,
        openrouter_api_key: openrouterApiKey || undefined,
        openrouter_base_url: openrouterBaseUrl,
        openrouter_model: openrouterModel,
        cloud_provider: cloudProvider,
        cloud_api_key: cloudApiKey || undefined,
        cloud_base_url: cloudBaseUrl,
        cloud_model: cloudModel,
        ollama_base_url: ollamaBaseUrl,
        ollama_model: ollamaModel,
      });
      if (onProviderChanged) {
        onProviderChanged({
          provider: providerType,
          google_studio_api_key: googleStudioApiKey,
          google_studio_model: googleStudioModel,
          openrouter_api_key: openrouterApiKey,
          openrouter_model: openrouterModel,
        });
      }
      setIsOpen(false);
    } catch (e) {
      alert(`Failed to save settings: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const getProviderBadge = () => {
    switch (providerType) {
      case 'google_studio':
        return { label: 'Google AI Studio', cls: 'badge-cyan', model: googleStudioModel };
      case 'openrouter':
        return { label: 'OpenRouter', cls: 'badge-success', model: openrouterModel };
      case 'ollama':
        return { label: 'Ollama (Local)', cls: 'badge-cyan', model: ollamaModel };
      case 'cloud':
        return { label: 'OpenAI Cloud', cls: 'badge-success', model: cloudModel };
      case 'mock':
        return { label: 'Mock (Offline)', cls: 'badge-warning', model: 'Deterministic Mock' };
      default:
        return { label: providerType, cls: 'badge-cyan', model: '' };
    }
  };

  const currentBadge = getProviderBadge();

  return (
    <div className="glass-panel" style={{ padding: '16px 20px', marginBottom: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '10px',
              background: 'linear-gradient(135deg, rgba(6,182,212,0.25), rgba(59,130,246,0.25))',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--primary)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <Cpu size={20} />
          </div>
          <div>
            <div style={{ fontSize: '0.9rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span>LLM Engine:</span>
              <span className={`badge ${currentBadge.cls}`}>{currentBadge.label}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem', fontFamily: 'monospace' }}>
                ({currentBadge.model})
              </span>
            </div>
            <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
              CAD Kernel:{' '}
              <strong style={{ color: cadEngine?.runtime_available ? '#34d399' : '#22d3ee' }}>
                {cadEngine?.status || 'Detecting...'}
              </strong>
            </div>
          </div>
        </div>

        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setIsOpen(!isOpen)}
          style={{ gap: '6px' }}
        >
          <Settings2 size={15} />
          {isOpen ? 'Close Settings' : 'Configure Provider & Keys'}
        </button>
      </div>

      {isOpen && (
        <div style={{ marginTop: '18px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
          {/* Provider Selection Tabs */}
          <div style={{ marginBottom: '18px' }}>
            <label
              style={{
                fontSize: '0.8rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                display: 'block',
                marginBottom: '10px',
              }}
            >
              Select Active Inference Engine
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px' }}>
              {[
                {
                  id: 'google_studio',
                  label: 'Google AI Studio',
                  sub: 'Gemini 2.0 Flash / 1.5 Pro',
                  icon: <Sparkles size={14} style={{ color: '#38bdf8' }} />,
                },
                {
                  id: 'openrouter',
                  label: 'OpenRouter',
                  sub: 'Claude 3.5, DeepSeek, Llama',
                  icon: <Zap size={14} style={{ color: '#a78bfa' }} />,
                },
                {
                  id: 'ollama',
                  label: 'Local Ollama',
                  sub: 'Private offline LLM server',
                  icon: <Cpu size={14} style={{ color: '#34d399' }} />,
                },
                {
                  id: 'cloud',
                  label: 'OpenAI API',
                  sub: 'Direct OpenAI endpoint',
                  icon: <Globe size={14} style={{ color: '#fb923c' }} />,
                },
                {
                  id: 'mock',
                  label: 'Offline Mock',
                  sub: 'Deterministic test simulator',
                  icon: <RefreshCw size={14} style={{ color: '#f59e0b' }} />,
                },
              ].map((p) => {
                const isSelected = providerType === p.id;
                return (
                  <div
                    key={p.id}
                    onClick={() => {
                      setProviderType(p.id);
                      setTestResult(null);
                    }}
                    style={{
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-sm)',
                      background: isSelected ? 'rgba(6, 182, 212, 0.14)' : 'rgba(0,0,0,0.3)',
                      border: `1px solid ${isSelected ? 'var(--primary)' : 'var(--border-subtle)'}`,
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
                      {p.icon}
                      <span
                        style={{
                          fontSize: '0.875rem',
                          fontWeight: 600,
                          color: isSelected ? 'var(--primary)' : 'var(--text-primary)',
                        }}
                      >
                        {p.label}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{p.sub}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Google AI Studio Form */}
          {providerType === 'google_studio' && (
            <div
              style={{
                background: 'rgba(56, 189, 248, 0.05)',
                border: '1px solid rgba(56, 189, 248, 0.2)',
                borderRadius: 'var(--radius-sm)',
                padding: '16px',
                marginBottom: '16px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', fontWeight: 600, color: '#38bdf8' }}>
                  <Sparkles size={16} /> Google AI Studio (Gemini) Configuration
                </div>
                <a
                  href="https://aistudio.google.com/apikey"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    fontSize: '0.75rem',
                    color: '#38bdf8',
                    textDecoration: 'none',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  Get API Key <ExternalLink size={12} />
                </a>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                    Gemini API Key
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type={showGoogleKey ? 'text' : 'password'}
                      className="input-field"
                      style={{ paddingRight: '40px', fontFamily: showGoogleKey ? 'monospace' : 'inherit' }}
                      value={googleStudioApiKey}
                      onChange={(e) => setGoogleStudioApiKey(e.target.value)}
                      placeholder="Paste your Google AI Studio key (AIzaSy...)"
                    />
                    <button
                      type="button"
                      onClick={() => setShowGoogleKey(!showGoogleKey)}
                      style={{
                        position: 'absolute',
                        right: '10px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        color: 'var(--text-muted)',
                        cursor: 'pointer',
                      }}
                    >
                      {showGoogleKey ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                      Gemini Model Name
                    </label>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Enter any model name</span>
                  </div>
                  <input
                    type="text"
                    className="input-field"
                    value={googleStudioModel}
                    onChange={(e) => setGoogleStudioModel(e.target.value)}
                    placeholder="e.g. gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-flash"
                    list="gemini-models-list"
                    style={{ fontFamily: 'monospace' }}
                  />
                  <datalist id="gemini-models-list">
                    <option value="gemini-2.5-flash" />
                    <option value="gemini-2.5-pro" />
                    <option value="gemini-2.0-flash" />
                    <option value="gemini-2.0-flash-lite" />
                    <option value="gemini-1.5-flash" />
                    <option value="gemini-1.5-pro" />
                    <option value="gemini-1.5-flash-8b" />
                  </datalist>

                  {/* Quick selection chips */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
                    {['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro'].map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setGoogleStudioModel(m)}
                        style={{
                          fontSize: '0.7rem',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          background: googleStudioModel === m ? 'rgba(56, 189, 248, 0.25)' : 'rgba(255, 255, 255, 0.06)',
                          border: `1px solid ${googleStudioModel === m ? '#38bdf8' : 'rgba(255, 255, 255, 0.1)'}`,
                          color: googleStudioModel === m ? '#38bdf8' : 'var(--text-secondary)',
                          cursor: 'pointer',
                        }}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* OpenRouter Form */}
          {providerType === 'openrouter' && (
            <div
              style={{
                background: 'rgba(167, 139, 250, 0.05)',
                border: '1px solid rgba(167, 139, 250, 0.2)',
                borderRadius: 'var(--radius-sm)',
                padding: '16px',
                marginBottom: '16px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', fontWeight: 600, color: '#a78bfa' }}>
                  <Zap size={16} /> OpenRouter Configuration
                </div>
                <a
                  href="https://openrouter.ai/keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    fontSize: '0.75rem',
                    color: '#a78bfa',
                    textDecoration: 'none',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  Get OpenRouter Key <ExternalLink size={12} />
                </a>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                    OpenRouter API Key
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type={showOpenRouterKey ? 'text' : 'password'}
                      className="input-field"
                      style={{ paddingRight: '40px', fontFamily: showOpenRouterKey ? 'monospace' : 'inherit' }}
                      value={openrouterApiKey}
                      onChange={(e) => setOpenrouterApiKey(e.target.value)}
                      placeholder="sk-or-v1-..."
                    />
                    <button
                      type="button"
                      onClick={() => setShowOpenRouterKey(!showOpenRouterKey)}
                      style={{
                        position: 'absolute',
                        right: '10px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        color: 'var(--text-muted)',
                        cursor: 'pointer',
                      }}
                    >
                      {showOpenRouterKey ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                      OpenRouter Model Name
                    </label>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Enter any model identifier</span>
                  </div>
                  <input
                    type="text"
                    className="input-field"
                    value={openrouterModel}
                    onChange={(e) => setOpenrouterModel(e.target.value)}
                    placeholder="e.g. anthropic/claude-3.5-sonnet, deepseek/deepseek-chat"
                    list="openrouter-models-list"
                    style={{ fontFamily: 'monospace' }}
                  />
                  <datalist id="openrouter-models-list">
                    <option value="anthropic/claude-3.5-sonnet" />
                    <option value="deepseek/deepseek-chat" />
                    <option value="deepseek/deepseek-r1" />
                    <option value="meta-llama/llama-3.3-70b-instruct" />
                    <option value="google/gemini-2.0-flash-001" />
                    <option value="qwen/qwen-2.5-coder-32b-instruct" />
                  </datalist>

                  {/* Quick selection chips */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
                    {['anthropic/claude-3.5-sonnet', 'deepseek/deepseek-chat', 'meta-llama/llama-3.3-70b-instruct'].map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setOpenrouterModel(m)}
                        style={{
                          fontSize: '0.7rem',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          background: openrouterModel === m ? 'rgba(167, 139, 250, 0.25)' : 'rgba(255, 255, 255, 0.06)',
                          border: `1px solid ${openrouterModel === m ? '#a78bfa' : 'rgba(255, 255, 255, 0.1)'}`,
                          color: openrouterModel === m ? '#a78bfa' : 'var(--text-secondary)',
                          cursor: 'pointer',
                        }}
                      >
                        {m.split('/')[1] || m}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Ollama Form */}
          {providerType === 'ollama' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Ollama Server URL
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={ollamaBaseUrl}
                  onChange={(e) => setOllamaBaseUrl(e.target.value)}
                  placeholder="http://localhost:11434"
                />
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Ollama Model Identifier
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  placeholder="qwen3:latest or qwen2.5-coder:7b"
                />
              </div>
            </div>
          )}

          {/* OpenAI Form */}
          {providerType === 'cloud' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  OpenAI API Key
                </label>
                <div style={{ position: 'relative' }}>
                  <input
                    type={showCloudKey ? 'text' : 'password'}
                    className="input-field"
                    style={{ paddingRight: '40px', fontFamily: showCloudKey ? 'monospace' : 'inherit' }}
                    value={cloudApiKey}
                    onChange={(e) => setCloudApiKey(e.target.value)}
                    placeholder="sk-..."
                  />
                  <button
                    type="button"
                    onClick={() => setShowCloudKey(!showCloudKey)}
                    style={{
                      position: 'absolute',
                      right: '10px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                    }}
                  >
                    {showCloudKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Model Identifier
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={cloudModel}
                  onChange={(e) => setCloudModel(e.target.value)}
                  placeholder="gpt-4o-mini or gpt-4o"
                />
              </div>
            </div>
          )}

          {/* Offline Mock notice */}
          {providerType === 'mock' && (
            <div
              style={{
                padding: '12px 14px',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(245, 158, 11, 0.08)',
                border: '1px solid rgba(245, 158, 11, 0.25)',
                color: '#fbbf24',
                fontSize: '0.8rem',
                marginBottom: '16px',
              }}
            >
              Offline Mock Engine active. Extracts specifications and generates FreeCAD code deterministically without external network calls or local server requirements.
            </div>
          )}

          {/* Action Row */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '12px', flexWrap: 'wrap', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleTestConnection}
                disabled={isTesting}
                style={{ gap: '6px' }}
              >
                {isTesting ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
                Test Connection
              </button>

              {testResult && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '0.775rem',
                    color: testResult.success ? '#34d399' : '#f87171',
                  }}
                >
                  {testResult.success ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                  <span>
                    {testResult.message} {testResult.latency_ms ? `(${testResult.latency_ms}ms)` : ''}
                  </span>
                </div>
              )}
            </div>

            <button
              className="btn btn-primary btn-sm"
              onClick={handleApplySettings}
              disabled={isSaving}
              style={{ gap: '6px' }}
            >
              {isSaving ? <Loader2 size={14} className="spin" /> : null}
              Apply Configuration
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
