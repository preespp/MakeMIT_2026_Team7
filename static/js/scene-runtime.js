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
  let latestRealsenseMeta = null;
  let capturedPhotoDataUrl = "";
  let pollTimer = null;
  let audioUnlocked = false;
  let selectedVoice = null;
  let lastSpokenAdviceKey = "";
  let lastGreetingKey = "";
  const AUDIO_UNLOCK_KEY = "sauron_scene_audio_unlocked";
  const COMPLETION_HOLD_UNTIL_KEY = "sauron_completion_hold_until_ms";
  const ADVICE_POST_SPEECH_DELAY_MS = 1800;
  const GREETING_POST_SPEECH_DELAY_MS = 350;
  let runtimePanelReady = false;
  let runtimePanelOpen = false;
  let greetingHoldUntilMs = 0;
  let adviceHoldUntilMs = 0;
  let lastAdviceTimerSeconds = null;
  let forceBypassCompletionHoldOnce = false;
  let forceBypassAdviceHoldOnce = false;
  let speechSequence = 0;
  let realsenseSnapshotTimer = null;
  let adviceAutoStopTimer = null;

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

  async function pollRealsenseMeta() {
    try {
      const meta = await requestJson(`/api/realsense/meta?_=${Date.now()}`);
      latestRealsenseMeta = meta && typeof meta === "object" ? meta : null;
    } catch (_err) {
      latestRealsenseMeta = null;
    }
    return latestRealsenseMeta;
  }

  function isEmbeddingReady() {
    return !!(latestRealsenseMeta && latestRealsenseMeta.pending_embedding_available);
  }

  function getVisionStatus() {
    const v = latestRealsenseMeta?.vision_status;
    return v && typeof v === "object" ? v : {};
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

  function detectBrowserTimezone() {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      return String(tz || "").trim() || "";
    } catch (_err) {
      return "";
    }
  }

  function normalizeNameKey(value) {
    return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
  }

  function hasKnownUserNameMatch(name) {
    const target = normalizeNameKey(name);
    if (!target) {
      return false;
    }
    const users = Array.isArray(latestStatus?.known_users) ? latestStatus.known_users : [];
    return users.some((u) => normalizeNameKey(u?.name) === target);
  }

  function formatTimerClock(seconds) {
    const n = Math.max(0, Number(seconds) || 0);
    return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
  }

  function clearAdviceAutoStopTimer() {
    if (adviceAutoStopTimer) {
      clearTimeout(adviceAutoStopTimer);
      adviceAutoStopTimer = null;
    }
  }

  function buildAdviceSpeechText(status) {
    const payload = status?.last_advice_payload && typeof status.last_advice_payload === "object"
      ? status.last_advice_payload
      : {};
    const user = status?.active_user || {};
    const name = String(user.name || "").trim();
    const medication = String(payload.medication || user.medication || "").trim();
    const sideEffects = Array.isArray(payload.side_effects) ? payload.side_effects.filter(Boolean).slice(0, 3) : [];
    const advice = String(payload.advice || status?.advice_text || "").trim();
    const scheduleGuidance = Array.isArray(payload.schedule_guidance) ? payload.schedule_guidance.filter(Boolean).slice(0, 3) : [];
    const environmentGuidance = Array.isArray(payload.environment_guidance) ? payload.environment_guidance.filter(Boolean).slice(0, 3) : [];

    const parts = [];
    if (name) {
      parts.push(`Hello ${name}.`);
    }
    if (medication) {
      parts.push(`You just received ${medication}.`);
    }
    if (sideEffects.length) {
      parts.push(`Common side effects may include ${sideEffects.join(", ")}.`);
    }
    if (advice) {
      parts.push(advice);
    }
    if (scheduleGuidance.length) {
      parts.push(`Timing reminder: ${scheduleGuidance.join(" ")}`);
    }
    if (environmentGuidance.length) {
      parts.push(`Today: ${environmentGuidance.join(" ")}`);
    }
    const composed = parts.join(" ").replace(/\s+/g, " ").trim();
    return composed || String(status?.advice_text || "").trim();
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

  function mountRegistrationRealsenseFeed() {
    if (currentSlug() !== "register") {
      return;
    }
    const preview = document.getElementById("register-face-preview") || document.querySelector(".face-preview");
    if (!preview) {
      return;
    }

    if (!document.getElementById("realsense-feed-style")) {
      const style = document.createElement("style");
      style.id = "realsense-feed-style";
      style.textContent = [
        ".face-preview .realsense-feed{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;background:#070e1d;display:block;}",
        ".face-preview .realsense-feed.hidden{display:none;}",
        ".face-preview .realsense-feed-overlay{position:absolute;left:10px;top:10px;z-index:3;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.08em;background:rgba(7,14,29,.65);color:#9ab0cb;border:1px solid rgba(255,255,255,.12);backdrop-filter:blur(6px);}",
        ".face-preview .realsense-feed-overlay.live{color:#b8ffe9;border-color:rgba(60,209,160,.35);box-shadow:0 0 0 1px rgba(60,209,160,.15) inset;}",
        ".face-preview .realsense-template-badge-reposition{position:absolute !important;left:10px !important;top:42px !important;bottom:auto !important;right:auto !important;z-index:4 !important;}",
      ].join("");
      document.head.appendChild(style);
    }

    let feedImg = document.getElementById("realsense-live-feed");
    if (!feedImg) {
      feedImg = document.createElement("img");
      feedImg.id = "realsense-live-feed";
      feedImg.className = "realsense-feed";
      feedImg.alt = "RealSense live feed";
      feedImg.loading = "eager";
      feedImg.decoding = "async";
      preview.insertBefore(feedImg, preview.firstChild || null);
    }

    // Keep existing scan line / badges / icon above the video feed.
    [...preview.children].forEach((child) => {
      if (child === feedImg) {
        return;
      }
      if (child instanceof HTMLElement) {
        const computedPos = window.getComputedStyle(child).position;
        if (!child.style.position && computedPos === "static") {
          child.style.position = "relative";
        }
        child.style.zIndex = child.style.zIndex || "2";
      }
    });

    // Reposition the template's "LIVE / CAM-01" badge cluster to the top-left so it remains
    // correctly placed after the injected feed layer and any crop/fit adjustments.
    const templateLiveBadge = [...preview.children].find((child) => {
      if (!(child instanceof HTMLElement) || child === feedImg || child.id === "realsense-feed-badge") {
        return false;
      }
      const text = (child.textContent || "").trim().toUpperCase();
      return text.includes("LIVE") && (text.includes("CAM") || text.includes("01"));
    });
    if (templateLiveBadge instanceof HTMLElement) {
      templateLiveBadge.classList.add("realsense-template-badge-reposition");
      templateLiveBadge.style.transform = "none";
      templateLiveBadge.style.margin = "0";
    }

    let badge = document.getElementById("realsense-feed-badge");
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "realsense-feed-badge";
      badge.className = "realsense-feed-overlay";
      badge.textContent = "REALSENSE LINKING";
      preview.appendChild(badge);
    }

    if (feedImg.dataset.streamBound === "1") {
      return;
    }
    feedImg.dataset.streamBound = "1";

    const setBadge = (text, isLive) => {
      if (!badge) {
        return;
      }
      badge.textContent = text;
      badge.classList.toggle("live", !!isLive);
    };

    const stopSnapshotFallback = () => {
      if (realsenseSnapshotTimer) {
        clearInterval(realsenseSnapshotTimer);
        realsenseSnapshotTimer = null;
      }
    };

    const startSnapshotFallback = () => {
      if (realsenseSnapshotTimer) {
        return;
      }
      setBadge("REALSENSE SNAPSHOT", false);
      const tick = () => {
        feedImg.src = `/api/realsense/frame.jpg?ts=${Date.now()}`;
      };
      realsenseSnapshotTimer = window.setInterval(tick, 300);
      tick();
    };

    feedImg.addEventListener("load", () => {
      const icon = preview.querySelector("iconify-icon");
      if (icon) {
        icon.style.opacity = "0.10";
      }
      setBadge("REALSENSE LIVE", true);
      stopSnapshotFallback();
    });

    feedImg.addEventListener("error", () => {
      setBadge("REALSENSE OFFLINE", false);
      startSnapshotFallback();
    });

    setBadge("REALSENSE CONNECTING", false);
    feedImg.src = `/api/realsense/stream.mjpg?ts=${Date.now()}`;
  }

  function mountRecognitionRealsenseFeed() {
    if (currentSlug() !== "recognition") {
      return;
    }
    const container = document.getElementById("view-container");
    if (!container) {
      return;
    }

    if (!document.getElementById("realsense-recognition-style")) {
      const style = document.createElement("style");
      style.id = "realsense-recognition-style";
      style.textContent = [
        "#recognition-realsense-panel{width:100%;max-width:760px;margin:0 auto 22px;padding:12px;border-radius:18px;border:1px solid rgba(167,193,224,.15);background:rgba(11,22,49,.55);backdrop-filter:blur(18px);}",
        "#recognition-realsense-stage{position:relative;overflow:hidden;border-radius:14px;border:1px solid rgba(167,193,224,.13);background:#070e1d;aspect-ratio:16/9;}",
        "#recognition-realsense-feed{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;}",
        "#recognition-vision-badge{position:absolute;left:10px;top:10px;z-index:3;padding:5px 9px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.1em;background:rgba(7,14,29,.68);color:#9ab0cb;border:1px solid rgba(255,255,255,.12);}",
        "#recognition-vision-badge.live{color:#b8ffe9;border-color:rgba(60,209,160,.35)}",
        "#recognition-vision-panel{display:grid;grid-template-columns:1fr;gap:8px;margin-top:10px;}",
        "#recognition-vision-message{padding:10px 12px;border-radius:12px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);font-size:12px;color:#ecf4ff;}",
        "#recognition-vision-meta{display:flex;flex-wrap:wrap;gap:8px;font-size:11px;color:#9ab0cb;}",
        "#recognition-vision-meta .chip{padding:4px 8px;border-radius:999px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);}",
      ].join("");
      document.head.appendChild(style);
    }

    let panel = document.getElementById("recognition-realsense-panel");
    if (!panel) {
      panel = document.createElement("section");
      panel.id = "recognition-realsense-panel";
      panel.setAttribute("data-role", "recognition-realsense-panel");
      panel.innerHTML = [
        '<div id="recognition-realsense-stage" data-role="recognition-realsense-stage">',
        '  <img id="recognition-realsense-feed" alt="RealSense recognition feed" loading="eager" decoding="async" />',
        '  <div id="recognition-vision-badge">REALSENSE CONNECTING</div>',
        "</div>",
        '<div id="recognition-vision-panel">',
        '  <div id="recognition-vision-message" data-role="recognition-vision-message">Waiting for RealSense status...</div>',
        '  <div id="recognition-vision-meta" data-role="recognition-vision-meta"></div>',
        "</div>",
      ].join("");
      container.insertBefore(panel, container.firstChild || null);
    }

    const feedImg = document.getElementById("recognition-realsense-feed");
    const badge = document.getElementById("recognition-vision-badge");
    if (!(feedImg instanceof HTMLImageElement) || !badge) {
      return;
    }
    if (feedImg.dataset.streamBound === "1") {
      return;
    }
    feedImg.dataset.streamBound = "1";

    const setBadge = (text, isLive) => {
      badge.textContent = text;
      badge.classList.toggle("live", !!isLive);
    };
    setBadge("REALSENSE CONNECTING", false);

    feedImg.addEventListener("load", () => setBadge("REALSENSE LIVE", true));
    feedImg.addEventListener("error", () => setBadge("REALSENSE OFFLINE", false));
    feedImg.src = `/api/realsense/stream.mjpg?ts=${Date.now()}`;
  }

  function ensureRegisterStatusWidgets() {
    if (currentSlug() !== "register") {
      return;
    }
    const preview = document.querySelector(".face-preview");
    if (!preview || !preview.parentElement) {
      return;
    }
    let wrap = document.getElementById("register-realsense-status-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = "register-realsense-status-wrap";
      wrap.setAttribute("data-role", "register-realsense-status");
      wrap.className = "grid gap-2 mt-3";
      wrap.innerHTML = [
        '<div id="register-embedding-ready-chip" class="px-3 py-2 rounded-xl border text-xs font-bold tracking-wide" style="border-color: rgba(255,255,255,.10); background: rgba(255,255,255,.03); color: #ecf4ff;">Face embedding captured: --</div>',
        '<div id="register-vision-message" class="px-3 py-2 rounded-xl text-xs" style="border:1px solid rgba(255,255,255,.08); background: rgba(255,255,255,.02); color:#9ab0cb;">Waiting for RealSense status...</div>',
      ].join("");
      const captureBtn = document.getElementById("capture-face-data-btn");
      if (captureBtn && captureBtn.parentElement) {
        captureBtn.parentElement.insertBefore(wrap, captureBtn);
      } else {
        preview.parentElement.appendChild(wrap);
      }
    }
  }

  function syncRealsenseUiWidgets(status) {
    const vision = getVisionStatus();
    const embeddingReady = isEmbeddingReady();
    const regNameInput = document.getElementById("reg-name") || document.querySelector('input[data-field="name"]');
    const registerName = String(regNameInput?.value || "").trim();
    const sameNameOverwrite = hasKnownUserNameMatch(registerName);

    const regChip = document.getElementById("register-embedding-ready-chip");
    if (regChip) {
      if (embeddingReady) {
        regChip.textContent = "Face embedding captured: YES";
        regChip.style.color = "#b8ffe9";
        regChip.style.borderColor = "rgba(60,209,160,.35)";
        regChip.style.background = "rgba(60,209,160,.09)";
      } else if (sameNameOverwrite) {
        regChip.textContent = "Face embedding captured: NO (existing profile embedding will be reused)";
        regChip.style.color = "#b8d7ff";
        regChip.style.borderColor = "rgba(88,195,255,.28)";
        regChip.style.background = "rgba(88,195,255,.07)";
      } else {
        regChip.textContent = "Face embedding captured: NO";
        regChip.style.color = "#ffd6a5";
        regChip.style.borderColor = "rgba(255,166,89,.28)";
        regChip.style.background = "rgba(255,166,89,.07)";
      }
    }

    const regMsg = document.getElementById("register-vision-message");
    if (regMsg) {
      const text = String(vision.vision_message || "").trim()
        || (
          embeddingReady
            ? "Embedding is ready. You can complete registration."
            : sameNameOverwrite
              ? "No new unknown-face embedding is pending. Same-name overwrite can continue and will keep the stored embedding."
              : "Stand in front of the camera until an unknown face is captured."
        );
      regMsg.textContent = text;
    }

    const recMsg = document.getElementById("recognition-vision-message");
    if (recMsg) {
      const text = String(vision.vision_message || "").trim() || "Scanning for a face...";
      recMsg.textContent = text;
    }
    const recMeta = document.getElementById("recognition-vision-meta");
    if (recMeta) {
      const chips = [];
      if (vision.match_name) chips.push(`User: ${vision.match_name}`);
      if (vision.match_score != null) chips.push(`Score: ${Number(vision.match_score).toFixed(2)}`);
      if (vision.distance_m != null) chips.push(`Distance: ${Number(vision.distance_m).toFixed(2)}m`);
      if (status?.distance_threshold_m != null) chips.push(`Threshold: ${Number(status.distance_threshold_m).toFixed(2)}m`);
      if (latestRealsenseMeta?.users_count != null) chips.push(`Users: ${latestRealsenseMeta.users_count}`);
      recMeta.innerHTML = chips.map((c) => `<span class="chip">${c}</span>`).join("");
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
        '  <div class="rt-actions">',
        '    <button class="rt-btn" id="runtimeDebugManualOverride" type="button">Manual Override Dispense</button>',
        '    <button class="rt-btn" id="runtimeDebugAdvicePayload" type="button">Fetch Advice</button>',
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
    document.getElementById("runtimeDebugManualOverride")?.addEventListener("click", async () => {
      await dispatchAction("/api/med/override-dispense", { mode: "all_active" });
    });
    document.getElementById("runtimeDebugAdvicePayload")?.addEventListener("click", async () => {
      await dispatchAction("/api/advice", {});
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
    const rs = latestRealsenseMeta || {};
    const vision = getVisionStatus();
    const uartResult = status.last_uart_result || {};
    const session = status.session_context || {};
    const lastSession = status.last_session_summary || {};
    const advicePayload = status.last_advice_payload || {};
    const rows = [
      ["State", status.state || "--"],
      ["Phase", status.phase || "--"],
      ["Scene", currentSlug()],
      ["UART", `${status.uart_transport || "--"} ${status.uart_port || ""}`.trim()],
      ["UART Proto", status.uart_protocol || "--"],
      ["UART Status", uartResult.status || "--"],
      ["HW Mode", uartResult.degraded ? "Simulated (offline)" : (uartResult.hardware_online === false ? "Offline" : "Online/Unknown")],
      ["Motor", status.motor_power_domain || "--"],
      ["Distance", status.current_distance_m == null ? "--" : Number(status.current_distance_m).toFixed(2)],
      ["Threshold", status.distance_threshold_m == null ? "--" : Number(status.distance_threshold_m).toFixed(2)],
      ["User", status.active_user?.name || "--"],
      ["Medication", status.active_user?.medication || "--"],
      ["Recognition Src", status.last_recognition?.source || lastSession.recognition_source || "--"],
      ["Manual Override", status.manual_override_available ? "Available" : "No"],
      ["TTS", status.is_speaking ? "Speaking" : "Idle"],
      ["Embedding", rs.pending_embedding_available ? "YES" : "NO"],
      ["Vision", vision.vision_state || "--"],
      ["Vision Msg", vision.vision_message || "--"],
      ["Advice Source", advicePayload.source || lastSession.advice_source || "--"],
      ["Session", session.session_id || lastSession.session_id || "--"],
    ];
    if (currentSlug() === "register") {
      rows.push(["Browser TZ", detectBrowserTimezone() || "--"]);
      rows.push(["Register Camera", rs.updated_at ? "Active" : "Waiting"]);
      rows.push(["Servo Map (Draft)", getRegisterServoMappingSummary()]);
    }
    if (status.last_error) {
      rows.push(["Last Error", status.last_error]);
    }
    grid.innerHTML = rows
      .map(([k, v]) => `<div class="rt-row"><span>${String(k)}</span><strong>${String(v)}</strong></div>`)
      .join("");
    const hint = document.getElementById("runtimeDebugHint");
    if (hint) {
      const lastSummarySnippet = lastSession && Object.keys(lastSession).length
        ? `Last session: ${lastSession.result || "--"} | user=${lastSession.user_id || "--"} | recog=${lastSession.recognition_source || "--"} | advice=${lastSession.advice_source || "--"}`
        : "Local FSM status for kiosk debugging.";
      hint.textContent = lastSummarySnippet;
    }

    const overrideBtn = document.getElementById("runtimeDebugManualOverride");
    if (overrideBtn) {
      const allow = !!status.manual_override_available || currentSlug() === "dispense" || currentSlug() === "advice";
      overrideBtn.disabled = !allow;
      overrideBtn.style.opacity = allow ? "1" : "0.45";
      overrideBtn.style.pointerEvents = allow ? "auto" : "none";
    }
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
    const seq = ++speechSequence;
    if (typeof opts.onend === "function") {
      utterance.onend = () => {
        if (seq !== speechSequence) {
          return;
        }
        try {
          opts.onend();
        } catch (_err) {
          // ignore callback errors
        }
      };
    }
    if (typeof opts.onerror === "function") {
      utterance.onerror = () => {
        if (seq !== speechSequence) {
          return;
        }
        try {
          opts.onerror();
        } catch (_err) {
          // ignore callback errors
        }
      };
    }
    window.speechSynthesis.speak(utterance);
    return true;
  }

  function cancelSpeech() {
    clearAdviceAutoStopTimer();
    if ("speechSynthesis" in window) {
      speechSequence += 1;
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

  function capturePhotoFromRealsenseFeed() {
    const feedImg = document.getElementById("realsense-live-feed");
    if (!(feedImg instanceof HTMLImageElement)) {
      return "";
    }
    const width = feedImg.naturalWidth || feedImg.width || 0;
    const height = feedImg.naturalHeight || feedImg.height || 0;
    if (!width || !height) {
      return "";
    }
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return "";
    }
    try {
      ctx.drawImage(feedImg, 0, 0, width, height);
      return canvas.toDataURL("image/jpeg", 0.9);
    } catch (_err) {
      return "";
    }
  }

  function escapeHtmlAttr(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function parseTimeList(text) {
    return String(text || "")
      .split(/[,\n;]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 6);
  }

  function getRegisterMedicationRows() {
    return [...document.querySelectorAll('[data-role="reg-med-row"]')];
  }

  function collectRegisterMedications() {
    const rows = getRegisterMedicationRows();
    const meds = [];
    rows.forEach((row, idx) => {
      const name = (row.querySelector('[data-role="reg-med-name"]')?.value || "").trim();
      const dosage = (row.querySelector('[data-role="reg-med-dosage"]')?.value || "").trim();
      const timesRaw = (row.querySelector('[data-role="reg-med-times"]')?.value || "").trim();
      const active = !!row.querySelector('[data-role="reg-med-active"]')?.checked;
      if (!name) {
        return;
      }
      meds.push({
        id: `med-${idx + 1}`,
        name,
        dosage,
        times: parseTimeList(timesRaw),
        servo_channel: idx + 1,
        active,
      });
    });
    return meds.slice(0, 4);
  }

  function getRegisterServoMappingSummary() {
    const meds = collectRegisterMedications().filter((m) => m.active !== false);
    const parts = [];
    for (let ch = 1; ch <= 4; ch += 1) {
      const med = meds.find((m) => Number(m.servo_channel) === ch);
      parts.push(`Ch${ch}:${med?.name || "--"}`);
    }
    return parts.join(" | ");
  }

  function ensureRegisterMedicationScheduleEditor() {
    if (currentSlug() !== "register") {
      return;
    }
    if (!document.getElementById("registration-view")) {
      return;
    }

    if (!document.getElementById("register-med-editor-style")) {
      const style = document.createElement("style");
      style.id = "register-med-editor-style";
      style.textContent = [
        "#register-med-schedule-grid{display:grid;gap:12px;}",
        ".reg-med-row{display:grid;grid-template-columns:1.35fr 1fr 1.45fr auto;gap:10px;align-items:end;padding:12px;border:1px solid rgba(255,255,255,.08);border-radius:14px;background:rgba(255,255,255,.02);}",
        ".reg-med-row .reg-med-slot{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#9ab0cb;font-weight:700;}",
        ".reg-med-row .reg-med-field{display:grid;gap:6px;min-width:0;}",
        ".reg-med-row .reg-med-field label{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#9ab0cb;}",
        ".reg-med-row .reg-med-field input{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.10);border-radius:10px;padding:10px 12px;color:white;width:100%;}",
        ".reg-med-row .reg-med-field input:focus{outline:none;border-color:#58c3ff;box-shadow:0 0 0 3px rgba(88,195,255,.12);}",
        ".reg-med-row .reg-med-toggle{display:flex;align-items:center;gap:8px;justify-self:end;font-size:11px;color:#ecf4ff;white-space:nowrap;}",
        ".reg-med-row .reg-med-toggle input{width:16px;height:16px;accent-color:#58c3ff;}",
        "@media (max-width: 980px){.reg-med-row{grid-template-columns:1fr;align-items:stretch;}.reg-med-row .reg-med-toggle{justify-self:start;}}",
      ].join("");
      document.head.appendChild(style);
    }

    const hwCard = document.getElementById("register-hardware-link-card");
    if (hwCard) {
      hwCard.style.display = "none";
      hwCard.setAttribute("aria-hidden", "true");
    }

    const servoSelect = document.getElementById("reg-servo-channel");
    const servoRow = servoSelect?.closest(".space-y-2");
    if (servoRow) {
      servoRow.style.display = "none";
      servoRow.setAttribute("aria-hidden", "true");
    }

    if (document.getElementById("register-med-schedule-wrap")) {
      return;
    }

    const medInput = document.getElementById("reg-medication");
    const dosageInput = document.getElementById("reg-dosage");
    const medSection = medInput?.closest("section") || dosageInput?.closest("section");
    if (!medSection) {
      return;
    }
    const legacyGrid = medInput?.closest(".grid");
    if (legacyGrid) {
      legacyGrid.style.display = "none";
      legacyGrid.setAttribute("aria-hidden", "true");
    }

    const wrap = document.createElement("div");
    wrap.id = "register-med-schedule-wrap";
    wrap.setAttribute("data-role", "register-med-schedule-wrap");
    wrap.className = "space-y-4";
    wrap.innerHTML = [
      '<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">',
      '  <div class="text-sm font-semibold text-white">Medication Schedule (up to 4)</div>',
      '  <div class="text-[11px] text-[#9ab0cb]">Servo channel mapping is auto-assigned internally and shown in the Debug Panel.</div>',
      "</div>",
      '<div id="register-med-schedule-grid" data-role="register-med-schedule-grid"></div>',
      '<div class="text-xs text-[#9ab0cb]">Use local time in HH:MM format. Example: 08:00, 20:00</div>',
    ].join("");
    medSection.appendChild(wrap);

    const grid = wrap.querySelector("#register-med-schedule-grid");
    if (!(grid instanceof HTMLElement)) {
      return;
    }

    const defaults = [
      {
        name: (medInput?.value || "").trim(),
        dosage: (dosageInput?.value || "").trim(),
        times: "",
        active: true,
      },
      { name: "", dosage: "", times: "", active: false },
      { name: "", dosage: "", times: "", active: false },
      { name: "", dosage: "", times: "", active: false },
    ];

    defaults.forEach((item, idx) => {
      const row = document.createElement("div");
      row.className = "reg-med-row";
      row.setAttribute("data-role", "reg-med-row");
      row.setAttribute("data-slot", String(idx + 1));
      row.innerHTML = [
        '<div class="reg-med-field">',
        `  <div class="reg-med-slot">Slot ${idx + 1}</div>`,
        "  <label>Medication</label>",
        `  <input type="text" data-role="reg-med-name" placeholder="Medication ${idx + 1}" value="${escapeHtmlAttr(item.name)}">`,
        "</div>",
        '<div class="reg-med-field">',
        "  <label>Dosage</label>",
        `  <input type="text" data-role="reg-med-dosage" placeholder="1 pill" value="${escapeHtmlAttr(item.dosage)}">`,
        "</div>",
        '<div class="reg-med-field">',
        "  <label>Schedule Times</label>",
        `  <input type="text" data-role="reg-med-times" placeholder="08:00,20:00" value="${escapeHtmlAttr(item.times)}">`,
        "</div>",
        '<label class="reg-med-toggle">',
        `  <input type="checkbox" data-role="reg-med-active" ${item.active ? "checked" : ""}>`,
        "  <span>Enabled</span>",
        "</label>",
      ].join("");
      grid.appendChild(row);
    });
  }

  function parseRegistrationFields() {
    ensureRegisterMedicationScheduleEditor();
    const inputs = [...document.querySelectorAll("input.input-field")];
    const select =
      document.getElementById("reg-servo-channel")
      || document.querySelector('select[data-field="servo_channel"]')
      || document.querySelector("select.input-field");
    const [fallbackNameInput, fallbackAgeInput, fallbackMedInput, fallbackDosageInput] = inputs;

    const nameInput =
      document.getElementById("reg-name")
      || document.querySelector('input[data-field="name"]')
      || fallbackNameInput;
    const ageInput =
      document.getElementById("reg-age")
      || document.querySelector('input[data-field="age"]')
      || fallbackAgeInput;
    const medInput =
      document.getElementById("reg-medication")
      || document.querySelector('input[data-field="medication"]')
      || fallbackMedInput;
    const dosageInput =
      document.getElementById("reg-dosage")
      || document.querySelector('input[data-field="dosage"]')
      || fallbackDosageInput;

    const name = (nameInput?.value || "").trim() || "Demo User";
    const age = (ageInput?.value || "").trim();
    const medication = (medInput?.value || "").trim() || "Ibuprofen";
    const dosage = (dosageInput?.value || "").trim() || "1 pill";

    const selectText = `${select?.value || ""} ${select?.options?.[select.selectedIndex]?.text || ""}`;
    const match = selectText.match(/channel\s*0*([1-4])/i) || selectText.match(/\b([1-4])\b/);
    const servoChannel = match ? Number(match[1]) : 1;
    const medications = collectRegisterMedications();
    const activeMedications = medications.filter((m) => m.active !== false);
    const primaryMed = activeMedications[0] || medications[0] || null;
    const timezone = detectBrowserTimezone();
    const language = String(navigator.language || "en-US").trim() || "en-US";

    return {
      name,
      age,
      language,
      timezone: timezone || undefined,
      medication: primaryMed?.name || medication,
      dosage: primaryMed?.dosage || dosage,
      servo_channel: Number(primaryMed?.servo_channel || servoChannel || 1),
      medications,
      schedule_times: Array.isArray(primaryMed?.times) ? primaryMed.times.slice(0, 6) : [],
    };
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
    syncRealsenseUiWidgets(status);
    const vision = getVisionStatus();
    const titleEl = document.getElementById("recognition-title");
    const subtitleEl = document.getElementById("recognition-subtitle");
    if (titleEl && vision.vision_state === "recognized" && vision.match_name) {
      titleEl.textContent = `Welcome, ${vision.match_name}`;
    } else if (titleEl) {
      titleEl.textContent = "Verifying Identity...";
    }
    if (subtitleEl) {
      subtitleEl.textContent = String(vision.vision_message || "").trim() || "Please look directly into the camera lens.";
    }
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

  function syncRegisterScene(status) {
    ensureRegisterMedicationScheduleEditor();
    syncRealsenseUiWidgets(status);
    const hwCard = document.getElementById("register-hardware-link-card");
    if (hwCard) {
      hwCard.style.display = "none";
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

    const card = document.querySelector(".glass-panel");
    if (card) {
      let note = document.getElementById("dispense-hardware-note");
      if (!note) {
        note = document.createElement("div");
        note.id = "dispense-hardware-note";
        note.setAttribute("data-role", "dispense-hardware-note");
        note.className = "mt-4 px-4 py-3 rounded-xl border text-sm";
        note.style.display = "none";
        note.style.borderColor = "rgba(255,255,255,.08)";
        note.style.background = "rgba(255,255,255,.03)";
        note.style.color = "#ecf4ff";
        card.appendChild(note);
      }
      const uart = status.last_uart_result || {};
      if (uart.degraded || uart.status === "SIMULATED_OFFLINE" || uart.status === "SIMULATED_DISABLED") {
        note.textContent = "Dispense simulated (hardware offline)";
        note.style.display = "block";
        note.style.color = "#ffd6a5";
        note.style.borderColor = "rgba(255,166,89,.25)";
        note.style.background = "rgba(255,166,89,.07)";
      } else if (String(uart.status || "").toUpperCase() === "NO_DUE") {
        note.textContent = "No medication is due right now. Use Manual Override in the Debug Panel if dispensing is still needed.";
        note.style.display = "block";
        note.style.color = "#b8d7ff";
        note.style.borderColor = "rgba(88,195,255,.25)";
        note.style.background = "rgba(88,195,255,.07)";
      } else if (uart.ack === true) {
        note.textContent = `Hardware ACK received (${uart.status || "ACK"})`;
        note.style.display = "block";
        note.style.color = "#b8ffe9";
        note.style.borderColor = "rgba(60,209,160,.25)";
        note.style.background = "rgba(60,209,160,.07)";
      } else {
        note.style.display = "none";
      }
    }
  }

  function syncAdviceScene(status) {
    const adviceDataReady = status.state === "SPEAKING_ADVICE" || status.state === "SESSION_SUCCESS";
    const adviceEl = document.getElementById("advice-text");
    const payloadForText = adviceDataReady && status.last_advice_payload && typeof status.last_advice_payload === "object"
      ? status.last_advice_payload
      : {};
    const primaryAdviceText = adviceDataReady
      ? String(payloadForText.advice || status.advice_text || "").trim()
      : "Preparing personalized guidance...";
    if (adviceEl) {
      adviceEl.textContent = primaryAdviceText || "Preparing personalized guidance...";
    }
    const timerEl = document.getElementById("session-timer");
    if (timerEl) {
      let sec = null;
      const localAdviceRemaining = adviceHoldUntilMs > 0
        ? Math.max(0, Math.ceil((adviceHoldUntilMs - Date.now()) / 1000))
        : null;

      if (status.state === "GENERATING_ADVICE") {
        sec = status.advice_generation_seconds_remaining;
        if (sec == null && localAdviceRemaining != null) {
          sec = localAdviceRemaining;
        }
      } else if (status.state === "SPEAKING_ADVICE") {
        // Prefer the local TTS-based estimate + post-speech hold, which matches actual UX timing.
        sec = localAdviceRemaining != null ? localAdviceRemaining : status.speech_seconds_remaining;
      } else if (localAdviceRemaining != null) {
        // We intentionally keep the advice scene on screen for a short local hold before navigation.
        sec = localAdviceRemaining;
      }

      if (sec == null || sec === undefined) {
        timerEl.textContent = lastAdviceTimerSeconds == null ? "0:00" : formatTimerClock(lastAdviceTimerSeconds);
      } else {
        const n = Math.max(0, Number(sec) || 0);
        lastAdviceTimerSeconds = n;
        timerEl.textContent = formatTimerClock(n);
      }
    }

    const payload = adviceDataReady && status.last_advice_payload && typeof status.last_advice_payload === "object"
      ? status.last_advice_payload
      : {};
    const adviceTitleEl = document.getElementById("advice-title");
    if (adviceTitleEl) {
      const med = String(payload.medication || status.active_user?.medication || "").trim();
      adviceTitleEl.textContent = med ? `${med} Guidance` : "Medication Guidance";
    }
    const env = payload.environment_summary && typeof payload.environment_summary === "object"
      ? payload.environment_summary
      : {};
    let structured = document.getElementById("advice-structured-sections");
    if (!structured) {
      const card = document.getElementById("advice-main-card") || document.querySelector(".glass-panel");
      const controlsRow = document.getElementById("finish-btn")?.closest(".flex.items-center.justify-between");
      if (card && controlsRow) {
        structured = document.createElement("div");
        structured.id = "advice-structured-sections";
        structured.setAttribute("data-role", "advice-structured-sections");
        structured.className = "grid grid-cols-1 md:grid-cols-3 gap-4";
        controlsRow.parentElement?.insertBefore(structured, controlsRow);
      }
    }
    if (structured) {
      const effects = adviceDataReady && Array.isArray(payload.side_effects) ? payload.side_effects.filter(Boolean).slice(0, 3) : [];
      const scheduleGuidance = adviceDataReady && Array.isArray(payload.schedule_guidance) ? payload.schedule_guidance.filter(Boolean).slice(0, 3) : [];
      const environmentGuidance = adviceDataReady && Array.isArray(payload.environment_guidance) ? payload.environment_guidance.filter(Boolean).slice(0, 3) : [];
      const scheduleSummary = adviceDataReady && payload.schedule_summary && typeof payload.schedule_summary === "object" ? payload.schedule_summary : {};
      const weatherBits = [];
      if (adviceDataReady && env.temperature_c != null) weatherBits.push(`${env.temperature_c} deg C`);
      if (adviceDataReady && env.aqi_us != null) weatherBits.push(`AQI ${env.aqi_us}`);
      if (adviceDataReady && env.precipitation_mm != null) weatherBits.push(`Rain ${env.precipitation_mm}mm`);
      if (adviceDataReady && Array.isArray(env.alerts) && env.alerts.length) weatherBits.push(`Alerts: ${env.alerts.length}`);
      const nextDoseText = adviceDataReady && Array.isArray(scheduleSummary.upcoming) && scheduleSummary.upcoming[0]
        ? `Next: ${scheduleSummary.upcoming[0].name || "medication"} @ ${scheduleSummary.upcoming[0].matched_time || "later"}`
        : "";
      const scheduleText = adviceDataReady
        ? (scheduleGuidance.length ? scheduleGuidance.join(" ") : (nextDoseText || "No schedule guidance available"))
        : "Preparing schedule-aware guidance...";
      const weatherTip = adviceDataReady
        ? (environmentGuidance.length ? environmentGuidance.join(" ") : (weatherBits.length ? weatherBits.join(" | ") : "No weather feed available"))
        : "Loading weather and context signals...";
      const adviceText = adviceDataReady
        ? (String(payload.advice || status.advice_text || "").trim() || "Advice is being prepared.")
        : "Preparing personalized guidance...";
      structured.innerHTML = [
        renderAdviceCardSection("Side Effects", adviceDataReady ? (effects.length ? effects.join("; ") : "--") : "Analyzing medication side effects...", "lucide:triangle-alert"),
        renderAdviceCardSection("Advice", adviceText, "lucide:message-circle-heart"),
        renderAdviceCardSection("Schedule", scheduleText, "lucide:clock-3"),
        renderAdviceCardSection("Weather Tip", weatherTip, "lucide:cloud-sun"),
      ].join("");
    }
  }

  function renderAdviceCardSection(title, body, icon) {
    return [
      '<section class="rounded-2xl border border-white/10 bg-white/5 p-4" data-role="advice-structured-card">',
      `  <div class="flex items-center gap-2 mb-2 text-[11px] uppercase tracking-widest text-[#9ab0cb] font-bold"><iconify-icon icon="${icon}" class="text-[#58c3ff]"></iconify-icon><span>${title}</span></div>`,
      `  <div class="text-sm leading-relaxed text-white/90">${escapeHtml(body)}</div>`,
      "</section>",
    ].join("");
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
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
      setText(document.getElementById("completion-title") || "h2", "Profile registered");
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
    } else if (slug === "register") {
      syncRegisterScene(status);
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
    ensureRegisterMedicationScheduleEditor();
    mountRegistrationRealsenseFeed();
    mountRecognitionRealsenseFeed();
    ensureRegisterStatusWidgets();

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
      await pollRealsenseMeta();
      const parsedFields = parseRegistrationFields();
      const sameNameOverwrite = hasKnownUserNameMatch(parsedFields.name);
      if (!isEmbeddingReady() && !sameNameOverwrite) {
        ensureRegisterStatusWidgets();
        const regMsg = document.getElementById("register-vision-message");
        if (regMsg) {
          regMsg.textContent = "Face embedding not ready. Please stand in front of the camera and wait for unknown-face capture before submitting registration.";
          regMsg.style.color = "#ffd6a5";
          regMsg.style.borderColor = "rgba(255,166,89,.25)";
          regMsg.style.background = "rgba(255,166,89,.06)";
        }
        window.alert("Face embedding not ready.\nPlease stand in front of the camera first and let the system capture the face (unknown-face detection) before clicking Complete Registration.");
        return;
      }
      if (!isEmbeddingReady() && sameNameOverwrite) {
        ensureRegisterStatusWidgets();
        const regMsg = document.getElementById("register-vision-message");
        if (regMsg) {
          regMsg.textContent = "No new face embedding captured. Same-name overwrite will proceed and keep the existing stored embedding for this user.";
          regMsg.style.color = "#b8d7ff";
          regMsg.style.borderColor = "rgba(88,195,255,.25)";
          regMsg.style.background = "rgba(88,195,255,.06)";
        }
      }
      if (!capturedPhotoDataUrl) {
        capturedPhotoDataUrl = capturePhotoFromRealsenseFeed() || buildFallbackPhotoDataUrl();
      }
      const payload = {
        ...parsedFields,
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
        forceBypassAdviceHoldOnce = true;
        adviceHoldUntilMs = 0;
        cancelSpeech();
        await dispatchAction("/api/stop-advice");
        return;
      }
      if (currentSlug() === "completion") {
        forceBypassCompletionHoldOnce = true;
        clearCompletionHold();
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

    const captureBtn = document.getElementById("capture-face-data-btn") || findButtonByText(/capture face data/i);
    if (captureBtn && captureBtn.dataset.localBound !== "1") {
      captureBtn.dataset.localBound = "1";
      captureBtn.addEventListener("click", (event) => {
        event.preventDefault();
        capturedPhotoDataUrl = capturePhotoFromRealsenseFeed() || buildFallbackPhotoDataUrl();
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
        const fallbackHold = Date.now() + estimateSpeechMs(greetingText, 1.0) + GREETING_POST_SPEECH_DELAY_MS;
        if (speakText(greetingText, {
          onend: () => {
            greetingHoldUntilMs = Date.now() + GREETING_POST_SPEECH_DELAY_MS;
          },
          onerror: () => {
            greetingHoldUntilMs = Date.now() + 200;
          },
        })) {
          greetingHoldUntilMs = fallbackHold;
          lastGreetingKey = key;
        }
      }
    }

    const adviceSpeechText = buildAdviceSpeechText(status);
    if (status.state === "SPEAKING_ADVICE" && adviceSpeechText) {
      const key = `${user.id || "anon"}:${adviceSpeechText}`;
      if (key !== lastSpokenAdviceKey) {
        clearAdviceAutoStopTimer();
        const fallbackHold = Date.now() + estimateSpeechMs(adviceSpeechText, 0.96) + ADVICE_POST_SPEECH_DELAY_MS;
        if (speakText(adviceSpeechText, {
          rate: 0.96,
          pitch: 1.0,
          onend: () => {
            adviceHoldUntilMs = Date.now() + ADVICE_POST_SPEECH_DELAY_MS;
            lastAdviceTimerSeconds = Math.max(0, Math.ceil(ADVICE_POST_SPEECH_DELAY_MS / 1000));
            clearAdviceAutoStopTimer();
            adviceAutoStopTimer = window.setTimeout(async () => {
              adviceAutoStopTimer = null;
              if (latestStatus?.state === "SPEAKING_ADVICE") {
                await dispatchAction("/api/stop-advice");
              }
            }, ADVICE_POST_SPEECH_DELAY_MS);
          },
          onerror: () => {
            adviceHoldUntilMs = Date.now() + 300;
            lastAdviceTimerSeconds = 1;
            clearAdviceAutoStopTimer();
            adviceAutoStopTimer = window.setTimeout(async () => {
              adviceAutoStopTimer = null;
              if (latestStatus?.state === "SPEAKING_ADVICE") {
                await dispatchAction("/api/stop-advice");
              }
            }, 300);
          },
        })) {
          adviceHoldUntilMs = fallbackHold;
          lastAdviceTimerSeconds = Math.max(0, Math.ceil((fallbackHold - Date.now()) / 1000));
          lastSpokenAdviceKey = key;
        }
      }
    }

    if (status.state === "WAITING_FOR_USER") {
      lastGreetingKey = "";
      lastSpokenAdviceKey = "";
      greetingHoldUntilMs = 0;
      adviceHoldUntilMs = 0;
      clearAdviceAutoStopTimer();
      lastAdviceTimerSeconds = null;
      forceBypassCompletionHoldOnce = false;
      forceBypassAdviceHoldOnce = false;
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

    if (slug === "advice" && target === "completion") {
      if (forceBypassAdviceHoldOnce) {
        forceBypassAdviceHoldOnce = false;
      } else if (adviceHoldUntilMs > Date.now()) {
        bindSceneHandlers();
        syncAdviceScene(status);
        updateRuntimePanel(status);
        return;
      }
    }

    if (slug === "completion" && target === "idle") {
      if (forceBypassCompletionHoldOnce) {
        forceBypassCompletionHoldOnce = false;
        clearCompletionHold();
      } else {
        const remaining = getCompletionHoldRemainingSeconds();
        if (remaining !== null && remaining > 0) {
          bindSceneHandlers();
          syncCompletionScene(status);
          updateRuntimePanel(status);
          return;
        }
        clearCompletionHold();
      }
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
      const [status] = await Promise.all([
        requestJson("/api/status"),
        pollRealsenseMeta(),
      ]);
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
