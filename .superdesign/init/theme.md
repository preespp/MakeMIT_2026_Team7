# theme.md

## Design Tokens and Global Styles
- Token source: `:root` variables in `static/css/style.css`
- Typography: Trebuchet/Gill Sans/Verdana stack
- Layout style: immersive gradient stage + glassmorphism surfaces
- Motion style: CSS keyframes + GSAP transform/opacity transitions
- No Tailwind config in this repo

### `static/css/style.css`

```css
:root {
  --bg-1: #0c2044;
  --bg-2: #1c3f75;
  --bg-3: #2b5ea8;
  --surface: rgba(11, 22, 49, 0.78);
  --surface-soft: rgba(12, 25, 54, 0.6);
  --text-main: #ecf4ff;
  --text-muted: #9ab0cb;
  --primary: #58c3ff;
  --primary-hover: #30a9ee;
  --success: #3cd1a0;
  --warning: #ff6d76;
  --border: rgba(167, 193, 224, 0.25);
  --radius: 18px;
  --shadow: 0 16px 38px -22px rgba(0, 0, 0, 0.7);
  --overlay: rgba(209, 238, 255, 0.6);
}

* {
  box-sizing: border-box;
  font-family: "Trebuchet MS", "Gill Sans", "Verdana", sans-serif;
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--text-main);
  background: linear-gradient(-35deg, var(--bg-1), var(--bg-2), var(--bg-3));
  background-size: 260% 260%;
  animation: bg-flow 16s ease infinite;
  transition: background-color 0.5s ease;
}

body.theme-idle {
  --bg-1: #0c2044;
  --bg-2: #17386a;
  --bg-3: #284f93;
}

body.theme-monitor {
  --bg-1: #1b2455;
  --bg-2: #62388f;
  --bg-3: #b25f74;
}

body.theme-recognition {
  --bg-1: #2d2f66;
  --bg-2: #4b3a85;
  --bg-3: #8153a1;
}

body.theme-register {
  --bg-1: #11356f;
  --bg-2: #1f5f9f;
  --bg-3: #3689c8;
}

body.theme-dispense {
  --bg-1: #124b4a;
  --bg-2: #1f8062;
  --bg-3: #66b874;
}

body.theme-error {
  --bg-1: #4f1421;
  --bg-2: #7f1b2a;
  --bg-3: #ab3141;
}

@keyframes bg-flow {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.95rem 1.35rem;
  background: var(--surface-soft);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  transition: opacity 0.4s ease, transform 0.4s ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand h1 {
  margin: 0;
  font-size: 1.45rem;
  letter-spacing: 0.02em;
}

.fw-light {
  font-weight: 300;
  color: var(--text-muted);
}

.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 9px rgba(60, 209, 160, 0.85);
}

.status-dot.error {
  background: var(--warning);
  box-shadow: 0 0 11px rgba(255, 109, 118, 0.88);
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

body.immersive-mode .app-header {
  opacity: 0;
  transform: translateY(-14px);
  pointer-events: none;
}

body.immersive-mode .debug-toggle-btn {
  opacity: 0;
  transform: translateY(-12px);
  pointer-events: none;
}

body.immersive-mode .app-layout {
  width: 100vw;
  margin: 0;
  min-height: 100vh;
}

body.immersive-mode .main-view-container {
  min-height: 100vh;
  border-radius: 0;
  border: none;
}

.system-badges {
  display: flex;
  gap: 8px;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  border: 1px solid var(--border);
  color: var(--text-muted);
  background: rgba(111, 141, 178, 0.15);
}

.badge.active {
  color: #ccf4ff;
  background: rgba(88, 195, 255, 0.2);
}

.badge.error {
  color: #ffd7db;
  background: rgba(255, 109, 118, 0.2);
}

.app-layout {
  display: block;
  width: min(1400px, 96vw);
  margin: 0.9rem auto 1.2rem;
  min-height: calc(100vh - 86px);
}

.main-view-container {
  position: relative;
  overflow: hidden;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--surface);
  box-shadow: var(--shadow);
  min-height: calc(100vh - 115px);
}

.debug-panel {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  width: min(360px, 92vw);
  z-index: 40;
  border-radius: 0 16px 16px 0;
  border: 1px solid var(--border);
  background: var(--surface);
  box-shadow: var(--shadow);
  padding: 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  transform: translateX(-110%);
  opacity: 0;
  pointer-events: none;
}

.debug-panel h3,
.debug-panel h4 {
  margin: 0.35rem 0;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.debug-toggle-btn {
  position: fixed;
  left: 14px;
  top: 98px;
  z-index: 31;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.48rem 0.88rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: #ebf8ff;
  background: rgba(9, 21, 45, 0.62);
  backdrop-filter: blur(8px);
  cursor: pointer;
  transition: transform 0.15s ease, opacity 0.2s ease;
}

.debug-toggle-btn:hover {
  transform: translateY(-1px);
}

.debug-scrim {
  position: fixed;
  inset: 0;
  z-index: 35;
  background: rgba(2, 8, 24, 0.55);
  opacity: 0;
  pointer-events: none;
}

.debug-scrim.active {
  pointer-events: auto;
}

.transition-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  background:
    radial-gradient(circle at 50% 50%, rgba(248, 252, 255, 0.45), transparent 55%),
    linear-gradient(118deg, rgba(155, 231, 255, 0.28), rgba(244, 214, 255, 0.2), rgba(255, 220, 168, 0.23));
  transition: opacity 0.42s ease;
  z-index: 8;
}

.transition-overlay.active {
  opacity: 1;
}

.hello-banner {
  position: absolute;
  top: 16px;
  left: 50%;
  z-index: 9;
  transform: translate(-50%, -24px);
  opacity: 0;
  transition: transform 0.34s ease, opacity 0.34s ease;
  background: rgba(238, 247, 255, 0.15);
  border: 1px solid rgba(225, 242, 255, 0.34);
  border-radius: 999px;
  padding: 0.55rem 1.25rem;
  backdrop-filter: blur(8px);
  pointer-events: none;
}

.hello-banner p {
  margin: 0;
  font-weight: 700;
  color: #edf8ff;
}

.hello-banner.show {
  transform: translate(-50%, 0);
  opacity: 1;
}

.view {
  position: absolute;
  inset: 0;
  padding: clamp(1rem, 2vw, 2rem);
  opacity: 0;
  pointer-events: none;
  transform: translateY(12px) scale(0.992);
  transition: opacity 0.35s ease, transform 0.35s ease;
  overflow-y: auto;
}

.view.active {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0) scale(1);
}

.view-content {
  max-width: 740px;
  margin: 0 auto;
}

.center-content {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

h2 {
  margin: 0;
  font-size: clamp(1.6rem, 2.8vw, 2.3rem);
}

h3 {
  margin: 0;
  font-size: 1.15rem;
}

.subtitle {
  margin: 0.45rem 0 1.5rem;
  color: var(--text-muted);
  font-size: 1.02rem;
}

.mascot-wrap {
  margin-bottom: 1rem;
}

.mascot-eyes {
  display: flex;
  gap: 18px;
  align-items: center;
  justify-content: center;
}

.eye {
  width: clamp(88px, 12vw, 120px);
  height: clamp(88px, 12vw, 120px);
  border-radius: 50%;
  background: #eef6ff;
  position: relative;
  box-shadow: inset 0 -6px 16px rgba(135, 170, 214, 0.35);
  overflow: hidden;
}

.pupil {
  position: absolute;
  width: 42%;
  height: 42%;
  border-radius: 50%;
  background: radial-gradient(circle at 36% 32%, #75c0ff, #0e2f57 70%);
  top: 30%;
  left: 30%;
  transform: translateZ(0);
  animation: look-around 7.2s ease-in-out infinite;
}

.glint {
  position: absolute;
  width: 14%;
  height: 14%;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.94);
  top: 36%;
  left: 44%;
  pointer-events: none;
}

.lid {
  position: absolute;
  inset: 0;
  background: rgba(10, 24, 56, 0.9);
  transform-origin: top center;
  animation: blink 5.4s infinite;
}

@keyframes blink {
  0%, 3%, 42%, 47%, 74%, 100% {
    transform: scaleY(0);
  }
  1.5%, 44%, 75% {
    transform: scaleY(1);
  }
}

@keyframes look-around {
  0%, 100% { transform: translate(0, 0); }
  18% { transform: translate(10%, -8%); }
  38% { transform: translate(-12%, 4%); }
  58% { transform: translate(8%, 8%); }
  78% { transform: translate(-8%, -5%); }
}

body.theme-monitor .mascot-wrap,
body.theme-recognition .mascot-wrap {
  transform: scale(1.04);
}

body.theme-monitor .pupil,
body.theme-recognition .pupil {
  animation-duration: 4.6s;
}

.btn {
  border-radius: 12px;
  border: 1px solid transparent;
  padding: 0.65rem 1.05rem;
  font-weight: 700;
  cursor: pointer;
  color: var(--text-main);
  background: rgba(145, 171, 204, 0.18);
  transition: transform 0.12s ease, background-color 0.2s ease, border-color 0.2s ease;
}

.btn:hover:not(:disabled) {
  transform: translateY(-1px);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: linear-gradient(120deg, #2eb3ff, #56daff);
  color: #02203e;
}

.btn-primary:hover:not(:disabled) {
  background: linear-gradient(120deg, #1ea6f4, #44cceb);
}

.btn-success {
  background: linear-gradient(120deg, #48d3a2, #7be2b9);
  color: #062f2a;
}

.btn-outline {
  border-color: var(--border);
  background: transparent;
  color: #deefff;
}

.btn-outline:hover:not(:disabled) {
  border-color: rgba(173, 219, 255, 0.85);
  color: #eff8ff;
}

.btn-secondary {
  background: linear-gradient(120deg, #5f74d0, #7f8de6);
  color: #f3f7ff;
}

.btn-xl {
  font-size: 1.12rem;
  padding: 0.9rem 2.1rem;
}

.btn-sm {
  padding: 0.45rem 0.75rem;
  font-size: 0.82rem;
}

.btn-block {
  width: 100%;
}

.btn.is-ready {
  border-color: rgba(98, 231, 181, 0.9);
  color: #d7ffe9;
}

.camera-container {
  position: relative;
  width: min(530px, 88vw);
  aspect-ratio: 4 / 3;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid rgba(171, 208, 255, 0.28);
  background: #071525;
}

#liveVideo {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.scan-line {
  position: absolute;
  left: 0;
  width: 100%;
  height: 2px;
  background: #80d8ff;
  box-shadow: 0 0 10px rgba(128, 216, 255, 0.9);
  animation: scan 2.1s infinite linear;
}

.scan-frame {
  position: absolute;
  inset: 18px;
  border: 2px solid rgba(149, 228, 255, 0.75);
  border-radius: 14px;
  box-shadow: inset 0 0 18px rgba(111, 210, 255, 0.32);
}

@keyframes scan {
  0% { top: 6%; }
  50% { top: 88%; }
  100% { top: 6%; }
}

.ring-stage {
  display: flex;
  justify-content: center;
  margin-bottom: 1rem;
}

.scan-ring {
  width: 86px;
  height: 86px;
  border-radius: 50%;
  border: 2px solid rgba(142, 234, 255, 0.88);
  border-top-color: transparent;
  border-right-color: rgba(198, 148, 255, 0.9);
  animation: spin 1.25s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.demo-controls {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 0.8rem;
  align-items: stretch;
}

.card {
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 1rem;
  background: rgba(10, 23, 48, 0.5);
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}

.divider {
  align-self: center;
  color: var(--text-muted);
  font-weight: 700;
}

.form-grid {
  display: grid;
  gap: 0.55rem;
}

.input-group {
  display: grid;
  gap: 0.35rem;
}

.input-group label {
  color: var(--text-muted);
  font-size: 0.86rem;
}

.input-modern {
  width: 100%;
  border-radius: 11px;
  border: 1px solid var(--border);
  background: rgba(8, 20, 43, 0.62);
  color: var(--text-main);
  padding: 0.65rem 0.78rem;
  outline: none;
}

.input-modern:focus {
  border-color: rgba(124, 208, 255, 0.88);
  box-shadow: 0 0 0 2px rgba(70, 177, 236, 0.18);
}

.input-sm {
  font-size: 0.85rem;
  padding: 0.42rem 0.54rem;
}

.photo-capture-section {
  margin-top: 0.35rem;
  border: 1px dashed var(--border);
  border-radius: 12px;
  padding: 0.75rem;
  display: grid;
  gap: 0.55rem;
}

#capturePreview {
  width: min(260px, 100%);
  border-radius: 12px;
  border: 1px solid var(--border);
}

.spinner {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 4px solid rgba(178, 222, 255, 0.25);
  border-top-color: rgba(178, 242, 255, 0.95);
  animation: spin 0.9s linear infinite;
  margin: 1.25rem 0;
}

.advice-card {
  width: min(600px, 92%);
  margin-top: 1rem;
  border: 1px solid rgba(176, 239, 213, 0.4);
  border-radius: 14px;
  background: rgba(18, 57, 52, 0.55);
  padding: 1rem;
  text-align: left;
}

.advice-card h3 {
  margin: 0 0 0.55rem;
}

.advice-card p {
  margin: 0.3rem 0;
}

.text-accent {
  color: #bdf9e3;
}

.metric-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.35rem;
  align-items: baseline;
  font-size: 0.87rem;
  padding: 0.42rem 0;
  border-bottom: 1px solid rgba(174, 202, 235, 0.18);
}

.metric-row strong {
  color: #e8f7ff;
}

.simulator-box {
  margin-top: 0.4rem;
  border: 1px dashed var(--border);
  border-radius: 12px;
  padding: 0.72rem;
  background: rgba(9, 20, 43, 0.44);
}

.flex-row {
  display: flex;
  gap: 0.5rem;
}

.history-list {
  margin: 0;
  padding-left: 0.9rem;
  font-size: 0.76rem;
  color: var(--text-muted);
  max-height: 240px;
  overflow: auto;
}

.history-list li {
  margin-bottom: 0.35rem;
}

.micro-text {
  font-size: 0.82rem;
  color: var(--text-muted);
}

.error-text {
  color: #ffd4d8;
  font-weight: 700;
}

.icon-error {
  width: 76px;
  height: 76px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 2.2rem;
  font-weight: 800;
  margin-bottom: 0.5rem;
  color: #ffced4;
  background: rgba(171, 35, 62, 0.38);
  border: 1px solid rgba(255, 144, 162, 0.35);
}

.hidden {
  display: none !important;
}

.mt-4 {
  margin-top: 1rem;
}

@media (max-width: 1080px) {
  .app-layout {
    width: 100vw;
    margin: 0;
  }

  .main-view-container {
    min-height: 100vh;
    border-radius: 0;
    border: none;
  }

  .demo-controls {
    grid-template-columns: 1fr;
  }

  .divider {
    margin: 0.2rem 0;
  }

  .app-header {
    padding: 0.78rem 0.82rem;
  }

  .brand h1 {
    font-size: 1.2rem;
  }

  .system-badges {
    display: none;
  }

  .debug-toggle-btn {
    top: 76px;
  }
}


```
