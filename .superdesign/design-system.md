# MedDispenser Design System

## Product Context
- Device UI for Jetson touchscreen
- Core tone: calm, medical-safe, futuristic-friendly
- Interaction mode: large touch targets + strong state transitions

## Visual Tokens (Hard Constraints)
- Keep color tokens from `static/css/style.css` root variables as canonical
- Preserve gradient background system (`theme-idle`, `theme-monitor`, `theme-recognition`, `theme-register`, `theme-dispense`, `theme-error`)
- Keep border radius family between 11px-18px
- Keep glass-like panels (`--surface`, `--surface-soft`, subtle blur)

## Typography
- Current stack: Trebuchet MS / Gill Sans / Verdana
- Maintain high contrast text hierarchy: main title/key labels bold; subtitles muted but readable

## Motion and Interaction
- Default animation primitives: transform + opacity
- Keep blink eye mascot concept in idle
- Keep lightweight transitions for low CPU use on Jetson
- Prefer GSAP for entrance/exit choreography; CSS keyframes for repeating loops

## Layout Patterns
- Immersive full-stage experience in idle state
- Floating system controls in header
- Debug as optional drawer, hidden by default
- All critical interactions remain in central stage flow

## UX Behavior Constraints
- Preserve FSM-driven state mapping from backend
- Never require debug panel for normal user flow
- Keep audio/TTS opt-in fallback button and autoplay-safe behavior

## Do Not Introduce
- Heavy UI frameworks in runtime page
- Large video backgrounds or expensive filter-heavy effects
- New visual tokens outside existing palette unless explicitly requested
