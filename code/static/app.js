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

const statusDiv = document.getElementById("status");
const messagesDiv = document.getElementById("messages");
const speedSlider = document.getElementById("speedSlider");
// Speed slider is enabled by default - values will be queued until connection is ready
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
        // autoGainControl: true,
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
    .replace(/</g, "<")
    .replace(/>/g, ">")
    .replace(/"/g, "&quot;");
}

// UI Controls

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
      pendingSpeedValue = null; // Clear pending if sent successfully
    } else {
      // Queue the value if socket isn't ready
      pendingSpeedValue = speedValue;
      console.log("Speed value queued (socket not ready):", speedValue);
    }
  });
}

// System prompt and verbosity controls
let pendingSystemPromptUpdate = null;

function sendSystemPromptUpdate(clearHistory = false) {
  const persona = personaSelect.value;
  const verbosityIndex = parseInt(verbositySlider.value);
  const verbosity = verbosityMap[verbosityIndex];
  
  if (socket && socket.readyState === WebSocket.OPEN) {
    // Send system prompt update immediately
    socket.send(JSON.stringify({
      type: 'set_system_prompt',
      persona: persona,
      verbosity: verbosity
    }));
    console.log(`System prompt updated: persona=${persona}, verbosity=${verbosity}`);
    
    // Clear history if persona changed (to ensure clean context)
    if (clearHistory) {
      chatHistory = [];
      typingUser = typingAssistant = "";
      renderMessages();
      socket.send(JSON.stringify({ type: 'clear_history' }));
      console.log("Conversation history cleared due to persona change");
    }
  } else {
    // Queue the update if socket isn't ready
    pendingSystemPromptUpdate = { persona, verbosity, clearHistory };
    console.log(`System prompt update queued: persona=${persona}, verbosity=${verbosity}`);
  }
}

// Persona change handler - clears history to ensure clean context
personaSelect.addEventListener("change", () => {
  const oldPersona = personaSelect.dataset.lastValue || "default";
  const newPersona = personaSelect.value;
  personaSelect.dataset.lastValue = newPersona;
  
  // Clear history when persona changes to ensure the new persona starts fresh
  sendSystemPromptUpdate(clearHistory = true);
  
  // Visual feedback
  const personaName = personaSelect.options[personaSelect.selectedIndex].text;
  console.log(`Persona changed from "${oldPersona}" to "${newPersona}" (${personaName})`);
});

// Verbosity change handler - doesn't clear history
verbositySlider.addEventListener("input", () => {
  sendSystemPromptUpdate(clearHistory = false);
});

document.getElementById("startBtn").onclick = async () => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    statusDiv.textContent = "Already recording.";
    return;
  }
  statusDiv.textContent = "Initializing connection...";

  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${wsProto}//${location.host}/ws`);

  socket.onopen = async () => {
    statusDiv.textContent = "Connected. Activating mic and TTS…";
    await startRawPcmCapture();
    await setupTTSPlayback();
    // Speed slider is always enabled - no need to enable it here
    
    // Initialize persona tracking
    if (!personaSelect.dataset.lastValue) {
      personaSelect.dataset.lastValue = personaSelect.value;
    }
    
    // Send initial system prompt settings
    sendSystemPromptUpdate(clearHistory = false);
    
    // Send any pending speed value that was queued before connection
    if (pendingSpeedValue !== null) {
      socket.send(JSON.stringify({
        type: 'set_speed',
        speed: pendingSpeedValue
      }));
      console.log("Pending speed value applied:", pendingSpeedValue);
      pendingSpeedValue = null;
    } else if (speedSlider) {
      // Send current speed slider value on connection (always send, even if 0)
      const currentSpeed = parseInt(speedSlider.value);
      socket.send(JSON.stringify({
        type: 'set_speed',
        speed: currentSpeed
      }));
      console.log("Initial speed value sent:", currentSpeed);
    }
    
    // Send any pending update that was queued before connection
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
    flushRemainder();
    cleanupAudio();
    // Keep speed slider enabled - values will be queued until reconnected
  };

  socket.onerror = (err) => {
    statusDiv.textContent = "Connection error.";
    cleanupAudio();
    console.error(err);
    // Keep speed slider enabled - values will be queued until reconnected
  };
};

document.getElementById("stopBtn").onclick = () => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    flushRemainder();
    socket.close();
  }
  cleanupAudio();
  statusDiv.textContent = "Stopped.";
};

document.getElementById("copyBtn").onclick = () => {
  const text = chatHistory
    .map(msg => `${msg.role.charAt(0).toUpperCase() + msg.role.slice(1)}: ${msg.content}`)
    .join('\n');
  
  navigator.clipboard.writeText(text)
    .then(() => console.log("Conversation copied to clipboard"))
    .catch(err => console.error("Copy failed:", err));
};

// First render
renderMessages();
