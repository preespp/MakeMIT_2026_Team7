const stateBadge = document.getElementById("stateBadge");
const phaseBadge = document.getElementById("phaseBadge");
const messageLine = document.getElementById("message");
const lastError = document.getElementById("lastError");
const historyList = document.getElementById("historyList");

const startBtn = document.getElementById("startBtn");
const resetBtn = document.getElementById("resetBtn");

const distanceForm = document.getElementById("distanceForm");
const distanceInput = document.getElementById("distanceInput");
const distanceInputValue = document.getElementById("distanceInputValue");
const distanceBtn = document.getElementById("distanceBtn");

const newUserBtn = document.getElementById("newUserBtn");
const existingUserBtn = document.getElementById("existingUserBtn");
const existingUserSelect = document.getElementById("existingUserSelect");

const registerForm = document.getElementById("registerForm");
const captureBtn = document.getElementById("captureBtn");
const photoFile = document.getElementById("photoFile");
const photoStatus = document.getElementById("photoStatus");
const capturePreview = document.getElementById("capturePreview");

const stopAdviceBtn = document.getElementById("stopAdviceBtn");

const thresholdVal = document.getElementById("thresholdVal");
const distanceVal = document.getElementById("distanceVal");
const computeVal = document.getElementById("computeVal");
const cameraVal = document.getElementById("cameraVal");
const recognitionVal = document.getElementById("recognitionVal");
const uartVal = document.getElementById("uartVal");
const motorPowerVal = document.getElementById("motorPowerVal");
const activeUserLine = document.getElementById("activeUserLine");
const adviceText = document.getElementById("adviceText");
const speechRemaining = document.getElementById("speechRemaining");
const autoReturn = document.getElementById("autoReturn");
const successTitle = document.getElementById("successTitle");
const successText = document.getElementById("successText");

const cameraPanel = document.getElementById("cameraPanel");
const liveVideo = document.getElementById("liveVideo");
const cameraNote = document.getElementById("cameraNote");

const views = {
  start: document.getElementById("startView"),
  monitor: document.getElementById("monitorView"),
  recognition: document.getElementById("recognitionView"),
  register: document.getElementById("registerView"),
  speaking: document.getElementById("speakingView"),
  success: document.getElementById("successView"),
  error: document.getElementById("errorView"),
};

let cameraStream = null;
let capturedPhotoDataUrl = "";
let uploadedPhotoDataUrl = "";

function setHidden(element, shouldHide) {
  element.classList.toggle("hidden", shouldHide);
}

async function requestJson(url, method = "GET", body = null) {
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== null) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch (err) {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.message || `Request failed (${response.status})`);
  }
  return payload;
}

function renderHistory(items) {
  historyList.innerHTML = "";
  const rows = [...(items || [])].reverse();
  if (!rows.length) {
    const li = document.createElement("li");
    li.textContent = "No transitions yet.";
    historyList.appendChild(li);
    return;
  }

  for (const entry of rows) {
    const li = document.createElement("li");
    const ts = new Date(entry.timestamp).toLocaleTimeString();
    li.textContent = `[${ts}] ${entry.from} -> ${entry.to} | ${entry.note}`;
    historyList.appendChild(li);
  }
}

function syncExistingUsers(users) {
  const list = users || [];
  const previous = existingUserSelect.value;

  existingUserSelect.innerHTML = "";
  if (!list.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No registered users yet";
    existingUserSelect.appendChild(opt);
    existingUserSelect.disabled = true;
    return;
  }

  existingUserSelect.disabled = false;
  for (const user of list) {
    const opt = document.createElement("option");
    opt.value = user.id;
    const channel = user.servo_channel || "-";
    opt.textContent = `${user.name} (${user.id}) | CH${channel}`;
    existingUserSelect.appendChild(opt);
  }

  if (list.some((u) => u.id === previous)) {
    existingUserSelect.value = previous;
  }
}

function showOnly(viewKey) {
  for (const [key, element] of Object.entries(views)) {
    setHidden(element, key !== viewKey);
  }
}

async function ensureCamera() {
  if (cameraStream) {
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    cameraNote.textContent = "Camera API unavailable in this browser.";
    return;
  }

  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    liveVideo.srcObject = cameraStream;
    cameraNote.textContent = "Camera stream active.";
  } catch (err) {
    cameraNote.textContent = `Camera error: ${err.message}`;
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

function stateNeedsCamera(state) {
  return ["MONITORING_DISTANCE", "FACE_RECOGNITION", "REGISTER_NEW_USER"].includes(state);
}

async function renderStatus(data) {
  stateBadge.textContent = data.state;
  stateBadge.classList.toggle("error", data.state === "ERROR");
  phaseBadge.textContent = data.phase || "--";
  phaseBadge.classList.toggle("error", data.state === "ERROR");

  messageLine.textContent = data.message || "Ready.";
  lastError.textContent = data.last_error ? `Last error: ${data.last_error}` : "";

  thresholdVal.textContent = `${Number(data.distance_threshold_m || 0).toFixed(2)}m`;
  distanceVal.textContent =
    data.current_distance_m === null || data.current_distance_m === undefined
      ? "--"
      : `${Number(data.current_distance_m).toFixed(2)}m`;
  computeVal.textContent = data.compute_node || "--";
  cameraVal.textContent = data.camera_source || "--";
  const rec = data.last_recognition || {};
  if (rec.match_type) {
    const recUser = rec.user_id ? `:${rec.user_id}` : "";
    const recConf = rec.confidence === null || rec.confidence === undefined ? "" : ` @${rec.confidence}`;
    recognitionVal.textContent = `${String(rec.source || "LOCAL")} ${String(rec.match_type).toUpperCase()}${recUser}${recConf}`;
  } else {
    recognitionVal.textContent = "--";
  }
  uartVal.textContent = `${data.uart_transport || "--"} ${data.uart_port || ""}@${data.uart_baud || ""}`.trim();
  motorPowerVal.textContent = data.motor_power_domain || "--";

  const activeUser = data.active_user;
  if (activeUser) {
    activeUserLine.textContent = `User: ${activeUser.name || "Unknown"} | Medication: ${
      activeUser.medication || "n/a"
    } | Channel: ${activeUser.servo_channel || "n/a"}`;
  } else {
    activeUserLine.textContent = "";
  }

  adviceText.textContent = data.advice_text || "Advice will appear here once generated.";
  speechRemaining.textContent =
    data.speech_seconds_remaining === null || data.speech_seconds_remaining === undefined
      ? "--"
      : String(data.speech_seconds_remaining);
  autoReturn.textContent =
    data.auto_return_seconds === null || data.auto_return_seconds === undefined
      ? "--"
      : String(data.auto_return_seconds);

  syncExistingUsers(data.known_users || []);
  renderHistory(data.history || []);

  startBtn.disabled = !data.can_start_monitoring;
  distanceBtn.disabled = !data.can_submit_distance;
  newUserBtn.disabled = !data.can_choose_recognition;
  existingUserBtn.disabled = !data.can_choose_recognition || existingUserSelect.disabled;
  registerForm.querySelector("button[type='submit']").disabled = !data.can_register_user;
  stopAdviceBtn.disabled = !data.can_stop_advice;
  resetBtn.disabled = !data.can_reset;

  if (stateNeedsCamera(data.state)) {
    setHidden(cameraPanel, false);
    await ensureCamera();
  } else {
    setHidden(cameraPanel, true);
    stopCamera();
  }

  if (data.state === "WAITING_FOR_USER") {
    showOnly("start");
  } else if (data.state === "MONITORING_DISTANCE") {
    showOnly("monitor");
  } else if (data.state === "FACE_RECOGNITION") {
    showOnly("recognition");
  } else if (data.state === "REGISTER_NEW_USER") {
    showOnly("register");
  } else if (data.state === "SPEAKING_ADVICE") {
    showOnly("speaking");
  } else if (data.state === "ERROR") {
    showOnly("error");
  } else {
    showOnly("success");
    if (data.state === "REGISTRATION_SUCCESS") {
      successTitle.textContent = "Registration Complete";
      successText.textContent = "User saved to local JSON + JPG. Returning to start screen soon.";
    } else if (data.state === "DISPENSING_PILL") {
      successTitle.textContent = "Dispensing Pill";
      const uartResult = data.last_uart_result || {};
      const status = uartResult.status || "PENDING";
      successText.textContent = `Dispense command sent over USB-UART to ESP32. Status: ${status}.`;
    } else if (data.state === "GENERATING_ADVICE") {
      successTitle.textContent = "Generating Advice";
      successText.textContent = "Gemini advice is being prepared (placeholder).";
    } else if (data.state === "SESSION_SUCCESS") {
      successTitle.textContent = "Session Complete";
      successText.textContent = "Dispense and advice are complete. Returning to start screen.";
    } else {
      successTitle.textContent = "Working";
      successText.textContent = "Please wait.";
    }
  }
}

async function refreshStatus() {
  try {
    const data = await requestJson("/api/status");
    await renderStatus(data);
  } catch (err) {
    messageLine.textContent = `Status error: ${err.message}`;
  }
}

async function runAction(url, body = null) {
  try {
    const data = await requestJson(url, "POST", body);
    await renderStatus(data);
  } catch (err) {
    messageLine.textContent = `Action error: ${err.message}`;
  }
}

startBtn.addEventListener("click", () => runAction("/api/start-monitoring"));
resetBtn.addEventListener("click", () => runAction("/api/reset"));

newUserBtn.addEventListener("click", () =>
  runAction("/api/recognition/local", {
    match_type: "new",
    source: "REALSENSE_LOCAL",
    confidence: 0.2,
  })
);
existingUserBtn.addEventListener("click", () => {
  if (!existingUserSelect.value) {
    messageLine.textContent = "Select an existing user first.";
    return;
  }
  runAction("/api/recognition/local", {
    match_type: "existing",
    user_id: existingUserSelect.value,
    source: "REALSENSE_LOCAL",
    confidence: 0.92,
  });
});

stopAdviceBtn.addEventListener("click", () => runAction("/api/stop-advice"));

distanceInput.addEventListener("input", () => {
  distanceInputValue.textContent = Number(distanceInput.value).toFixed(2);
});

distanceForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("/api/distance", { distance_m: Number(distanceInput.value) });
});

captureBtn.addEventListener("click", () => {
  if (!cameraStream || !liveVideo.videoWidth || !liveVideo.videoHeight) {
    messageLine.textContent = "Camera is not ready yet.";
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.width = liveVideo.videoWidth;
  canvas.height = liveVideo.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(liveVideo, 0, 0, canvas.width, canvas.height);

  capturedPhotoDataUrl = canvas.toDataURL("image/jpeg", 0.9);
  uploadedPhotoDataUrl = "";
  capturePreview.src = capturedPhotoDataUrl;
  setHidden(capturePreview, false);
  photoStatus.textContent = "Captured image from camera.";
});

photoFile.addEventListener("change", () => {
  const [file] = photoFile.files || [];
  if (!file) {
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    uploadedPhotoDataUrl = String(reader.result || "");
    capturedPhotoDataUrl = "";
    capturePreview.src = uploadedPhotoDataUrl;
    setHidden(capturePreview, false);
    photoStatus.textContent = "Loaded image from file.";
  };
  reader.readAsDataURL(file);
});

registerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const photoDataUrl = capturedPhotoDataUrl || uploadedPhotoDataUrl;
  if (!photoDataUrl) {
    messageLine.textContent = "Capture or upload a photo before saving.";
    return;
  }

  const payload = {
    name: document.getElementById("nameInput").value.trim(),
    age: document.getElementById("ageInput").value.trim(),
    medication: document.getElementById("medicationInput").value.trim(),
    dosage: document.getElementById("dosageInput").value.trim(),
    servo_channel: Number(document.getElementById("servoChannelInput").value || 1),
    notes: document.getElementById("notesInput").value.trim(),
    photo_data_url: photoDataUrl,
  };

  runAction("/api/register", payload);
});

window.addEventListener("beforeunload", stopCamera);

refreshStatus();
setInterval(refreshStatus, 1000);
