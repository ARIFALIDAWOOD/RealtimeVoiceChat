(function() {
  const originalLog = console.log.bind(console);
  console.log = (...args) => {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    const ms = String(now.getMilliseconds()).padStart(3, '0');
    originalLog(
      `[${hh}:${mm}:${ss}.${ms}]`,
      ...args
    );
  };
})();

// =============================================================================
// API Utility Layer
// =============================================================================

const API_BASE = '/api/v1';

/**
 * Fetch wrapper with automatic auth token handling and refresh
 */
async function apiFetch(endpoint, options = {}) {
  const token = localStorage.getItem('access_token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token && { 'Authorization': `Bearer ${token}` }),
    ...options.headers
  };

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers
  });

  // Handle 401 - try token refresh
  if (response.status === 401 && token) {
    const refreshed = await refreshToken();
    if (refreshed) {
      // Retry with new token
      const newToken = localStorage.getItem('access_token');
      headers['Authorization'] = `Bearer ${newToken}`;
      return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
    }
    // Refresh failed - clear auth and show login
    clearAuthState();
    showAuthModal();
  }

  return response;
}

// =============================================================================
// Authentication Functions
// =============================================================================

/**
 * Register a new user
 */
async function register(email, password) {
  try {
    const response = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'Registration failed');
    }

    // Auto-login after registration
    return await login(email, password);
  } catch (error) {
    console.error('Registration error:', error);
    throw error;
  }
}

/**
 * Login user and store tokens
 */
async function login(email, password) {
  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'Login failed');
    }

    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('token_expires_in', data.expires_in);
    localStorage.setItem('user_email', email);

    // Schedule token refresh
    scheduleTokenRefresh(data.expires_in);

    updateUserStatus();
    hideAuthModal();

    // Load user's sessions
    await loadSessions();

    return data;
  } catch (error) {
    console.error('Login error:', error);
    throw error;
  }
}

/**
 * Refresh access token
 */
async function refreshToken() {
  const currentToken = localStorage.getItem('access_token');
  if (!currentToken) return false;

  try {
    // Note: This implementation uses the access token as refresh token
    // In a production system, you'd have a separate refresh token
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: currentToken })
    });

    if (!response.ok) {
      return false;
    }

    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('token_expires_in', data.expires_in);
    scheduleTokenRefresh(data.expires_in);

    return true;
  } catch (error) {
    console.error('Token refresh error:', error);
    return false;
  }
}

/**
 * Logout user
 */
function logout() {
  clearAuthState();
  updateUserStatus();

  // Clear session-related state
  localStorage.removeItem('current_session_id');
  currentSessionId = null;

  // Clear chat history display
  chatHistory = [];
  typingUser = typingAssistant = "";
  renderMessages();

  // Close WebSocket if connected
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }

  // Clear session list
  const sessionList = document.getElementById('sessionList');
  if (sessionList) {
    sessionList.innerHTML = '<div class="session-item empty">Login to save sessions</div>';
  }

  console.log('User logged out');
}

/**
 * Clear authentication state
 */
function clearAuthState() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('token_expires_in');
  localStorage.removeItem('user_email');

  if (tokenRefreshTimeout) {
    clearTimeout(tokenRefreshTimeout);
    tokenRefreshTimeout = null;
  }
}

let tokenRefreshTimeout = null;

/**
 * Schedule token refresh before expiry
 */
function scheduleTokenRefresh(expiresIn) {
  if (tokenRefreshTimeout) {
    clearTimeout(tokenRefreshTimeout);
  }

  // Refresh 60 seconds before expiry
  const refreshTime = (expiresIn - 60) * 1000;
  if (refreshTime > 0) {
    tokenRefreshTimeout = setTimeout(async () => {
      const success = await refreshToken();
      if (!success) {
        console.log('Token refresh failed, showing login');
        showAuthModal();
      }
    }, refreshTime);
  }
}

/**
 * Get current user info
 */
async function getCurrentUser() {
  try {
    const response = await apiFetch('/auth/me');
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error('Get current user error:', error);
    return null;
  }
}

// =============================================================================
// Session Management Functions
// =============================================================================

let currentSessionId = null;

/**
 * Create a new session
 */
async function createSession(config = null, initialHistory = null) {
  try {
    const body = {};
    if (config) body.config = config;
    if (initialHistory) body.initial_history = initialHistory;

    const response = await apiFetch('/sessions', {
      method: 'POST',
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'Failed to create session');
    }

    const session = await response.json();
    currentSessionId = session.id;
    localStorage.setItem('current_session_id', session.id);

    updateSessionIndicator(session);
    console.log('Session created:', session.id);

    return session;
  } catch (error) {
    console.error('Create session error:', error);
    throw error;
  }
}

/**
 * List user's sessions
 */
async function listSessions(includeExpired = false) {
  try {
    const response = await apiFetch(`/sessions?include_expired=${includeExpired}`);
    if (!response.ok) {
      if (response.status === 401) {
        return { sessions: [], total: 0 };
      }
      throw new Error('Failed to list sessions');
    }
    return await response.json();
  } catch (error) {
    console.error('List sessions error:', error);
    return { sessions: [], total: 0 };
  }
}

/**
 * Get session by ID
 */
async function getSession(sessionId) {
  try {
    const response = await apiFetch(`/sessions/${sessionId}`);
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error('Get session error:', error);
    return null;
  }
}

/**
 * Update session configuration
 */
async function updateSessionConfig(sessionId, configUpdates) {
  try {
    const response = await apiFetch(`/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify(configUpdates)
    });

    if (!response.ok) {
      throw new Error('Failed to update session');
    }

    return await response.json();
  } catch (error) {
    console.error('Update session error:', error);
    throw error;
  }
}

/**
 * Delete/terminate a session
 */
async function deleteSession(sessionId) {
  try {
    const response = await apiFetch(`/sessions/${sessionId}`, {
      method: 'DELETE'
    });

    if (!response.ok && response.status !== 204) {
      throw new Error('Failed to delete session');
    }

    if (currentSessionId === sessionId) {
      currentSessionId = null;
      localStorage.removeItem('current_session_id');
      updateSessionIndicator(null);
    }

    return true;
  } catch (error) {
    console.error('Delete session error:', error);
    throw error;
  }
}

/**
 * Get session history
 */
async function getSessionHistory(sessionId) {
  try {
    const response = await apiFetch(`/sessions/${sessionId}/history`);
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error('Get session history error:', error);
    return null;
  }
}

// =============================================================================
// Configuration API Functions
// =============================================================================

/**
 * Get available personas
 */
async function getPersonas() {
  try {
    const response = await fetch(`${API_BASE}/config/personas`);
    if (!response.ok) throw new Error('Failed to load personas');
    return await response.json();
  } catch (error) {
    console.error('Get personas error:', error);
    return { personas: [] };
  }
}

/**
 * Get available LLM providers
 */
async function getLLMProviders() {
  try {
    const response = await fetch(`${API_BASE}/config/llm-providers`);
    if (!response.ok) throw new Error('Failed to load LLM providers');
    return await response.json();
  } catch (error) {
    console.error('Get LLM providers error:', error);
    return { providers: [] };
  }
}

/**
 * Get available TTS engines
 */
async function getTTSEngines() {
  try {
    const response = await fetch(`${API_BASE}/config/tts-engines`);
    if (!response.ok) throw new Error('Failed to load TTS engines');
    return await response.json();
  } catch (error) {
    console.error('Get TTS engines error:', error);
    return { engines: [] };
  }
}

/**
 * Get available languages
 */
async function getLanguages() {
  try {
    const response = await fetch(`${API_BASE}/config/languages`);
    if (!response.ok) throw new Error('Failed to load languages');
    return await response.json();
  } catch (error) {
    console.error('Get languages error:', error);
    return { languages: [] };
  }
}

/**
 * Get verbosity levels
 */
async function getVerbosityLevels() {
  try {
    const response = await fetch(`${API_BASE}/config/verbosity-levels`);
    if (!response.ok) throw new Error('Failed to load verbosity levels');
    return await response.json();
  } catch (error) {
    console.error('Get verbosity levels error:', error);
    return { levels: [] };
  }
}

/**
 * Load all config options and populate dropdowns
 */
async function loadConfigOptions() {
  try {
    const [personasData, llmData, ttsData, languagesData] = await Promise.all([
      getPersonas(),
      getLLMProviders(),
      getTTSEngines(),
      getLanguages()
    ]);

    populatePersonaDropdown(personasData.personas);
    populateLLMDropdowns(llmData.providers);
    populateTTSDropdowns(ttsData.engines);
    populateLanguageDropdown(languagesData.languages);

    console.log('Config options loaded');
  } catch (error) {
    console.error('Failed to load config options:', error);
  }
}

/**
 * Populate persona dropdown
 */
function populatePersonaDropdown(personas) {
  const select = document.getElementById('personaSelect');
  if (!select || !personas.length) return;

  select.innerHTML = '';
  personas.forEach(persona => {
    const option = document.createElement('option');
    option.value = persona.id;
    option.textContent = persona.name;
    if (persona.description) {
      option.title = persona.description;
    }
    select.appendChild(option);
  });
}

/**
 * Populate LLM provider and model dropdowns
 */
function populateLLMDropdowns(providers) {
  const providerSelect = document.getElementById('llmProviderSelect');
  const modelSelect = document.getElementById('llmModelSelect');
  if (!providerSelect || !modelSelect) return;

  // Store providers data for model updates
  window.llmProviders = providers;

  providerSelect.innerHTML = '';
  providers.forEach(provider => {
    const option = document.createElement('option');
    option.value = provider.id;
    option.textContent = provider.name;
    option.disabled = !provider.available;
    if (!provider.available) {
      option.textContent += ' (Unavailable)';
    }
    providerSelect.appendChild(option);
  });

  // Update models when provider changes
  providerSelect.addEventListener('change', () => {
    updateLLMModels(providerSelect.value);
  });

  // Initial model population
  if (providers.length > 0) {
    updateLLMModels(providers[0].id);
  }
}

/**
 * Update LLM model dropdown based on selected provider
 */
function updateLLMModels(providerId) {
  const modelSelect = document.getElementById('llmModelSelect');
  if (!modelSelect || !window.llmProviders) return;

  const provider = window.llmProviders.find(p => p.id === providerId);
  if (!provider) return;

  modelSelect.innerHTML = '';
  provider.models.forEach(model => {
    const option = document.createElement('option');
    option.value = model;
    option.textContent = model;
    modelSelect.appendChild(option);
  });
}

/**
 * Populate TTS engine and voice dropdowns
 */
function populateTTSDropdowns(engines) {
  const engineSelect = document.getElementById('ttsEngineSelect');
  const voiceSelect = document.getElementById('ttsVoiceSelect');
  if (!engineSelect || !voiceSelect) return;

  // Store engines data for voice updates
  window.ttsEngines = engines;

  engineSelect.innerHTML = '';
  engines.forEach(engine => {
    const option = document.createElement('option');
    option.value = engine.id;
    option.textContent = engine.name;
    option.disabled = !engine.available;
    engineSelect.appendChild(option);
  });

  // Update voices when engine changes
  engineSelect.addEventListener('change', () => {
    updateTTSVoices(engineSelect.value);
  });

  // Initial voice population
  if (engines.length > 0) {
    updateTTSVoices(engines[0].id);
  }
}

/**
 * Update TTS voice dropdown based on selected engine
 */
function updateTTSVoices(engineId) {
  const voiceSelect = document.getElementById('ttsVoiceSelect');
  if (!voiceSelect || !window.ttsEngines) return;

  const engine = window.ttsEngines.find(e => e.id === engineId);
  if (!engine) return;

  voiceSelect.innerHTML = '';
  engine.voices.forEach(voice => {
    const option = document.createElement('option');
    option.value = voice;
    option.textContent = voice;
    voiceSelect.appendChild(option);
  });
}

/**
 * Populate language dropdown
 */
function populateLanguageDropdown(languages) {
  const select = document.getElementById('languageSelect');
  if (!select || !languages) return;

  select.innerHTML = '';
  languages.forEach(lang => {
    const option = document.createElement('option');
    option.value = lang.code;
    option.textContent = lang.name;
    select.appendChild(option);
  });
}

// =============================================================================
// UI Functions
// =============================================================================

/**
 * Show auth modal
 */
function showAuthModal() {
  const modal = document.getElementById('authModal');
  if (modal) {
    modal.classList.add('visible');
  }
}

/**
 * Hide auth modal
 */
function hideAuthModal() {
  const modal = document.getElementById('authModal');
  if (modal) {
    modal.classList.remove('visible');
  }
}

/**
 * Update user status display
 */
function updateUserStatus() {
  const userStatus = document.getElementById('userStatus');
  const userEmail = document.getElementById('userEmail');
  const logoutBtn = document.getElementById('logoutBtn');
  const guestIndicator = document.getElementById('guestIndicator');

  const email = localStorage.getItem('user_email');

  if (email) {
    if (userEmail) userEmail.textContent = email;
    if (logoutBtn) logoutBtn.style.display = 'inline-block';
    if (guestIndicator) guestIndicator.style.display = 'none';
  } else {
    if (userEmail) userEmail.textContent = '';
    if (logoutBtn) logoutBtn.style.display = 'none';
    if (guestIndicator) guestIndicator.style.display = 'inline-block';
  }
}

/**
 * Update session indicator
 */
function updateSessionIndicator(session) {
  const indicator = document.getElementById('sessionIndicator');
  const sessionIdSpan = document.getElementById('currentSessionId');
  const connectionDot = document.getElementById('connectionDot');

  if (session) {
    if (sessionIdSpan) {
      // Show truncated session ID
      sessionIdSpan.textContent = session.id.substring(0, 8) + '...';
      sessionIdSpan.title = session.id;
    }
  } else {
    if (sessionIdSpan) {
      sessionIdSpan.textContent = 'No session';
      sessionIdSpan.title = '';
    }
  }
}

/**
 * Update connection status dot
 */
function updateConnectionDot(connected) {
  const dot = document.getElementById('connectionDot');
  if (dot) {
    dot.className = 'connection-dot ' + (connected ? 'connected' : 'disconnected');
    dot.title = connected ? 'Connected' : 'Disconnected';
  }
}

/**
 * Load and display sessions
 */
async function loadSessions() {
  const sessionList = document.getElementById('sessionList');
  if (!sessionList) return;

  const token = localStorage.getItem('access_token');
  if (!token) {
    sessionList.innerHTML = '<div class="session-item empty">Login to save sessions</div>';
    return;
  }

  sessionList.innerHTML = '<div class="session-item loading">Loading sessions...</div>';

  const data = await listSessions();

  if (data.sessions.length === 0) {
    sessionList.innerHTML = '<div class="session-item empty">No sessions yet</div>';
    return;
  }

  sessionList.innerHTML = '';
  data.sessions.forEach(session => {
    const item = document.createElement('div');
    item.className = 'session-item' + (session.id === currentSessionId ? ' active' : '');

    const created = new Date(session.created_at).toLocaleDateString();
    const persona = session.config.persona || 'default';

    item.innerHTML = `
      <div class="session-info">
        <span class="session-name">${persona}</span>
        <span class="session-date">${created}</span>
      </div>
      <div class="session-actions">
        <button class="session-load" title="Load session">Load</button>
        <button class="session-delete" title="Delete session">×</button>
      </div>
    `;

    // Load button
    item.querySelector('.session-load').onclick = async (e) => {
      e.stopPropagation();
      await loadSession(session.id);
    };

    // Delete button
    item.querySelector('.session-delete').onclick = async (e) => {
      e.stopPropagation();
      if (confirm('Delete this session?')) {
        await deleteSession(session.id);
        await loadSessions();
      }
    };

    sessionList.appendChild(item);
  });
}

/**
 * Load a specific session and restore history
 */
async function loadSession(sessionId) {
  try {
    const session = await getSession(sessionId);
    if (!session) {
      console.error('Session not found');
      return;
    }

    currentSessionId = session.id;
    localStorage.setItem('current_session_id', session.id);
    updateSessionIndicator(session);

    // Load history
    const historyData = await getSessionHistory(sessionId);
    if (historyData && historyData.messages) {
      chatHistory = historyData.messages.map(msg => ({
        role: msg.role,
        content: msg.content,
        type: 'final'
      }));
      renderMessages();
    }

    // Update config UI to match session
    if (session.config) {
      const personaSelect = document.getElementById('personaSelect');
      if (personaSelect && session.config.persona) {
        personaSelect.value = session.config.persona;
      }

      const llmProviderSelect = document.getElementById('llmProviderSelect');
      const llmModelSelect = document.getElementById('llmModelSelect');
      if (llmProviderSelect && session.config.llm_provider) {
        llmProviderSelect.value = session.config.llm_provider;
        updateLLMModels(session.config.llm_provider);
        if (llmModelSelect && session.config.llm_model) {
          llmModelSelect.value = session.config.llm_model;
        }
      }

      const ttsEngineSelect = document.getElementById('ttsEngineSelect');
      const ttsVoiceSelect = document.getElementById('ttsVoiceSelect');
      if (ttsEngineSelect && session.config.tts_engine) {
        ttsEngineSelect.value = session.config.tts_engine;
        updateTTSVoices(session.config.tts_engine);
        if (ttsVoiceSelect && session.config.tts_voice) {
          ttsVoiceSelect.value = session.config.tts_voice;
        }
      }

      // Update verbosity slider
      const verbosityMap = { brief: 0, normal: 1, detailed: 2 };
      const verbositySlider = document.getElementById('verbositySlider');
      if (verbositySlider && session.config.verbosity) {
        verbositySlider.value = verbosityMap[session.config.verbosity] || 1;
      }
    }

    // Refresh session list to highlight current
    await loadSessions();

    console.log('Session loaded:', sessionId);
  } catch (error) {
    console.error('Failed to load session:', error);
  }
}

/**
 * Create a new session and clear UI
 */
async function newSession() {
  // Get current config from UI
  const config = getCurrentConfig();

  try {
    const session = await createSession(config);

    // Clear chat history
    chatHistory = [];
    typingUser = typingAssistant = "";
    renderMessages();

    // Refresh session list
    await loadSessions();

    console.log('New session created:', session.id);
  } catch (error) {
    console.error('Failed to create new session:', error);
  }
}

/**
 * Get current config from UI
 */
function getCurrentConfig() {
  const personaSelect = document.getElementById('personaSelect');
  const verbositySlider = document.getElementById('verbositySlider');
  const llmProviderSelect = document.getElementById('llmProviderSelect');
  const llmModelSelect = document.getElementById('llmModelSelect');
  const ttsEngineSelect = document.getElementById('ttsEngineSelect');
  const ttsVoiceSelect = document.getElementById('ttsVoiceSelect');
  const languageSelect = document.getElementById('languageSelect');

  const verbosityMap = ['brief', 'normal', 'detailed'];

  return {
    persona: personaSelect?.value || 'default',
    verbosity: verbosityMap[parseInt(verbositySlider?.value || 1)],
    llm_provider: llmProviderSelect?.value || 'openai',
    llm_model: llmModelSelect?.value || 'gpt-4o-mini',
    tts_engine: ttsEngineSelect?.value || 'kokoro',
    tts_voice: ttsVoiceSelect?.value || 'af_heart',
    language: languageSelect?.value || 'en'
  };
}

// =============================================================================
// Original Audio/WebSocket Code
// =============================================================================

const statusDiv = document.getElementById("status");
const messagesDiv = document.getElementById("messages");
const speedSlider = document.getElementById("speedSlider");
const personaSelect = document.getElementById("personaSelect");
const verbositySlider = document.getElementById("verbositySlider");

// Verbosity mapping: 0 = brief, 1 = normal, 2 = detailed
const verbosityMap = ["brief", "normal", "detailed"];

let socket = null;
let audioContext = null;
let mediaStream = null;
let micWorkletNode = null;
let ttsWorkletNode = null;

let isTTSPlaying = false;
let ignoreIncomingTTS = false;

let chatHistory = [];
let typingUser = "";
let typingAssistant = "";

// --- batching + fixed 8‑byte header setup ---
const BATCH_SAMPLES = 2048;
const HEADER_BYTES  = 8;
const FRAME_BYTES   = BATCH_SAMPLES * 2;
const MESSAGE_BYTES = HEADER_BYTES + FRAME_BYTES;

const bufferPool = [];
let batchBuffer = null;
let batchView = null;
let batchInt16 = null;
let batchOffset = 0;

function initBatch() {
  if (!batchBuffer) {
    batchBuffer = bufferPool.pop() || new ArrayBuffer(MESSAGE_BYTES);
    batchView   = new DataView(batchBuffer);
    batchInt16  = new Int16Array(batchBuffer, HEADER_BYTES);
    batchOffset = 0;
  }
}

function flushBatch() {
  const ts = Date.now() & 0xFFFFFFFF;
  batchView.setUint32(0, ts, false);
  const flags = isTTSPlaying ? 1 : 0;
  batchView.setUint32(4, flags, false);

  socket.send(batchBuffer);

  bufferPool.push(batchBuffer);
  batchBuffer = null;
}

function flushRemainder() {
  if (batchOffset > 0) {
    for (let i = batchOffset; i < BATCH_SAMPLES; i++) {
      batchInt16[i] = 0;
    }
    flushBatch();
  }
}

function initAudioContext() {
  if (!audioContext) {
    audioContext = new AudioContext();
  }
}

function base64ToInt16Array(b64) {
  const raw = atob(b64);
  const buf = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < raw.length; i++) {
    view[i] = raw.charCodeAt(i);
  }
  return new Int16Array(buf);
}

async function startRawPcmCapture() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: { ideal: 24000 },
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true
      }
    });
    mediaStream = stream;
    initAudioContext();
    await audioContext.audioWorklet.addModule('/static/pcmWorkletProcessor.js');
    micWorkletNode = new AudioWorkletNode(audioContext, 'pcm-worklet-processor');

    micWorkletNode.port.onmessage = ({ data }) => {
      const incoming = new Int16Array(data);
      let read = 0;
      while (read < incoming.length) {
        initBatch();
        const toCopy = Math.min(
          incoming.length - read,
          BATCH_SAMPLES - batchOffset
        );
        batchInt16.set(
          incoming.subarray(read, read + toCopy),
          batchOffset
        );
        batchOffset += toCopy;
        read       += toCopy;
        if (batchOffset === BATCH_SAMPLES) {
          flushBatch();
        }
      }
    };

    const source = audioContext.createMediaStreamSource(stream);
    source.connect(micWorkletNode);
    statusDiv.textContent = "Recording...";
  } catch (err) {
    statusDiv.textContent = "Mic access denied.";
    console.error(err);
  }
}

async function setupTTSPlayback() {
  await audioContext.audioWorklet.addModule('/static/ttsPlaybackProcessor.js');
  ttsWorkletNode = new AudioWorkletNode(
    audioContext,
    'tts-playback-processor'
  );

  ttsWorkletNode.port.onmessage = (event) => {
    const { type } = event.data;
    if (type === 'ttsPlaybackStarted') {
      if (!isTTSPlaying && socket && socket.readyState === WebSocket.OPEN) {
        isTTSPlaying = true;
        console.log(
          "TTS playback started. Reason: ttsWorkletNode Event ttsPlaybackStarted."
        );
        socket.send(JSON.stringify({ type: 'tts_start' }));
      }
    } else if (type === 'ttsPlaybackStopped') {
      if (isTTSPlaying && socket && socket.readyState === WebSocket.OPEN) {
        isTTSPlaying = false;
        console.log(
          "TTS playback stopped. Reason: ttsWorkletNode Event ttsPlaybackStopped."
        );
        socket.send(JSON.stringify({ type: 'tts_stop' }));
      }
    }
  };
  ttsWorkletNode.connect(audioContext.destination);
}

function cleanupAudio() {
  if (micWorkletNode) {
    micWorkletNode.disconnect();
    micWorkletNode = null;
  }
  if (ttsWorkletNode) {
    ttsWorkletNode.disconnect();
    ttsWorkletNode = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  if (mediaStream) {
    mediaStream.getAudioTracks().forEach(track => track.stop());
    mediaStream = null;
  }
}

function renderMessages() {
  messagesDiv.innerHTML = "";
  chatHistory.forEach(msg => {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${msg.role}`;
    bubble.textContent = msg.content;
    messagesDiv.appendChild(bubble);
  });
  if (typingUser) {
    const typing = document.createElement("div");
    typing.className = "bubble user typing";
    typing.innerHTML = typingUser + '<span style="opacity:.6;">✏️</span>';
    messagesDiv.appendChild(typing);
  }
  if (typingAssistant) {
    const typing = document.createElement("div");
    typing.className = "bubble assistant typing";
    typing.innerHTML = typingAssistant + '<span style="opacity:.6;">✏️</span>';
    messagesDiv.appendChild(typing);
  }
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function handleJSONMessage({ type, content }) {
  if (type === "partial_user_request") {
    typingUser = content?.trim() ? escapeHtml(content) : "";
    renderMessages();
    return;
  }
  if (type === "final_user_request") {
    if (content?.trim()) {
      chatHistory.push({ role: "user", content, type: "final" });
    }
    typingUser = "";
    renderMessages();
    return;
  }
  if (type === "partial_assistant_answer") {
    typingAssistant = content?.trim() ? escapeHtml(content) : "";
    renderMessages();
    return;
  }
  if (type === "final_assistant_answer") {
    if (content?.trim()) {
      chatHistory.push({ role: "assistant", content, type: "final" });
    }
    typingAssistant = "";
    renderMessages();
    return;
  }
  if (type === "tts_chunk") {
    if (ignoreIncomingTTS) return;
    const int16Data = base64ToInt16Array(content);
    if (ttsWorkletNode) {
      ttsWorkletNode.port.postMessage(int16Data);
    }
    return;
  }
  if (type === "tts_interruption") {
    if (ttsWorkletNode) {
      ttsWorkletNode.port.postMessage({ type: "clear" });
    }
    isTTSPlaying = false;
    ignoreIncomingTTS = false;
    return;
  }
  if (type === "stop_tts") {
    if (ttsWorkletNode) {
      ttsWorkletNode.port.postMessage({ type: "clear" });
    }
    isTTSPlaying = false;
    ignoreIncomingTTS = true;
    console.log("TTS playback stopped. Reason: tts_interruption.");
    socket.send(JSON.stringify({ type: 'tts_stop' }));
    return;
  }
}

function escapeHtml(str) {
  return (str ?? '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// =============================================================================
// UI Controls
// =============================================================================

document.getElementById("clearBtn").onclick = () => {
  chatHistory = [];
  typingUser = typingAssistant = "";
  renderMessages();
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'clear_history' }));
  }
};

let pendingSpeedValue = null;

if (speedSlider) {
  speedSlider.addEventListener("input", (e) => {
    const speedValue = parseInt(e.target.value);
    console.log("Speed setting changed to:", speedValue);

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: 'set_speed',
        speed: speedValue
      }));
      pendingSpeedValue = null;
    } else {
      pendingSpeedValue = speedValue;
      console.log("Speed value queued (socket not ready):", speedValue);
    }
  });
}

// System prompt and verbosity controls
let pendingSystemPromptUpdate = null;

function sendSystemPromptUpdate(clearHistory = false) {
  const persona = personaSelect?.value || 'default';
  const verbosityIndex = parseInt(verbositySlider?.value || 1);
  const verbosity = verbosityMap[verbosityIndex];

  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({
      type: 'set_system_prompt',
      persona: persona,
      verbosity: verbosity
    }));
    console.log(`System prompt updated: persona=${persona}, verbosity=${verbosity}`);

    if (clearHistory) {
      chatHistory = [];
      typingUser = typingAssistant = "";
      renderMessages();
      socket.send(JSON.stringify({ type: 'clear_history' }));
      console.log("Conversation history cleared due to persona change");
    }

    // Also update session config via API if session exists
    if (currentSessionId) {
      updateSessionConfig(currentSessionId, { persona, verbosity }).catch(err => {
        console.log('Session config update skipped:', err.message);
      });
    }
  } else {
    pendingSystemPromptUpdate = { persona, verbosity, clearHistory };
    console.log(`System prompt update queued: persona=${persona}, verbosity=${verbosity}`);
  }
}

// Persona change handler
if (personaSelect) {
  personaSelect.addEventListener("change", () => {
    const oldPersona = personaSelect.dataset.lastValue || "default";
    const newPersona = personaSelect.value;
    personaSelect.dataset.lastValue = newPersona;

    sendSystemPromptUpdate(true);

    const personaName = personaSelect.options[personaSelect.selectedIndex]?.text || newPersona;
    console.log(`Persona changed from "${oldPersona}" to "${newPersona}" (${personaName})`);
  });
}

// Verbosity change handler
if (verbositySlider) {
  verbositySlider.addEventListener("input", () => {
    sendSystemPromptUpdate(false);
  });
}

// Start button - Connect WebSocket with session_id
document.getElementById("startBtn").onclick = async () => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    statusDiv.textContent = "Already recording.";
    return;
  }
  statusDiv.textContent = "Initializing connection...";

  // Create session if we don't have one
  if (!currentSessionId) {
    try {
      const config = getCurrentConfig();
      const session = await createSession(config);
      currentSessionId = session.id;
    } catch (error) {
      console.log('Creating ephemeral session (not logged in)');
    }
  }

  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = currentSessionId
    ? `${wsProto}//${location.host}/ws?session_id=${currentSessionId}`
    : `${wsProto}//${location.host}/ws`;

  socket = new WebSocket(wsUrl);

  socket.onopen = async () => {
    statusDiv.textContent = "Connected. Activating mic and TTS…";
    updateConnectionDot(true);

    await startRawPcmCapture();
    await setupTTSPlayback();

    if (personaSelect && !personaSelect.dataset.lastValue) {
      personaSelect.dataset.lastValue = personaSelect.value;
    }

    sendSystemPromptUpdate(false);

    if (pendingSpeedValue !== null) {
      socket.send(JSON.stringify({
        type: 'set_speed',
        speed: pendingSpeedValue
      }));
      console.log("Pending speed value applied:", pendingSpeedValue);
      pendingSpeedValue = null;
    } else if (speedSlider) {
      const currentSpeed = parseInt(speedSlider.value);
      socket.send(JSON.stringify({
        type: 'set_speed',
        speed: currentSpeed
      }));
      console.log("Initial speed value sent:", currentSpeed);
    }

    if (pendingSystemPromptUpdate) {
      const { persona, verbosity, clearHistory } = pendingSystemPromptUpdate;
      socket.send(JSON.stringify({
        type: 'set_system_prompt',
        persona: persona,
        verbosity: verbosity
      }));
      if (clearHistory) {
        chatHistory = [];
        typingUser = typingAssistant = "";
        renderMessages();
        socket.send(JSON.stringify({ type: 'clear_history' }));
      }
      pendingSystemPromptUpdate = null;
      console.log("Pending system prompt update applied");
    }
  };

  socket.onmessage = (evt) => {
    if (typeof evt.data === "string") {
      try {
        const msg = JSON.parse(evt.data);
        handleJSONMessage(msg);
      } catch (e) {
        console.error("Error parsing message:", e);
      }
    }
  };

  socket.onclose = () => {
    statusDiv.textContent = "Connection closed.";
    updateConnectionDot(false);
    flushRemainder();
    cleanupAudio();
  };

  socket.onerror = (err) => {
    statusDiv.textContent = "Connection error.";
    updateConnectionDot(false);
    cleanupAudio();
    console.error(err);
  };
};

document.getElementById("stopBtn").onclick = () => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    flushRemainder();
    socket.close();
  }
  cleanupAudio();
  statusDiv.textContent = "Stopped.";
  updateConnectionDot(false);
};

document.getElementById("copyBtn").onclick = () => {
  const text = chatHistory
    .map(msg => `${msg.role.charAt(0).toUpperCase() + msg.role.slice(1)}: ${msg.content}`)
    .join('\n');

  navigator.clipboard.writeText(text)
    .then(() => console.log("Conversation copied to clipboard"))
    .catch(err => console.error("Copy failed:", err));
};

// =============================================================================
// Auth Modal Event Handlers
// =============================================================================

function setupAuthHandlers() {
  // Auth tabs
  const loginTab = document.getElementById('loginTab');
  const registerTab = document.getElementById('registerTab');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const authError = document.getElementById('authError');
  const guestBtn = document.getElementById('guestBtn');
  const logoutBtn = document.getElementById('logoutBtn');
  const newSessionBtn = document.getElementById('newSessionBtn');

  if (loginTab && registerTab) {
    loginTab.addEventListener('click', () => {
      loginTab.classList.add('active');
      registerTab.classList.remove('active');
      if (loginForm) loginForm.classList.remove('hidden');
      if (registerForm) registerForm.classList.add('hidden');
      if (authError) authError.textContent = '';
    });

    registerTab.addEventListener('click', () => {
      registerTab.classList.add('active');
      loginTab.classList.remove('active');
      if (registerForm) registerForm.classList.remove('hidden');
      if (loginForm) loginForm.classList.add('hidden');
      if (authError) authError.textContent = '';
    });
  }

  // Login form
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('loginEmail').value;
      const password = document.getElementById('loginPassword').value;

      try {
        if (authError) authError.textContent = '';
        await login(email, password);
      } catch (error) {
        if (authError) authError.textContent = error.message;
      }
    });
  }

  // Register form
  if (registerForm) {
    registerForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('registerEmail').value;
      const password = document.getElementById('registerPassword').value;
      const confirmPassword = document.getElementById('registerConfirmPassword').value;

      if (password !== confirmPassword) {
        if (authError) authError.textContent = 'Passwords do not match';
        return;
      }

      try {
        if (authError) authError.textContent = '';
        await register(email, password);
      } catch (error) {
        if (authError) authError.textContent = error.message;
      }
    });
  }

  // Guest button
  if (guestBtn) {
    guestBtn.addEventListener('click', () => {
      hideAuthModal();
    });
  }

  // Logout button
  if (logoutBtn) {
    logoutBtn.addEventListener('click', logout);
  }

  // New session button
  if (newSessionBtn) {
    newSessionBtn.addEventListener('click', newSession);
  }

  // Advanced config toggle
  const configToggle = document.getElementById('configToggle');
  const configContent = document.getElementById('configContent');
  if (configToggle && configContent) {
    configToggle.addEventListener('click', () => {
      configContent.classList.toggle('hidden');
      configToggle.classList.toggle('expanded');
    });
  }

  // Session panel toggle
  const sessionToggle = document.getElementById('sessionToggle');
  const sessionPanel = document.getElementById('sessionPanel');
  if (sessionToggle && sessionPanel) {
    sessionToggle.addEventListener('click', () => {
      sessionPanel.classList.toggle('hidden');
      sessionToggle.classList.toggle('expanded');
    });
  }
}

// =============================================================================
// Initialization
// =============================================================================

async function init() {
  // Update user status
  updateUserStatus();

  // Load config options (personas, etc.)
  await loadConfigOptions();

  // Setup auth handlers
  setupAuthHandlers();

  // Check for existing auth
  const token = localStorage.getItem('access_token');
  if (token) {
    // Validate token
    const user = await getCurrentUser();
    if (user) {
      console.log('User authenticated:', user.email);
      await loadSessions();

      // Try to restore last session
      const lastSessionId = localStorage.getItem('current_session_id');
      if (lastSessionId) {
        const session = await getSession(lastSessionId);
        if (session) {
          await loadSession(lastSessionId);
        } else {
          localStorage.removeItem('current_session_id');
        }
      }
    } else {
      // Token invalid
      clearAuthState();
      updateUserStatus();
    }
  }

  // Initial render
  renderMessages();
  updateConnectionDot(false);
  updateSessionIndicator(null);
}

// Run initialization when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
