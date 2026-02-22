(function () {
  const stateToSlug = {
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

  let latestStatus = null;
  let capturedPhotoDataUrl = "";
  let pollTimer = null;
  let audioUnlocked = false;
  let selectedVoice = null;
  let lastSpokenAdviceKey = "";
  let lastGreetingKey = "";
  const AUDIO_UNLOCK_KEY = "sauron_scene_audio_unlocked";
  const COMPLETION_HOLD_UNTIL_KEY = "sauron_completion_hold_until_ms";
  let runtimePanelReady = false;
  let runtimePanelOpen = false;
  let greetingHoldUntilMs = 0;

  function currentSlug() {
    const parts = window.location.pathname.split("/").filter(Boolean);
    return (parts[parts.length - 1] || "idle").toLowerCase();
  }

  function targetSlugFromState(state) {
    return stateToSlug[state] || "idle";
  }

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

  function setText(selectorOrEl, text) {
    const el = typeof selectorOrEl === "string" ? document.querySelector(selectorOrEl) : selectorOrEl;
    if (el) {
      el.textContent = text;
    }
    return el;
  }

  function estimateSpeechMs(text, rate = 1) {
    const content = String(text || "").trim();
    if (!content) {
      return 0;
    }
    const words = content.split(/\s+/).filter(Boolean).length || 1;
    const wordsPerSecond = 2.6 * Math.max(0.5, Number(rate) || 1);
    return Math.round((words / wordsPerSecond) * 1000 + 500);
  }

  function setCompletionHold(seconds) {
    const n = Number(seconds);
    if (!Number.isFinite(n) || n <= 0) {
      return;
    }
    try {
      window.sessionStorage.setItem(COMPLETION_HOLD_UNTIL_KEY, String(Date.now() + Math.round(n * 1000)));
    } catch (_err) {
      // ignore storage failures
    }
  }

  function getCompletionHoldRemainingSeconds() {
    try {
      const raw = window.sessionStorage.getItem(COMPLETION_HOLD_UNTIL_KEY);
      if (!raw) {
        return null;
      }
      const until = Number(raw);
      if (!Number.isFinite(until)) {
        return null;
      }
      const remainingMs = until - Date.now();
      return Math.max(0, Math.ceil(remainingMs / 1000));
    } catch (_err) {
      return null;
    }
  }

  function clearCompletionHold() {
    try {
      window.sessionStorage.removeItem(COMPLETION_HOLD_UNTIL_KEY);
    } catch (_err) {
      // ignore storage failures
    }
  }

  function ensureRuntimePanel() {
    if (runtimePanelReady) {
      return;
    }
    runtimePanelReady = true;

    if (!document.getElementById("runtime-panel-style")) {
      const style = document.createElement("style");
      style.id = "runtime-panel-style";
      style.textContent = [
        "#debug-drawer,#debug-side-drawer,#scrim,#page-scrim{display:none !important;}",
        "#runtimeDebugScrim{position:fixed;inset:0;background:rgba(2,8,24,.6);z-index:2147483000;opacity:0;pointer-events:none;transition:opacity .2s ease;}",
        "#runtimeDebugScrim.active{opacity:1;pointer-events:auto;}",
        "#runtimeDebugPanel{position:fixed;left:0;top:0;bottom:0;width:min(360px,92vw);z-index:2147483001;background:rgba(12,22,42,.94);backdrop-filter:blur(10px);border-right:1px solid rgba(255,255,255,.12);transform:translateX(-102%);transition:transform .22s ease;color:#ecf4ff;font-family:system-ui,sans-serif;display:flex;flex-direction:column;}",
        "#runtimeDebugPanel.open{transform:translateX(0);}",
        "#runtimeDebugPanel .rt-head{display:flex;align-items:center;justify-content:space-between;padding:14px 14px 10px;border-bottom:1px solid rgba(255,255,255,.08);}",
        "#runtimeDebugPanel .rt-title{font-weight:700;font-size:14px;letter-spacing:.02em;}",
        "#runtimeDebugPanel .rt-close{border:1px solid rgba(255,255,255,.12);background:transparent;color:#ecf4ff;border-radius:10px;padding:6px 9px;cursor:pointer;}",
        "#runtimeDebugPanel .rt-body{padding:12px 14px;overflow:auto;display:grid;gap:10px;}",
        "#runtimeDebugPanel .rt-grid{display:grid;gap:8px;}",
        "#runtimeDebugPanel .rt-row{display:grid;grid-template-columns:1fr auto;gap:10px;padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);font-size:12px;}",
        "#runtimeDebugPanel .rt-row span{color:#9ab0cb;}",
        "#runtimeDebugPanel .rt-row strong{color:#ecf4ff;font-weight:600;max-width:180px;text-align:right;word-break:break-word;}",
        "#runtimeDebugPanel .rt-actions{display:flex;gap:8px;}",
        "#runtimeDebugPanel .rt-btn{flex:1;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.04);color:#ecf4ff;border-radius:10px;padding:8px 10px;font-weight:600;cursor:pointer;}",
        "#runtimeDebugPanel .rt-btn.primary{background:#58c3ff;color:#06203b;border-color:transparent;}",
        "#runtimeDebugPanel .rt-small{font-size:11px;color:#9ab0cb;line-height:1.35;}",
      ].join("");
      document.head.appendChild(style);
    }

    if (!document.getElementById("runtimeDebugScrim")) {
      const scrim = document.createElement("div");
      scrim.id = "runtimeDebugScrim";
      document.body.appendChild(scrim);
    }

    if (!document.getElementById("runtimeDebugPanel")) {
      const panel = document.createElement("aside");
      panel.id = "runtimeDebugPanel";
      panel.innerHTML = [
        '<div class="rt-head">',
        '  <div class="rt-title">System Panel</div>',
        '  <button class="rt-close" id="runtimeDebugClose" type="button">Close</button>',
        "</div>",
        '<div class="rt-body">',
        '  <div class="rt-grid" id="runtimeDebugGrid"></div>',
        '  <div class="rt-actions">',
        '    <button class="rt-btn" id="runtimeDebugRefresh" type="button">Refresh</button>',
        '    <button class="rt-btn primary" id="runtimeDebugReset" type="button">Reset</button>',
        "  </div>",
        '  <div class="rt-small" id="runtimeDebugHint">Local FSM status for kiosk debugging.</div>',
        "</div>",
      ].join("");
      document.body.appendChild(panel);
    }

    document.getElementById("runtimeDebugClose")?.addEventListener("click", () => closeRuntimePanel());
    document.getElementById("runtimeDebugScrim")?.addEventListener("click", () => closeRuntimePanel());
    document.getElementById("runtimeDebugRefresh")?.addEventListener("click", () => pollStatus());
    document.getElementById("runtimeDebugReset")?.addEventListener("click", async () => {
      cancelSpeech();
      await dispatchAction("/api/reset");
      closeRuntimePanel();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeRuntimePanel();
      }
    });
  }

  function updateRuntimePanel(status) {
    ensureRuntimePanel();
    const grid = document.getElementById("runtimeDebugGrid");
    if (!grid || !status) {
      return;
    }
    const rows = [
      ["State", status.state || "--"],
      ["Phase", status.phase || "--"],
      ["Scene", currentSlug()],
      ["UART", `${status.uart_transport || "--"} ${status.uart_port || ""}`.trim()],
      ["Motor", status.motor_power_domain || "--"],
      ["Distance", status.current_distance_m == null ? "--" : Number(status.current_distance_m).toFixed(2)],
      ["Threshold", status.distance_threshold_m == null ? "--" : Number(status.distance_threshold_m).toFixed(2)],
      ["User", status.active_user?.name || "--"],
      ["Medication", status.active_user?.medication || "--"],
      ["TTS", status.is_speaking ? "Speaking" : "Idle"],
    ];
    if (status.last_error) {
      rows.push(["Last Error", status.last_error]);
    }
    grid.innerHTML = rows
      .map(([k, v]) => `<div class="rt-row"><span>${String(k)}</span><strong>${String(v)}</strong></div>`)
      .join("");
  }

  function openRuntimePanel() {
    ensureRuntimePanel();
    runtimePanelOpen = true;
    document.getElementById("runtimeDebugPanel")?.classList.add("open");
    document.getElementById("runtimeDebugScrim")?.classList.add("active");
  }

  function closeRuntimePanel() {
    runtimePanelOpen = false;
    document.getElementById("runtimeDebugPanel")?.classList.remove("open");
    document.getElementById("runtimeDebugScrim")?.classList.remove("active");
  }

  function toggleRuntimePanel() {
    if (runtimePanelOpen) {
      closeRuntimePanel();
    } else {
      openRuntimePanel();
    }
  }

  function bindDebugTriggers() {
    ensureRuntimePanel();
    ["debug-trigger", "debug-btn-trigger"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el || el.dataset.runtimeDebugBound === "1") {
        return;
      }
      el.dataset.runtimeDebugBound = "1";
      el.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (typeof event.stopImmediatePropagation === "function") {
            event.stopImmediatePropagation();
          }
          unlockAudio();
          toggleRuntimePanel();
        },
        true,
      );
    });
  }

  function bindClick(id, handler) {
    const el = document.getElementById(id);
    if (!el || el.dataset.localBound === "1") {
      return el;
    }
    el.dataset.localBound = "1";
    el.addEventListener("click", (event) => {
      event.preventDefault();
      unlockAudio();
      handler(event, el);
    });
    return el;
  }

  function findButtonByText(pattern) {
    const regex = typeof pattern === "string" ? new RegExp(pattern, "i") : pattern;
    return [...document.querySelectorAll("button")].find((btn) => regex.test(btn.textContent || ""));
  }

  function pickVoice() {
    if (!("speechSynthesis" in window)) {
      selectedVoice = null;
      return;
    }
    const voices = window.speechSynthesis.getVoices();
    selectedVoice =
      voices.find((v) => v.lang && v.lang.toLowerCase().startsWith("en-us")) ||
      voices.find((v) => v.lang && v.lang.toLowerCase().startsWith("en")) ||
      voices[0] ||
      null;
  }

  function unlockAudio() {
    if (audioUnlocked) {
      return true;
    }
    try {
      if ("speechSynthesis" in window) {
        pickVoice();
      }
      audioUnlocked = true;
      try {
        window.sessionStorage.setItem(AUDIO_UNLOCK_KEY, "1");
      } catch (_err) {
        // ignore storage failures in kiosk mode
      }
      return true;
    } catch (_err) {
      audioUnlocked = false;
      return false;
    }
  }

  function speakText(text, opts = {}) {
    if (!audioUnlocked) {
      unlockAudio();
    }
    if (!audioUnlocked || !("speechSynthesis" in window)) {
      return false;
    }
    const content = String(text || "").trim();
    if (!content) {
      return false;
    }
    const utterance = new SpeechSynthesisUtterance(content);
    utterance.lang = opts.lang || "en-US";
    utterance.rate = opts.rate === undefined ? 1.0 : opts.rate;
    utterance.pitch = opts.pitch === undefined ? 1.04 : opts.pitch;
    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }
    window.speechSynthesis.speak(utterance);
    return true;
  }

  function cancelSpeech() {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }

  function buildFallbackPhotoDataUrl() {
    const canvas = document.createElement("canvas");
    canvas.width = 160;
    canvas.height = 120;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return "";
    }
    const gradient = ctx.createLinearGradient(0, 0, 160, 120);
    gradient.addColorStop(0, "#17386a");
    gradient.addColorStop(1, "#58c3ff");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 160, 120);
    ctx.fillStyle = "rgba(255,255,255,0.18)";
    ctx.beginPath();
    ctx.arc(80, 44, 22, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillRect(50, 74, 60, 24);
    return canvas.toDataURL("image/jpeg", 0.82);
  }

  function parseRegistrationFields() {
    const inputs = [...document.querySelectorAll("input.input-field")];
    const select = document.querySelector("select.input-field");
    const [nameInput, ageInput, medInput, dosageInput] = inputs;

    const name = (nameInput?.value || "").trim() || "Demo User";
    const age = (ageInput?.value || "").trim();
    const medication = (medInput?.value || "").trim() || "Ibuprofen";
    const dosage = (dosageInput?.value || "").trim() || "1 pill";

    const selectText = `${select?.value || ""} ${select?.options?.[select.selectedIndex]?.text || ""}`;
    const match = selectText.match(/channel\s*0*([1-4])/i) || selectText.match(/\b([1-4])\b/);
    const servoChannel = match ? Number(match[1]) : 1;

    return { name, age, medication, dosage, servo_channel: servoChannel };
  }

  async function dispatchAction(endpoint, payload = null) {
    try {
      const data = await requestJson(endpoint, "POST", payload);
      await applyStatus(data);
      return data;
    } catch (err) {
      console.error("Scene action failed:", err);
      return null;
    }
  }

  async function fetchUsersIfNeeded(status) {
    if (status?.known_users?.length) {
      return status.known_users;
    }
    try {
      const payload = await requestJson("/api/users");
      return payload.users || [];
    } catch (_err) {
      return [];
    }
  }

  function syncRecognitionScene(status) {
    const users = status.known_users || [];
    const matchLink = document.getElementById("sim-match-link");
    if (matchLink) {
      matchLink.style.opacity = users.length ? "1" : "0.45";
      matchLink.style.pointerEvents = users.length ? "auto" : "none";
      const small = matchLink.querySelector("span:last-child");
      if (small && users[0]) {
        small.textContent = `Existing User: ${users[0].name}`;
      }
    }
  }

  function syncDispenseScene(status) {
    const user = status.active_user || {};
    const heading = document.querySelector("h2");
    const accent = heading?.querySelector("span");
    if (accent && user.name) {
      accent.textContent = user.name;
    }

    const cards = [...document.querySelectorAll(".glass-panel div, .glass-panel span")];
    const stepCell = cards.find((el) => /Current Step/i.test(el.textContent || ""));
    if (stepCell) {
      const valueEl = stepCell.parentElement?.querySelector("span:last-child");
      if (valueEl) {
        const uartStatus = status.last_uart_result?.status || "Dispensing...";
        valueEl.textContent = `UART: ${uartStatus}`;
      }
    }

    const remaining = status.dispense_seconds_remaining;
    const total = Number(status.dispense_display_seconds_total || 0);
    const progressPercent = remaining === null || remaining === undefined || total <= 0
      ? null
      : Math.max(0, Math.min(100, 100 - (Number(remaining) / total) * 100));
    const progressFill = document.querySelector(".w-full.h-2 .h-full");
    if (progressFill && progressPercent !== null && !Number.isNaN(progressPercent)) {
      progressFill.style.width = `${Math.round(progressPercent)}%`;
    }
  }

  function syncAdviceScene(status) {
    const adviceEl = document.getElementById("advice-text");
    if (adviceEl && status.advice_text) {
      adviceEl.textContent = status.advice_text;
    }
    const timerEl = document.getElementById("session-timer");
    if (timerEl) {
      const sec = status.state === "GENERATING_ADVICE"
        ? status.advice_generation_seconds_remaining
        : status.speech_seconds_remaining;
      if (sec === null || sec === undefined) {
        timerEl.textContent = "--:--";
      } else {
        const n = Math.max(0, Number(sec) || 0);
        timerEl.textContent = `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
      }
    }

    // Preserve the exported scene design; only patch dynamic timer/content.
  }

  function syncCompletionScene(status) {
    let sec = status.auto_return_seconds;
    if (status.state !== "SESSION_SUCCESS" && status.state !== "REGISTRATION_SUCCESS") {
      const localRemaining = getCompletionHoldRemainingSeconds();
      if (localRemaining !== null) {
        sec = localRemaining;
      }
    }
    const n = sec === null || sec === undefined ? "--" : String(sec);
    const countdownEl = document.getElementById("completion-countdown")
      || [...document.querySelectorAll("div, p, span")]
        .find((el) => {
          const text = (el.textContent || "").trim();
          // Avoid matching a parent container whose textContent contains the whole page text.
          return el.children.length === 0 && /(Returning to idle in|Auto-closing in)/i.test(text);
        });
    if (countdownEl) {
      countdownEl.textContent = `Returning to idle in ${n}s`;
    }

    if (status.state === "REGISTRATION_SUCCESS") {
      setText("h2", "Profile registered");
    }
  }

  function syncFaultScene(status) {
    if (!status.last_error) {
      return;
    }
    const msgParagraph = [...document.querySelectorAll("p")]
      .find((p) => /The system encountered an error/i.test(p.textContent || ""));
    if (msgParagraph) {
      msgParagraph.textContent = status.last_error;
    }
  }

  function syncSceneContent(status) {
    const slug = currentSlug();
    if (slug === "recognition") {
      syncRecognitionScene(status);
    } else if (slug === "dispense") {
      syncDispenseScene(status);
    } else if (slug === "advice") {
      syncAdviceScene(status);
    } else if (slug === "completion") {
      syncCompletionScene(status);
    } else if (slug === "fault") {
      syncFaultScene(status);
    }
  }

  function bindSceneHandlers() {
    bindDebugTriggers();

    bindClick("cta-start-session", async () => {
      unlockAudio();
      await dispatchAction("/api/start-monitoring");
    });

    bindClick("proceed-to-scan-link", async () => {
      const threshold = Number(latestStatus?.distance_threshold_m || 1.2);
      await dispatchAction("/api/distance", { distance_m: Math.max(0.2, threshold - 0.05) });
    });

    bindClick("sim-match-link", async () => {
      const users = await fetchUsersIfNeeded(latestStatus);
      const user = users[0];
      if (!user?.id) {
        return;
      }
      await dispatchAction("/api/recognition/local", {
        match_type: "existing",
        user_id: user.id,
        source: "REALSENSE_LOCAL",
        confidence: 0.93,
      });
    });

    bindClick("sim-no-match-link", async () => {
      await dispatchAction("/api/recognition/local", {
        match_type: "new",
        source: "REALSENSE_LOCAL",
        confidence: 0.2,
      });
    });

    bindClick("cancel-registration", async () => {
      cancelSpeech();
      await dispatchAction("/api/reset");
    });

    bindClick("submit-registration", async () => {
      if (!capturedPhotoDataUrl) {
        capturedPhotoDataUrl = buildFallbackPhotoDataUrl();
      }
      const payload = {
        ...parseRegistrationFields(),
        photo_data_url: capturedPhotoDataUrl,
      };
      await dispatchAction("/api/register", payload);
    });

    bindClick("report-issue-link", async () => {
      cancelSpeech();
      await dispatchAction("/api/reset");
    });

    bindClick("finish-btn", async () => {
      if (latestStatus?.state === "SPEAKING_ADVICE") {
        cancelSpeech();
        await dispatchAction("/api/stop-advice");
        return;
      }
      cancelSpeech();
      await dispatchAction("/api/reset");
    });

    bindClick("recovery-retry-link", async () => {
      cancelSpeech();
      await dispatchAction("/api/reset");
    });

    bindClick("recovery-cancel-link", async () => {
      cancelSpeech();
      await dispatchAction("/api/reset");
    });

    bindClick("support-link", () => {
      // local demo placeholder
    });

    const captureBtn = findButtonByText(/capture face data/i);
    if (captureBtn && captureBtn.dataset.localBound !== "1") {
      captureBtn.dataset.localBound = "1";
      captureBtn.addEventListener("click", (event) => {
        event.preventDefault();
        capturedPhotoDataUrl = buildFallbackPhotoDataUrl();
        captureBtn.textContent = "Face Data Captured";
        captureBtn.classList.add("opacity-80");
      });
    }
  }

  function maybeSpeak(status) {
    const user = status.active_user || {};

    if (status.state === "DISPENSING_PILL" && user.name) {
      const key = `${user.id || user.name}:${status.state}`;
      if (key !== lastGreetingKey) {
        const greetingText = `Hello ${user.name}, dispensing your medication now.`;
        if (speakText(greetingText)) {
          greetingHoldUntilMs = Date.now() + estimateSpeechMs(greetingText, 1.0);
          lastGreetingKey = key;
        }
      }
    }

    if (status.state === "SPEAKING_ADVICE" && status.advice_text) {
      const key = `${user.id || "anon"}:${status.advice_text}`;
      if (key !== lastSpokenAdviceKey) {
        if (speakText(status.advice_text, { rate: 0.96, pitch: 1.0 })) {
          lastSpokenAdviceKey = key;
        }
      }
    }

    if (status.state === "WAITING_FOR_USER") {
      lastGreetingKey = "";
      lastSpokenAdviceKey = "";
      greetingHoldUntilMs = 0;
      clearCompletionHold();
    }
  }

  async function applyStatus(status) {
    if (!status || !status.state) {
      return;
    }
    latestStatus = status;

    if (status.state === "SESSION_SUCCESS" || status.state === "REGISTRATION_SUCCESS") {
      setCompletionHold(status.auto_return_seconds);
    }

    const target = targetSlugFromState(status.state);
    const slug = currentSlug();

    if (slug === "dispense" && target === "advice" && greetingHoldUntilMs > Date.now()) {
      bindSceneHandlers();
      syncDispenseScene(status);
      updateRuntimePanel(status);
      return;
    }

    if (slug === "completion" && target === "idle") {
      const remaining = getCompletionHoldRemainingSeconds();
      if (remaining !== null && remaining > 0) {
        bindSceneHandlers();
        syncCompletionScene(status);
        updateRuntimePanel(status);
        return;
      }
      clearCompletionHold();
    }

    if (target !== slug) {
      try {
        window.location.replace(`/ui-scene/${target}`);
      } catch (_err) {
        window.location.assign(`/ui-scene/${target}`);
      }
      return;
    }

    bindSceneHandlers();
    syncSceneContent(status);
    updateRuntimePanel(status);
    maybeSpeak(status);
  }

  async function pollStatus() {
    try {
      const status = await requestJson("/api/status");
      await applyStatus(status);
    } catch (err) {
      console.error("Scene status poll failed:", err);
    }
  }

  function startPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
    }
    pollTimer = window.setInterval(pollStatus, 500);
    pollStatus();
  }

  document.addEventListener(
    "pointerdown",
    () => {
      unlockAudio();
    },
    { once: true },
  );

  if ("speechSynthesis" in window) {
    window.speechSynthesis.addEventListener("voiceschanged", pickVoice);
    pickVoice();
  }
  try {
    if (window.sessionStorage.getItem(AUDIO_UNLOCK_KEY) === "1") {
      audioUnlocked = true;
    }
  } catch (_err) {
    // ignore storage failures
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } else {
      startPolling();
    }
  });

  ensureRuntimePanel();
  bindDebugTriggers();
  startPolling();
})();
