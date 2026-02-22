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
const sceneFrame = document.getElementById("sceneFrame");

const debugPanel = document.getElementById("debugPanel");
const debugScrim = document.getElementById("debugScrim");
const debugToggleBtn = document.getElementById("debugToggleBtn");
const debugCloseBtn = document.getElementById("debugCloseBtn");

const views = {
  WAITING_FOR_USER: document.getElementById("startView"),
  MONITORING_DISTANCE: document.getElementById("monitorView"),
  FACE_RECOGNITION: document.getElementById("recognitionView"),
  REGISTER_NEW_USER: document.getElementById("registerView"),
  DISPENSING_PILL: document.getElementById("dispenseView"),
  GENERATING_ADVICE: document.getElementById("adviceView"),
  SPEAKING_ADVICE: document.getElementById("adviceView"),
  REGISTRATION_SUCCESS: document.getElementById("completionView"),
  SESSION_SUCCESS: document.getElementById("completionView"),
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

const dispenseTitle = document.getElementById("dispenseTitle");
const dispenseSubtitle = document.getElementById("dispenseSubtitle");
const dispenseUserName = document.getElementById("dispenseUserName");
const dispenseMedication = document.getElementById("dispenseMedication");
const dispenseServoChannel = document.getElementById("dispenseServoChannel");
const dispenseUartStatus = document.getElementById("dispenseUartStatus");

const adviceTitle = document.getElementById("adviceTitle");
const adviceSubtitle = document.getElementById("adviceSubtitle");
const adviceLoading = document.getElementById("adviceLoading");
const adviceContainer = document.getElementById("adviceContainer");
const adviceText = document.getElementById("adviceText");
const speechRemaining = document.getElementById("speechRemaining");

const completionTitle = document.getElementById("completionTitle");
const completionSubtitle = document.getElementById("completionSubtitle");
const completionCountdown = document.getElementById("completionCountdown");

const lastError = document.getElementById("lastError");

const liveVideo = document.getElementById("liveVideo");
const captureBtn = document.getElementById("captureBtn");
const capturePreview = document.getElementById("capturePreview");
const photoStatus = document.getElementById("photoStatus");
const registerForm = document.getElementById("registerForm");

const stateLabelMap = {
  WAITING_FOR_USER: "IDLE WELCOME",
  MONITORING_DISTANCE: "WAKE & DETECTION",
  FACE_RECOGNITION: "LOCAL FACE CHECK",
  REGISTER_NEW_USER: "NEW USER REGISTRATION",
  REGISTRATION_SUCCESS: "REGISTRATION COMPLETE",
  DISPENSING_PILL: "DISPENSING & GREETING",
  GENERATING_ADVICE: "GENERATING ADVICE",
  SPEAKING_ADVICE: "ADVICE PLAYBACK",
  SESSION_SUCCESS: "SESSION COMPLETE",
  ERROR: "FAULT & RECOVERY",
};

const sceneSlugMap = {
  WAITING_FOR_USER: "idle",
  MONITORING_DISTANCE: "wake",
  FACE_RECOGNITION: "recognition",
  REGISTER_NEW_USER: "register",
  DISPENSING_PILL: "dispense",
  GENERATING_ADVICE: "advice",
  SPEAKING_ADVICE: "advice",
  REGISTRATION_SUCCESS: "completion",
  SESSION_SUCCESS: "completion",
  ERROR: "fault",
};

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
let activeAudio = null;
let activeAudioUrl = "";
let currentSceneSlug = "";
let lastStatusData = null;
const ELEVENLABS_TTS_ENDPOINT = "/api/tts/elevenlabs";

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

function getSceneSlugForState(state) {
  return sceneSlugMap[state] || "idle";
}

function getSceneDocument() {
  try {
    if (!sceneFrame || !sceneFrame.contentWindow) {
      return null;
    }
    return sceneFrame.contentDocument || sceneFrame.contentWindow.document || null;
  } catch (_err) {
    return null;
  }
}

function updateSceneFrame(state) {
  if (!sceneFrame) {
    return;
  }
  const slug = getSceneSlugForState(state);
  if (slug === currentSceneSlug) {
    return;
  }
  currentSceneSlug = slug;
  sceneFrame.src = `/ui-scene/${slug}`;
}

function bindSceneClick(doc, id, handler) {
  const el = doc.getElementById(id);
  if (!el || el.dataset.shellBound === "1") {
    return el;
  }
  el.dataset.shellBound = "1";
  el.addEventListener("click", (event) => {
    event.preventDefault();
    handler(event, el);
  });
  return el;
}

function parseServoChannelFromScene(selectEl) {
  if (!selectEl) {
    return 1;
  }
  const text = `${selectEl.value || ""} ${selectEl.options?.[selectEl.selectedIndex]?.text || ""}`;
  const match = text.match(/channel\s*0*([1-4])/i) || text.match(/\b([1-4])\b/);
  return match ? Number(match[1]) : 1;
}

function buildFallbackPhotoDataUrl() {
  const canvas = document.createElement("canvas");
  canvas.width = 160;
  canvas.height = 120;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return "";
  }
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, "#17386a");
  gradient.addColorStop(1, "#58c3ff");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "rgba(255,255,255,0.18)";
  ctx.beginPath();
  ctx.arc(80, 46, 22, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.roundRect?.(40, 74, 80, 28, 12);
  if (!ctx.roundRect) {
    ctx.fillRect(40, 74, 80, 28);
  }
  ctx.fill();
  return canvas.toDataURL("image/jpeg", 0.82);
}

async function capturePhotoFromLiveVideo() {
  if (!cameraStream) {
    await ensureCameraReady();
  }
  if (!liveVideo.videoWidth || !liveVideo.videoHeight) {
    return "";
  }
  const canvas = document.createElement("canvas");
  canvas.width = liveVideo.videoWidth;
  canvas.height = liveVideo.videoHeight;
  const context = canvas.getContext("2d");
  if (!context) {
    return "";
  }
  context.drawImage(liveVideo, 0, 0, canvas.width, canvas.height);
  const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
  capturedPhotoDataUrl = dataUrl;
  if (capturePreview) {
    capturePreview.src = dataUrl;
    capturePreview.classList.remove("hidden");
  }
  if (photoStatus) {
    photoStatus.textContent = "Captured locally.";
  }
  return dataUrl;
}

async function submitRegistrationFromScene() {
  const doc = getSceneDocument();
  if (!doc) {
    return;
  }
  const inputs = [...doc.querySelectorAll("input.input-field")];
  const select = doc.querySelector("select.input-field");
  const [nameInputEl, ageInputEl, medicationInputEl, dosageInputEl] = inputs;

  const name = (nameInputEl?.value || "").trim() || "Demo User";
  const age = (ageInputEl?.value || "").trim();
  const medication = (medicationInputEl?.value || "").trim() || "Ibuprofen";
  const dosage = (dosageInputEl?.value || "").trim() || "1 pill";
  const servoChannel = parseServoChannelFromScene(select);

  let photo = capturedPhotoDataUrl;
  if (!photo) {
    photo = await capturePhotoFromLiveVideo();
  }
  if (!photo) {
    photo = buildFallbackPhotoDataUrl();
    capturedPhotoDataUrl = photo;
    if (photoStatus) {
      photoStatus.textContent = "Using generated placeholder face image (demo).";
    }
  }

  await dispatchAction("/api/register", {
    name,
    age,
    medication,
    dosage,
    servo_channel: servoChannel,
    photo_data_url: photo,
  });
}

async function captureRegistrationFaceFromScene(triggerEl) {
  let photo = await capturePhotoFromLiveVideo();
  if (!photo) {
    photo = buildFallbackPhotoDataUrl();
    capturedPhotoDataUrl = photo;
    if (photoStatus) {
      photoStatus.textContent = "Camera unavailable, using demo placeholder image.";
    }
  }
  if (triggerEl) {
    triggerEl.textContent = "Face Data Captured";
    triggerEl.classList.add("opacity-80");
  }
}

function bindSceneInteractions(data) {
  const doc = getSceneDocument();
  if (!doc || !data) {
    return;
  }

  bindSceneClick(doc, "cta-start-session", () => {
    unlockAudio();
    dispatchAction("/api/start-monitoring");
  });

  bindSceneClick(doc, "proceed-to-scan-link", () => {
    const threshold = Number(data.distance_threshold_m || 0.7);
    dispatchAction("/api/distance", { distance_m: Math.max(0.2, threshold - 0.05) });
  });

  bindSceneClick(doc, "sim-match-link", () => {
    if (!existingUserSelect?.value) {
      return;
    }
    dispatchAction("/api/recognition/local", {
      match_type: "existing",
      user_id: existingUserSelect.value,
      source: "REALSENSE_LOCAL",
      confidence: 0.93,
    });
  });

  bindSceneClick(doc, "sim-no-match-link", () => {
    dispatchAction("/api/recognition/local", {
      match_type: "new",
      source: "REALSENSE_LOCAL",
      confidence: 0.2,
    });
  });

  bindSceneClick(doc, "cancel-registration", () => {
    cancelSpeech();
    dispatchAction("/api/reset");
  });

  bindSceneClick(doc, "submit-registration", async () => {
    await submitRegistrationFromScene();
  });

  bindSceneClick(doc, "next-advice-link", () => {
    // FSM auto-progresses after dispense; no manual transition endpoint needed here.
  });

  bindSceneClick(doc, "report-issue-link", () => {
    dispatchAction("/api/reset");
  });

  bindSceneClick(doc, "finish-btn", () => {
    if (data.state === "SPEAKING_ADVICE") {
      cancelSpeech();
      dispatchAction("/api/stop-advice");
      return;
    }
    if (data.state === "REGISTRATION_SUCCESS" || data.state === "SESSION_SUCCESS" || data.state === "ERROR") {
      cancelSpeech();
      dispatchAction("/api/reset");
    }
  });

  bindSceneClick(doc, "recovery-retry-link", () => {
    cancelSpeech();
    dispatchAction("/api/reset");
  });

  bindSceneClick(doc, "recovery-cancel-link", () => {
    cancelSpeech();
    dispatchAction("/api/reset");
  });

  bindSceneClick(doc, "support-link", () => {
    // Placeholder action for local prototype.
  });

  const registerCaptureBtn = [...doc.querySelectorAll("button")]
    .find((button) => /capture face data/i.test(button.textContent || ""));
  if (registerCaptureBtn && registerCaptureBtn.dataset.shellBound !== "1") {
    registerCaptureBtn.dataset.shellBound = "1";
    registerCaptureBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      await captureRegistrationFaceFromScene(registerCaptureBtn);
    });
  }
}

function syncSceneContent(data) {
  const doc = getSceneDocument();
  if (!doc || !data) {
    return;
  }
  const state = data.state;
  const user = data.active_user || {};

  if (state === "DISPENSING_PILL") {
    const heading = doc.querySelector("h2");
    const nameAccent = heading?.querySelector("span");
    if (nameAccent) {
      nameAccent.textContent = user.name || "User";
    }
    const progressStatus = [...doc.querySelectorAll("*")]
      .find((el) => /UART Buffer/i.test(el.textContent || ""));
    if (progressStatus && progressStatus.nextElementSibling) {
      progressStatus.nextElementSibling.textContent = `${data.last_uart_result?.status || "Pending"}`;
    }
  }

  if (state === "SPEAKING_ADVICE" || state === "GENERATING_ADVICE") {
    const adviceEl = doc.getElementById("advice-text");
    if (adviceEl && state === "SPEAKING_ADVICE" && data.advice_text) {
      adviceEl.textContent = data.advice_text;
    }
    const timerEl = doc.getElementById("session-timer");
    if (timerEl) {
      const seconds =
        data.speech_seconds_remaining === null || data.speech_seconds_remaining === undefined
          ? null
          : Number(data.speech_seconds_remaining);
      if (seconds === null || Number.isNaN(seconds)) {
        timerEl.textContent = state === "GENERATING_ADVICE" ? "--:--" : timerEl.textContent;
      } else {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        timerEl.textContent = `${mins}:${String(secs).padStart(2, "0")}`;
      }
    }
  }

  if (state === "SESSION_SUCCESS" || state === "REGISTRATION_SUCCESS") {
    const countdownText = [...doc.querySelectorAll("div,p,span")]
      .find((el) => /Auto-closing in/i.test(el.textContent || ""));
    if (countdownText) {
      const seconds =
        data.auto_return_seconds === null || data.auto_return_seconds === undefined
          ? "--"
          : String(data.auto_return_seconds);
      countdownText.textContent = `Auto-closing in ${seconds}s`;
    }
  }
}

function initializeGsapPrimitives() {
  if (!gsapLib) {
    return;
  }
  gsapLib.set(debugPanel, { xPercent: -108, autoAlpha: 0 });
  gsapLib.set(debugScrim, { autoAlpha: 0 });
}

function switchView(state) {
  const viewKey = views[state] ? state : "WAITING_FOR_USER";

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
    "theme-success",
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
  if (state === "REGISTRATION_SUCCESS" || state === "SESSION_SUCCESS") {
    bodyEl.classList.add("theme-success");
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

function revokeActiveAudioUrl() {
  if (!activeAudioUrl) {
    return;
  }
  try {
    URL.revokeObjectURL(activeAudioUrl);
  } catch (_err) {
    // ignore cleanup errors
  }
  activeAudioUrl = "";
}

function clearActiveAudio() {
  if (activeAudio) {
    try {
      activeAudio.pause();
    } catch (_err) {
      // ignore pause failures
    }
    activeAudio = null;
  }
  revokeActiveAudioUrl();
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
  if (!audioUnlocked) {
    return;
  }
  const normalized = String(text || "").trim();
  if (!normalized) {
    return;
  }
  cancelSpeech();

  fetch(`${ELEVENLABS_TTS_ENDPOINT}?_=${Date.now()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: normalized }),
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.blob();
    })
    .then((blob) => {
      if (!(blob instanceof Blob) || blob.size <= 0) {
        throw new Error("empty audio");
      }
      clearActiveAudio();
      const objectUrl = URL.createObjectURL(blob);
      activeAudio = new Audio(objectUrl);
      activeAudioUrl = objectUrl;
      activeAudio.onended = () => clearActiveAudio();
      activeAudio.onerror = () => clearActiveAudio();
      return activeAudio.play();
    })
    .catch(() => {
      clearActiveAudio();
      if (!("speechSynthesis" in window)) {
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
    });
}

function cancelSpeech() {
  clearActiveAudio();
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

function updateDispenseView(data) {
  const user = data.active_user || {};
  const uartStatus = data.last_uart_result?.status || data.last_uart_command?.status || "Pending";

  if (dispenseUserName) {
    dispenseUserName.textContent = user.name || "--";
  }
  if (dispenseMedication) {
    dispenseMedication.textContent = user.medication || "--";
  }
  if (dispenseServoChannel) {
    dispenseServoChannel.textContent = String(user.servo_channel || "--");
  }
  if (dispenseUartStatus) {
    dispenseUartStatus.textContent = String(uartStatus);
  }

  if (data.state === "DISPENSING_PILL") {
    if (dispenseTitle) {
      dispenseTitle.textContent = user.name ? `Dispensing for ${user.name}` : "Dispensing Medication";
    }
    if (dispenseSubtitle) {
      dispenseSubtitle.textContent = `Sending USB-UART command to ESP32. Status: ${uartStatus}`;
    }
    return;
  }

  if (dispenseTitle) {
    dispenseTitle.textContent = "Dispensing Medication";
  }
  if (dispenseSubtitle) {
    dispenseSubtitle.textContent = "Sending USB-UART command to ESP32.";
  }
}

function updateAdviceView(data) {
  const isGenerating = data.state === "GENERATING_ADVICE";
  const isSpeaking = data.state === "SPEAKING_ADVICE";

  adviceLoading?.classList.toggle("hidden", !isGenerating);
  adviceContainer?.classList.toggle("hidden", !isSpeaking);

  if (isGenerating) {
    if (adviceTitle) {
      adviceTitle.textContent = "Generating Advice";
    }
    if (adviceSubtitle) {
      adviceSubtitle.textContent = "Preparing personalized guidance and voice playback.";
    }
    speechRemaining.textContent = "--";
    return;
  }

  if (isSpeaking) {
    if (adviceTitle) {
      adviceTitle.textContent = "Advice and Voice Playback";
    }
    if (adviceSubtitle) {
      adviceSubtitle.textContent = "Review and listen to the recommendation.";
    }
    speechRemaining.textContent =
      data.speech_seconds_remaining === null || data.speech_seconds_remaining === undefined
        ? "--"
        : String(data.speech_seconds_remaining);
    return;
  }

  adviceLoading?.classList.add("hidden");
  adviceContainer?.classList.add("hidden");
}

function updateCompletionView(data) {
  const remaining = data.auto_return_seconds === null || data.auto_return_seconds === undefined
    ? "--"
    : String(data.auto_return_seconds);

  if (completionCountdown) {
    completionCountdown.textContent = remaining;
  }

  if (data.state === "REGISTRATION_SUCCESS") {
    if (completionTitle) {
      completionTitle.textContent = "Registration Complete";
    }
    if (completionSubtitle) {
      completionSubtitle.textContent = "Profile saved locally. Returning to standby.";
    }
    return;
  }

  if (data.state === "SESSION_SUCCESS") {
    if (completionTitle) {
      completionTitle.textContent = "Dispense Complete";
    }
    if (completionSubtitle) {
      completionSubtitle.textContent = "Medication session finished. Returning to standby.";
    }
    return;
  }

  if (completionTitle) {
    completionTitle.textContent = "Complete";
  }
  if (completionSubtitle) {
    completionSubtitle.textContent = "Returning to standby.";
  }
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
    if (data.state === "GENERATING_ADVICE") {
      resetTypewriter();
      adviceText.textContent = "";
      speechRemaining.textContent = "--";
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

  if (data.state !== "SPEAKING_ADVICE") {
    speechRemaining.textContent = "--";
  }

  lastState = data.state;
}

async function renderStatus(data) {
  lastStatusData = data;
  const stateLabel = stateLabelMap[data.state] || data.state;
  stateBadge.textContent = `STATE: ${stateLabel}`;
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

  updateSceneFrame(data.state);
  switchView(data.state);
  updateDispenseView(data);
  updateAdviceView(data);
  updateCompletionView(data);
  bindSceneInteractions(data);
  syncSceneContent(data);
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
sceneFrame?.addEventListener("load", () => {
  if (!lastStatusData) {
    return;
  }
  bindSceneInteractions(lastStatusData);
  syncSceneContent(lastStatusData);
});
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
