# 🤖 Claude Distraction Manager — Desktop Script

A Windows desktop automation tool that manages your focus time by opening
social media windows **only while Claude is generating a response**, then
**instantly closing them** when Claude finishes or needs your input.

---

## 📐 Window Layout

```
┌──────────────────────┬────────────────────┐
│                      │   YouTube Shorts   │  ← top-right 25%
│   Instagram Reels    ├────────────────────┤
│     (left 50%)       │   Facebook Feed    │  ← bottom-right 25%
└──────────────────────┴────────────────────┘
```

Works at any screen resolution — layout is calculated dynamically.

---

## 🧠 Detection Method: Playwright DOM Monitoring

**Why Playwright over OCR / title polling?**

| Method | Reliability | CPU Usage | Complexity |
|--------|-------------|-----------|------------|
| OCR (pytesseract) | ⚠️ Medium | 🔴 High | High |
| Window title polling | ⚠️ Low | 🟡 Medium | Low |
| **Playwright DOM** ✅ | 🟢 High | 🟢 Very low | Low |

The script opens a **persistent Chromium browser** (separate from your daily Chrome) via Playwright. It polls the DOM every ~1 second for:

- **Generating state** → `button[aria-label="Stop generating"]` is visible
- **Idle state** → Stop button is gone, Send button is present

This is the same signal used by Claude's own UI and is far more reliable than pixel-level detection.

---

## ⚙️ Setup

### Prerequisites
- Windows 10/11
- Python 3.10+
- Google Chrome or Microsoft Edge installed

### 1. Install Dependencies

```bash
# Option A: One-click setup
setup.bat

# Option B: Manual
pip install -r requirements.txt
playwright install chromium
```

### 2. First Run

```bash
python claude_distraction_manager.py
```

A Playwright-controlled Chromium window will open to `claude.ai`.

> **First-time only**: Log into your Claude account in this browser window.
> Your session will be saved for future runs.

### 3. Use It

- Start a conversation with Claude
- When Claude begins generating → social media windows open automatically (after ~2.5s delay)
- When Claude finishes or asks you something → windows close instantly
- **Toggle on/off**: `Ctrl+Shift+D`

---

## 🔧 Configuration

Edit the `Config` dataclass at the top of `claude_distraction_manager.py`:

```python
@dataclass
class Config:
    claude_url: str = "https://claude.ai"   # Change for local Antigravity
    poll_interval: float = 1.0              # Detection frequency (seconds)
    open_delay: float = 2.5                 # Wait before opening windows
    instagram_url: str = "https://www.instagram.com/reels/"
    youtube_url: str   = "https://www.youtube.com/shorts"
    facebook_url: str  = "https://www.facebook.com"
    browser_exe: str = ""                   # Auto-detected; set if needed
    toggle_hotkey: str = "ctrl+shift+d"
    log_file: str = "distraction_manager.log"
```

### Using with Antigravity (local Claude)

If you run Claude locally via Antigravity, change:

```python
claude_url: str = "http://localhost:3000"  # Your local port
```

---

## 📦 File Structure

```
claude_distraction_manager/
├── claude_distraction_manager.py   # Main script
├── requirements.txt                 # Python dependencies
├── setup.bat                        # One-click setup for Windows
├── README.md                        # This file
└── distraction_manager.log          # Created at runtime
```

---

## 🛡️ Safety & Performance

| Feature | Implementation |
|---------|---------------|
| **Zero interference** | Only closes windows it opened (tracked by PID) |
| **Low CPU** | Polls DOM every 1s via lightweight JS eval |
| **Crash safe** | Prunes dead windows every 5s; handles external closes |
| **Duplicate prevention** | Checks if windows already open before opening again |
| **Clean shutdown** | `Ctrl+C` or toggle → closes all managed windows |

---

## 🪵 Log Output Example

```
[23:10:01] INFO     Browser: C:\Program Files\Google\Chrome\Application\chrome.exe
[23:10:01] INFO     Hotkey:  ctrl+shift+d  (toggle on/off)
[23:10:05] INFO     Claude state: unknown → generating
[23:10:07] INFO     Claude is generating — opening social windows …
[23:10:07] INFO     Launched instagram (PID 18432)
[23:10:09] INFO     Placing instagram at (0,0) 960×1080
[23:10:10] INFO     ✅ All social windows open and arranged.
[23:10:42] INFO     Claude state: generating → idle
[23:10:42] INFO     Claude stopped — closing social windows …
[23:10:43] INFO     ❌ All social windows closed.
```

---

## 🔮 Reliability Improvements

1. **Multiple stop-button selectors** — tries 5 different CSS selectors so DOM changes don't break detection
2. **Open delay** — waits 2.5s to avoid flickering on short responses
3. **Session persistence** — Playwright reuses your Claude login across restarts
4. **Dead window pruning** — automatically cleans up if user manually closes a window
5. **Child process kill** — kills Chrome renderer sub-processes cleanly via `psutil`

---

## ❓ Troubleshooting

**Script can't find Chrome**
→ Set `browser_exe` in Config to your Chrome path, e.g.:
```python
browser_exe: str = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
```

**Windows open but don't resize correctly**
→ Check Windows display scaling (Settings → Display → Scale). Set scale to 100% or adjust `get_screen_size()` DPI handling.

**Detection not working after Claude update**
→ Update selectors in `STOP_BUTTON_SELECTORS` list. Inspect Claude's DOM with F12 DevTools and find the stop button's aria-label.

**Permission errors**
→ Run `setup.bat` or the script as Administrator.
