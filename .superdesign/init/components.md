# components.md

## Framework Summary
- Framework: Flask + server-rendered HTML template
- Frontend runtime: vanilla JavaScript
- Animation: GSAP (CDN) + CSS keyframes
- CSS approach: single global stylesheet (`static/css/style.css`)
- Component library: custom primitives (no external React/Vue component library)

## Shared UI Primitives Source

### `templates/index.html`
Brief: Contains reusable visual primitives (`.btn`, `.card`, `.view`, `.badge`, drawer structure) and all view sections.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Sauron MedDispenser</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}" />
</head>
<body class="theme-idle">
  <header class="app-header">
    <div class="brand">
      <div class="status-dot" id="globalStatusDot"></div>
      <h1>Sauron <span class="fw-light">MedDispenser</span></h1>
    </div>

    <div class="header-controls">
      <div class="system-badges">
        <span class="badge" id="phaseBadge">PHASE: --</span>
        <span class="badge" id="stateBadge">STATE: --</span>
      </div>
      <button id="audioUnlockBtn" class="btn btn-outline btn-sm" type="button">Enable Voice</button>
    </div>
  </header>

  <main class="app-layout">
    <section class="main-view-container" id="mainStage">
      <div id="transitionOverlay" class="transition-overlay"></div>
      <div id="helloBanner" class="hello-banner">
        <p id="helloText">Hello</p>
      </div>

      <div id="startView" class="view active">
        <div class="view-content center-content">
          <div class="mascot-wrap" aria-hidden="true">
            <div class="mascot-eyes">
              <div class="eye">
                <div class="pupil"></div>
                <div class="glint"></div>
                <div class="lid"></div>
              </div>
              <div class="eye">
                <div class="pupil"></div>
                <div class="glint"></div>
                <div class="lid"></div>
              </div>
            </div>
          </div>
          <h2>Ready to Dispense</h2>
          <p class="subtitle">Tap start or walk near the device to begin.</p>
          <button id="startBtn" class="btn btn-primary btn-xl" type="button" disabled>Start System</button>
        </div>
      </div>

      <div id="monitorView" class="view">
        <div class="view-content center-content">
          <h2>Detecting User</h2>
          <p class="subtitle" id="distanceSubtitle">Please move closer to the camera.</p>
          <div class="camera-container">
            <video id="liveVideo" autoplay playsinline muted></video>
            <div class="scan-line"></div>
            <div class="scan-frame"></div>
          </div>
        </div>
      </div>

      <div id="recognitionView" class="view">
        <div class="view-content">
          <h2>Local Face Recognition</h2>
          <p class="subtitle">Jetson + RealSense local pipeline is active.</p>

          <div class="ring-stage">
            <div class="scan-ring"></div>
          </div>

          <div class="demo-controls">
            <div class="card">
              <h3>Recognized Existing User</h3>
              <select id="existingUserSelect" class="input-modern" disabled></select>
              <button id="existingUserBtn" class="btn btn-success" type="button" disabled>Simulate Login</button>
            </div>
            <div class="divider">OR</div>
            <div class="card">
              <h3>Unknown Face</h3>
              <button id="newUserBtn" class="btn btn-outline" type="button" disabled>Register New User</button>
            </div>
          </div>
        </div>
      </div>

      <div id="registerView" class="view">
        <div class="view-content">
          <h2>New User Registration</h2>
          <p class="subtitle">Capture a face and bind medication + servo channel.</p>
          <form id="registerForm" class="form-grid">
            <div class="input-group">
              <label for="nameInput">Full Name</label>
              <input type="text" id="nameInput" required class="input-modern" placeholder="e.g. Jane Doe" />
            </div>
            <div class="input-group">
              <label for="ageInput">Age</label>
              <input type="number" id="ageInput" class="input-modern" placeholder="Age" />
            </div>
            <div class="input-group">
              <label for="medicationInput">Medication</label>
              <input type="text" id="medicationInput" required class="input-modern" placeholder="e.g. Ibuprofen" />
            </div>
            <div class="input-group">
              <label for="dosageInput">Dosage</label>
              <input type="text" id="dosageInput" class="input-modern" placeholder="e.g. 2 pills" />
            </div>
            <div class="input-group">
              <label for="servoChannelInput">Servo Channel (1-4)</label>
              <input type="number" id="servoChannelInput" min="1" max="4" required class="input-modern" value="1" />
            </div>

            <div class="photo-capture-section">
              <button type="button" id="captureBtn" class="btn btn-outline btn-sm">Capture Face</button>
              <span id="photoStatus" class="micro-text">No photo captured.</span>
              <img id="capturePreview" class="hidden" alt="Face Preview" />
            </div>

            <button type="submit" class="btn btn-primary btn-block">Save Profile</button>
          </form>
        </div>
      </div>

      <div id="workingView" class="view">
        <div class="view-content center-content">
          <h2 id="workingTitle">Dispensing...</h2>
          <p class="subtitle" id="workingSubtitle">Preparing hardware action.</p>
          <div class="spinner"></div>

          <div id="adviceContainer" class="advice-card hidden">
            <h3>Health Advice</h3>
            <p id="adviceText"></p>
            <p class="micro-text text-accent">Auto-closing in <span id="speechRemaining">--</span>s</p>
            <button id="stopAdviceBtn" class="btn btn-outline btn-sm" type="button">Acknowledge</button>
          </div>
        </div>
      </div>

      <div id="errorView" class="view">
        <div class="view-content center-content">
          <div class="icon-error">!</div>
          <h2>System Fault</h2>
          <p class="error-text" id="lastError"></p>
          <button id="resetBtn" class="btn btn-outline mt-4" type="button">Reset System</button>
        </div>
      </div>
    </section>
  </main>

  <button id="debugToggleBtn" class="debug-toggle-btn" type="button">System Panel</button>
  <div id="debugScrim" class="debug-scrim"></div>
  <aside id="debugPanel" class="debug-panel">
    <div class="drawer-header">
      <h3>System Metrics</h3>
      <button id="debugCloseBtn" class="btn btn-outline btn-sm" type="button">Close</button>
    </div>
    <div class="metric-row"><span>UART:</span><strong id="uartVal">--</strong></div>
    <div class="metric-row"><span>Motor Power:</span><strong id="motorPowerVal">--</strong></div>
    <div class="metric-row"><span>Distance:</span><strong id="distanceVal">--</strong><span>/</span><span id="thresholdVal">--</span></div>

    <div class="simulator-box">
      <h4>Distance Simulator</h4>
      <form id="distanceForm" class="flex-row">
        <input type="number" step="0.1" id="distanceInput" class="input-modern input-sm" placeholder="Meters" value="1.0" />
        <button type="submit" id="distanceBtn" class="btn btn-secondary btn-sm" disabled>Update</button>
      </form>
    </div>

    <h4>FSM History</h4>
    <ul id="historyList" class="history-list"></ul>
  </aside>

  <script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"></script>
  <script src="{{ url_for('static', filename='js/app.js') }}"></script>
</body>
</html>


```

### `static/js/app.js`
Brief: Contains reusable UI controllers for view switching, transitions, TTS, and drawer interactions.

```js
const gsapLib = window.gsap || null;

const bodyEl = document.body;
const statusDot = document.getElementById("globalStatusDot");
const phaseBadge = document.getElementById("phaseBadge");
const stateBadge = document.getElementById("stateBadge");
const audioUnlockBtn = document.getElementById("audioUnlockBtn");

const transitionOverlay = document.getElementById("transitionOverlay");
const helloBanner = document.getElementById("helloBanner");
const helloText = document.getElementById("helloText");
const distanceSubtitle = document.getElementById("distanceSubtitle");

const debugPanel = document.getElementById("debugPanel");
const debugScrim = document.getElementById("debugScrim");
const debugToggleBtn = document.getElementById("debugToggleBtn");
const debugCloseBtn = document.getElementById("debugCloseBtn");

const views = {
  WAITING_FOR_USER: document.getElementById("startView"),
  MONITORING_DISTANCE: document.getElementById("monitorView"),
  FACE_RECOGNITION: document.getElementById("recognitionView"),
  REGISTER_NEW_USER: document.getElementById("registerView"),
  WORKING: document.getElementById("workingView"),
  ERROR: document.getElementById("errorView"),
};

const startBtn = document.getElementById("startBtn");
const resetBtn = document.getElementById("resetBtn");
const distanceForm = document.getElementById("distanceForm");
const distanceBtn = document.getElementById("distanceBtn");
const distanceInput = document.getElementById("distanceInput");
const newUserBtn = document.getElementById("newUserBtn");
const existingUserBtn = document.getElementById("existingUserBtn");
const existingUserSelect = document.getElementById("existingUserSelect");
const stopAdviceBtn = document.getElementById("stopAdviceBtn");

const uartVal = document.getElementById("uartVal");
const motorPowerVal = document.getElementById("motorPowerVal");
const distanceVal = document.getElementById("distanceVal");
const thresholdVal = document.getElementById("thresholdVal");
const historyList = document.getElementById("historyList");

const workingTitle = document.getElementById("workingTitle");
const workingSubtitle = document.getElementById("workingSubtitle");
const adviceContainer = document.getElementById("adviceContainer");
const adviceText = document.getElementById("adviceText");
const speechRemaining = document.getElementById("speechRemaining");
const lastError = document.getElementById("lastError");

const liveVideo = document.getElementById("liveVideo");
const captureBtn = document.getElementById("captureBtn");
const capturePreview = document.getElementById("capturePreview");
const photoStatus = document.getElementById("photoStatus");
const registerForm = document.getElementById("registerForm");

let cameraStream = null;
let capturedPhotoDataUrl = "";
let currentViewKey = "WAITING_FOR_USER";
let lastState = "";
let lastGreetingKey = "";
let lastAdviceKey = "";
let typewriterTimer = null;
let transitionTimer = null;
let helloTimer = null;
let drawerOpen = false;

let audioContext = null;
let audioUnlocked = false;
let selectedVoice = null;

function requestJson(url, method = "GET", body = null) {
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== null) {
    options.body = JSON.stringify(body);
  }
  return fetch(url, options).then(async (response) => {
    let payload = {};
    try {
      payload = await response.json();
    } catch (_err) {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(payload.message || `HTTP ${response.status}`);
    }
    return payload;
  });
}

function initializeGsapPrimitives() {
  if (!gsapLib) {
    return;
  }
  gsapLib.set(debugPanel, { xPercent: -108, autoAlpha: 0 });
  gsapLib.set(debugScrim, { autoAlpha: 0 });
}

function switchView(state) {
  let viewKey = "WORKING";
  if (views[state]) {
    viewKey = state;
  }
  if (state === "REGISTRATION_SUCCESS" || state === "SESSION_SUCCESS") {
    viewKey = "WORKING";
  }

  const nextEl = views[viewKey];
  const currentEl = views[currentViewKey];
  if (!nextEl) {
    return;
  }

  if (viewKey !== currentViewKey && currentEl) {
    currentEl.classList.remove("active");
  }
  nextEl.classList.add("active");
  currentViewKey = viewKey;

  if (gsapLib) {
    const target = nextEl.querySelector(".view-content") || nextEl;
    gsapLib.killTweensOf(target);
    gsapLib.fromTo(
      target,
      { y: 18, autoAlpha: 0.72, scale: 0.992 },
      { y: 0, autoAlpha: 1, scale: 1, duration: 0.42, ease: "power3.out" },
    );
  }
}

function runTransitionFlash() {
  if (gsapLib) {
    gsapLib.killTweensOf(transitionOverlay);
    gsapLib.fromTo(
      transitionOverlay,
      { autoAlpha: 0 },
      { autoAlpha: 1, duration: 0.15, yoyo: true, repeat: 1, ease: "power2.out" },
    );
    return;
  }

  transitionOverlay.classList.remove("active");
  if (transitionTimer) {
    clearTimeout(transitionTimer);
  }
  void transitionOverlay.offsetWidth;
  transitionOverlay.classList.add("active");
  transitionTimer = setTimeout(() => {
    transitionOverlay.classList.remove("active");
  }, 420);
}

function setThemeByState(state) {
  bodyEl.classList.remove(
    "theme-idle",
    "theme-monitor",
    "theme-recognition",
    "theme-register",
    "theme-dispense",
    "theme-error",
  );

  if (state === "WAITING_FOR_USER") {
    bodyEl.classList.add("theme-idle");
    return;
  }
  if (state === "MONITORING_DISTANCE") {
    bodyEl.classList.add("theme-monitor");
    return;
  }
  if (state === "FACE_RECOGNITION") {
    bodyEl.classList.add("theme-recognition");
    return;
  }
  if (state === "REGISTER_NEW_USER") {
    bodyEl.classList.add("theme-register");
    return;
  }
  if (state === "ERROR") {
    bodyEl.classList.add("theme-error");
    return;
  }
  bodyEl.classList.add("theme-dispense");
}

function setImmersiveMode(state) {
  const immersive = state === "WAITING_FOR_USER";
  bodyEl.classList.toggle("immersive-mode", immersive);
  if (immersive && drawerOpen) {
    closeDebugDrawer(true);
  }
}

function openDebugDrawer() {
  if (drawerOpen) {
    return;
  }
  drawerOpen = true;
  debugPanel.style.pointerEvents = "auto";
  debugScrim.classList.add("active");
  if (gsapLib) {
    gsapLib.to(debugPanel, { xPercent: 0, autoAlpha: 1, duration: 0.35, ease: "power3.out" });
    gsapLib.to(debugScrim, { autoAlpha: 1, duration: 0.25, ease: "power2.out" });
    return;
  }
  debugPanel.style.transform = "translateX(0)";
  debugPanel.style.opacity = "1";
  debugScrim.style.opacity = "1";
}

function closeDebugDrawer(immediate = false) {
  if (!drawerOpen && !immediate) {
    return;
  }
  drawerOpen = false;
  debugScrim.classList.remove("active");
  if (gsapLib) {
    gsapLib.to(debugPanel, {
      xPercent: -108,
      autoAlpha: 0,
      duration: immediate ? 0 : 0.3,
      ease: "power3.inOut",
      onComplete: () => {
        debugPanel.style.pointerEvents = "none";
      },
    });
    gsapLib.to(debugScrim, { autoAlpha: 0, duration: immediate ? 0 : 0.2 });
    return;
  }
  debugPanel.style.transform = "translateX(-110%)";
  debugPanel.style.opacity = "0";
  debugPanel.style.pointerEvents = "none";
  debugScrim.style.opacity = "0";
}

function toggleDebugDrawer() {
  if (drawerOpen) {
    closeDebugDrawer();
  } else {
    openDebugDrawer();
  }
}

function runIdleIntro() {
  if (!gsapLib) {
    return;
  }
  const mascot = document.querySelector(".mascot-wrap");
  const title = document.querySelector("#startView h2");
  const subtitle = document.querySelector("#startView .subtitle");
  const button = document.querySelector("#startView #startBtn");
  if (!mascot || !title || !subtitle || !button) {
    return;
  }

  const tl = gsapLib.timeline({ defaults: { ease: "power3.out" } });
  tl.fromTo(mascot, { autoAlpha: 0, y: 28, scale: 0.9 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.55 });
  tl.fromTo([title, subtitle], { autoAlpha: 0, y: 16 }, { autoAlpha: 1, y: 0, duration: 0.4, stagger: 0.07 }, "-=0.3");
  tl.fromTo(button, { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, duration: 0.28 }, "-=0.14");
}

function pickVoice() {
  if (!("speechSynthesis" in window)) {
    selectedVoice = null;
    return;
  }
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) {
    selectedVoice = null;
    return;
  }
  selectedVoice =
    voices.find((voice) => voice.lang.toLowerCase().startsWith("en-us")) ||
    voices.find((voice) => voice.lang.toLowerCase().startsWith("en")) ||
    voices[0];
}

function setAudioReadyVisual(ready) {
  if (!audioUnlockBtn) {
    return;
  }
  if (ready) {
    audioUnlockBtn.textContent = "Voice Ready";
    audioUnlockBtn.classList.add("is-ready");
  } else {
    audioUnlockBtn.textContent = "Enable Voice";
    audioUnlockBtn.classList.remove("is-ready");
  }
}

function unlockAudio() {
  if (audioUnlocked) {
    return true;
  }
  try {
    if (!audioContext) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) {
        audioContext = new Ctx();
      }
    }
    if (audioContext && audioContext.state === "suspended") {
      audioContext.resume();
    }
    if ("speechSynthesis" in window) {
      pickVoice();
    }
    audioUnlocked = true;
    setAudioReadyVisual(true);
    return true;
  } catch (_err) {
    audioUnlocked = false;
    setAudioReadyVisual(false);
    return false;
  }
}

function playWakeTone() {
  if (!audioUnlocked || !audioContext) {
    return;
  }
  const now = audioContext.currentTime;
  const osc = audioContext.createOscillator();
  const gain = audioContext.createGain();

  osc.type = "sine";
  osc.frequency.setValueAtTime(420, now);
  osc.frequency.exponentialRampToValueAtTime(700, now + 0.16);

  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.08, now + 0.04);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.24);

  osc.connect(gain);
  gain.connect(audioContext.destination);
  osc.start(now);
  osc.stop(now + 0.24);
}

function speakText(text, options = {}) {
  if (!audioUnlocked || !("speechSynthesis" in window)) {
    return;
  }
  const normalized = String(text || "").trim();
  if (!normalized) {
    return;
  }
  const utterance = new SpeechSynthesisUtterance(normalized);
  utterance.lang = options.lang || "en-US";
  utterance.pitch = options.pitch === undefined ? 1.06 : options.pitch;
  utterance.rate = options.rate === undefined ? 1.0 : options.rate;
  if (selectedVoice) {
    utterance.voice = selectedVoice;
  }
  window.speechSynthesis.speak(utterance);
}

function cancelSpeech() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

function showHello(name) {
  helloText.textContent = `Hello, ${name}`;
  helloBanner.classList.add("show");
  if (gsapLib) {
    gsapLib.fromTo(helloText, { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.24, ease: "power2.out" });
  }
  if (helloTimer) {
    clearTimeout(helloTimer);
  }
  helloTimer = setTimeout(() => {
    helloBanner.classList.remove("show");
  }, 2500);
}

function resetTypewriter() {
  if (typewriterTimer) {
    clearInterval(typewriterTimer);
    typewriterTimer = null;
  }
}

function typewriteAdvice(text) {
  const normalized = String(text || "");
  resetTypewriter();
  adviceText.textContent = "";
  if (!normalized) {
    return;
  }
  let index = 0;
  const step = Math.max(1, Math.ceil(normalized.length / 85));
  typewriterTimer = setInterval(() => {
    index = Math.min(normalized.length, index + step);
    adviceText.textContent = normalized.slice(0, index);
    if (index >= normalized.length) {
      resetTypewriter();
    }
  }, 28);
}

function updateWorkingView(data) {
  adviceContainer.classList.add("hidden");

  if (data.state === "DISPENSING_PILL") {
    workingTitle.textContent = "Dispensing Medication";
    workingSubtitle.textContent = `Sending USB-UART command. Status: ${data.last_uart_result?.status || "Pending"}`;
    return;
  }

  if (data.state === "GENERATING_ADVICE") {
    workingTitle.textContent = "Generating Advice";
    workingSubtitle.textContent = "Preparing personalized suggestions.";
    return;
  }

  if (data.state === "SPEAKING_ADVICE") {
    workingTitle.textContent = "Advice and Guidance";
    workingSubtitle.textContent = "Review and listen to the recommendation.";
    adviceContainer.classList.remove("hidden");
    speechRemaining.textContent =
      data.speech_seconds_remaining === null || data.speech_seconds_remaining === undefined
        ? "--"
        : String(data.speech_seconds_remaining);
    return;
  }

  if (data.state === "SESSION_SUCCESS" || data.state === "REGISTRATION_SUCCESS") {
    workingTitle.textContent = "Complete";
    workingSubtitle.textContent = "Returning to standby.";
    adviceContainer.classList.add("hidden");
    return;
  }

  workingTitle.textContent = "Working";
  workingSubtitle.textContent = "Please wait.";
}

function ensureKnownUsers(users) {
  const list = users || [];
  const previous = existingUserSelect.value;
  existingUserSelect.innerHTML = "";

  for (const user of list) {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = `${user.name} (Ch: ${user.servo_channel || "-"})`;
    existingUserSelect.appendChild(option);
  }

  if (previous && list.some((user) => user.id === previous)) {
    existingUserSelect.value = previous;
  }
  existingUserSelect.disabled = list.length === 0;
}

async function ensureCameraReady() {
  if (cameraStream || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return;
  }
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    liveVideo.srcObject = cameraStream;
  } catch (_err) {
    cameraStream = null;
  }
}

function stopCamera() {
  if (!cameraStream) {
    return;
  }
  for (const track of cameraStream.getTracks()) {
    track.stop();
  }
  cameraStream = null;
  liveVideo.srcObject = null;
}

function handleStateEntryEffects(data) {
  const stateChanged = data.state !== lastState;

  if (stateChanged) {
    runTransitionFlash();
    if (data.state === "MONITORING_DISTANCE") {
      playWakeTone();
    }
    if (data.state === "REGISTER_NEW_USER") {
      speakText("Hi there. Please register to continue.");
    }
    if (data.state === "WAITING_FOR_USER") {
      lastGreetingKey = "";
      lastAdviceKey = "";
      helloBanner.classList.remove("show");
      resetTypewriter();
      adviceText.textContent = "";
      runIdleIntro();
    }
  }

  const user = data.active_user || {};
  if (data.state === "DISPENSING_PILL" && user.name) {
    const greetingKey = `${user.id || user.name}:${data.state}`;
    if (greetingKey !== lastGreetingKey) {
      showHello(user.name);
      speakText(`Hello ${user.name}, dispensing your medication now.`);
      lastGreetingKey = greetingKey;
    }
  }

  if (data.state === "SPEAKING_ADVICE" && data.advice_text) {
    const adviceKey = `${user.id || "anon"}:${data.advice_text}`;
    if (adviceKey !== lastAdviceKey) {
      typewriteAdvice(data.advice_text);
      speakText(data.advice_text, { pitch: 1.0, rate: 0.96 });
      lastAdviceKey = adviceKey;
    }
  }

  if (data.state !== "SPEAKING_ADVICE" && adviceContainer.classList.contains("hidden")) {
    speechRemaining.textContent = "--";
  }

  lastState = data.state;
}

async function renderStatus(data) {
  stateBadge.textContent = `STATE: ${data.state}`;
  phaseBadge.textContent = `PHASE: ${data.phase || "--"}`;
  setThemeByState(data.state);
  setImmersiveMode(data.state);

  const hasError = data.state === "ERROR";
  statusDot.className = `status-dot${hasError ? " error" : ""}`;
  stateBadge.className = `badge ${hasError ? "error" : "active"}`;

  uartVal.textContent = data.uart_transport ? `${data.uart_transport} ${data.uart_port || ""}` : "--";
  motorPowerVal.textContent = data.motor_power_domain || "--";
  distanceVal.textContent =
    data.current_distance_m === null || data.current_distance_m === undefined
      ? "--"
      : Number(data.current_distance_m).toFixed(2);
  thresholdVal.textContent = Number(data.distance_threshold_m || 0).toFixed(2);
  lastError.textContent = data.last_error || "";

  if (distanceSubtitle) {
    if (data.current_distance_m === null || data.current_distance_m === undefined) {
      distanceSubtitle.textContent = "Please move closer to the camera.";
    } else {
      const remaining = Number(data.current_distance_m) - Number(data.distance_threshold_m || 0);
      if (remaining > 0) {
        distanceSubtitle.textContent = `${remaining.toFixed(2)}m remaining to reach threshold.`;
      } else {
        distanceSubtitle.textContent = "Threshold reached. Running local face recognition.";
      }
    }
  }

  ensureKnownUsers(data.known_users || []);

  startBtn.disabled = !data.can_start_monitoring;
  distanceBtn.disabled = !data.can_submit_distance;
  newUserBtn.disabled = !data.can_choose_recognition;
  existingUserBtn.disabled = !data.can_choose_recognition || !existingUserSelect.options.length;
  stopAdviceBtn.disabled = !data.can_stop_advice;
  resetBtn.disabled = !data.can_reset;

  historyList.innerHTML = "";
  const recent = [...(data.history || [])].reverse().slice(0, 12);
  for (const entry of recent) {
    const item = document.createElement("li");
    item.textContent = `[${new Date(entry.timestamp).toLocaleTimeString()}] ${entry.from} -> ${entry.to}`;
    historyList.appendChild(item);
  }

  const needsCamera = ["MONITORING_DISTANCE", "FACE_RECOGNITION", "REGISTER_NEW_USER"].includes(data.state);
  if (needsCamera) {
    await ensureCameraReady();
  } else {
    stopCamera();
  }

  switchView(data.state);
  updateWorkingView(data);
  handleStateEntryEffects(data);
}

async function dispatchAction(endpoint, payload = null) {
  try {
    const data = await requestJson(endpoint, "POST", payload);
    await renderStatus(data);
  } catch (err) {
    console.error("Action error:", err);
  }
}

audioUnlockBtn?.addEventListener("click", () => {
  unlockAudio();
});

document.addEventListener(
  "pointerdown",
  () => {
    unlockAudio();
  },
  { once: true },
);

debugToggleBtn?.addEventListener("click", () => {
  toggleDebugDrawer();
});

debugCloseBtn?.addEventListener("click", () => {
  closeDebugDrawer();
});

debugScrim?.addEventListener("click", () => {
  closeDebugDrawer();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeDebugDrawer();
  }
});

startBtn.addEventListener("click", () => {
  unlockAudio();
  dispatchAction("/api/start-monitoring");
});

resetBtn.addEventListener("click", () => {
  cancelSpeech();
  dispatchAction("/api/reset");
});

distanceForm.addEventListener("submit", (event) => {
  event.preventDefault();
  dispatchAction("/api/distance", { distance_m: Number(distanceInput.value) });
});

existingUserBtn.addEventListener("click", () => {
  if (!existingUserSelect.value) {
    return;
  }
  dispatchAction("/api/recognition/local", {
    match_type: "existing",
    user_id: existingUserSelect.value,
    source: "REALSENSE_LOCAL",
    confidence: 0.93,
  });
});

newUserBtn.addEventListener("click", () => {
  dispatchAction("/api/recognition/local", {
    match_type: "new",
    source: "REALSENSE_LOCAL",
    confidence: 0.2,
  });
});

stopAdviceBtn.addEventListener("click", () => {
  cancelSpeech();
  dispatchAction("/api/stop-advice");
});

captureBtn.addEventListener("click", async () => {
  if (!cameraStream) {
    await ensureCameraReady();
  }
  if (!liveVideo.videoWidth || !liveVideo.videoHeight) {
    photoStatus.textContent = "Camera not ready yet.";
    return;
  }
  const canvas = document.createElement("canvas");
  canvas.width = liveVideo.videoWidth;
  canvas.height = liveVideo.videoHeight;
  const context = canvas.getContext("2d");
  if (!context) {
    photoStatus.textContent = "Could not open capture context.";
    return;
  }
  context.drawImage(liveVideo, 0, 0, canvas.width, canvas.height);
  capturedPhotoDataUrl = canvas.toDataURL("image/jpeg", 0.9);
  capturePreview.src = capturedPhotoDataUrl;
  capturePreview.classList.remove("hidden");
  photoStatus.textContent = "Captured locally.";
});

registerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!capturedPhotoDataUrl) {
    photoStatus.textContent = "Capture a face photo first.";
    return;
  }
  const payload = {
    name: document.getElementById("nameInput").value.trim(),
    age: document.getElementById("ageInput").value.trim(),
    medication: document.getElementById("medicationInput").value.trim(),
    dosage: document.getElementById("dosageInput").value.trim(),
    servo_channel: Number(document.getElementById("servoChannelInput").value || 1),
    photo_data_url: capturedPhotoDataUrl,
  };
  dispatchAction("/api/register", payload);
});

window.addEventListener("beforeunload", () => {
  stopCamera();
  cancelSpeech();
});

if ("speechSynthesis" in window) {
  window.speechSynthesis.addEventListener("voiceschanged", pickVoice);
  pickVoice();
}
setAudioReadyVisual(false);
initializeGsapPrimitives();

async function pollStatus() {
  try {
    const data = await requestJson("/api/status");
    await renderStatus(data);
  } catch (err) {
    console.error("Status polling failed:", err);
  }
}

setInterval(pollStatus, 1000);
pollStatus();


```
