const API_BASE = '';

export async function fetchProviders() {
  const res = await fetch(`${API_BASE}/providers`);
  if (!res.ok) throw new Error(`Failed to load providers (${res.status})`);
  return res.json();
}

export async function testProviderConfig(payload) {
  const res = await fetch(`${API_BASE}/providers/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Provider test failed (${res.status})`);
  return res.json();
}

export async function applyProviderSettings(payload) {
  const res = await fetch(`${API_BASE}/settings/provider`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to update provider settings (${res.status})`);
  return res.json();
}

export async function fetchCadEngineStatus() {
  const res = await fetch(`${API_BASE}/cad/engine`);
  if (!res.ok) throw new Error(`Failed to fetch CAD engine status (${res.status})`);
  return res.json();
}

export async function initiateGenerateCAD(prompt, mockMode = false, outputFormats = ['STEP', 'STL'], options = {}) {
  const payload = {
    prompt,
    mock_mode: mockMode,
    output_formats: outputFormats,
  };
  if (options.provider) payload.provider = options.provider;
  if (options.model) payload.model = options.model;
  if (options.apiKey) payload.api_key = options.apiKey;
  if (options.baseUrl) payload.base_url = options.baseUrl;

  const res = await fetch(`${API_BASE}/generate-cad`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to initiate generation (${res.status})`);
  }
  return res.json();
}

export async function executeEditedScript(script, expectedDimensions = null, mockMode = false, jobId = null) {
  const res = await fetch(`${API_BASE}/cad/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      job_id: jobId,
      script,
      expected_dimensions: expectedDimensions,
      mock_mode: mockMode,
      output_formats: ['STEP', 'STL'],
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to execute script (${res.status})`);
  }
  return res.json();
}

export async function fetchJobStatus(jobId) {
  const res = await fetch(`${API_BASE}/cad/jobs/${jobId}`);
  if (!res.ok) throw new Error(`Failed to fetch status for job ${jobId}`);
  return res.json();
}

export function getArtifactDownloadUrl(jobId, format) {
  return `${API_BASE}/cad/jobs/${jobId}/artifacts/${format}`;
}

export function getPreviewArtifactUrl(jobId) {
  return `${API_BASE}/cad/jobs/${jobId}/preview`;
}
