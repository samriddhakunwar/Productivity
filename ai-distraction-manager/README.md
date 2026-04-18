# 🧠 AI Distraction Manager

A **Chrome Extension (Manifest v3)** that automatically opens distraction tabs (YouTube Shorts, Instagram, Facebook) when Claude is generating a response — and closes them the moment Claude finishes or asks for your input.

---

## 📁 Project Structure

```
ai-distraction-manager/
├── manifest.json          # Extension manifest (MV3)
├── background.js          # Service worker – tab management & state logic
├── content.js             # Content script – Claude DOM detection via MutationObserver
├── popup.html             # Extension popup UI
├── popup.css              # Popup styles (dark theme)
├── popup.js               # Popup logic – settings, site management, status
├── generate-icons.js      # Icon generator script (run once)
└── icons/
    ├── icon.svg           # Source SVG icon
    ├── icon16.png
    ├── icon32.png
    ├── icon48.png
    └── icon128.png
```

---

## ⚙️ How Claude Detection Works

The content script (`content.js`) injects into every `claude.ai` page and uses a **MutationObserver** to watch the DOM for state changes — no polling, no performance overhead.

### Detection Signals (any one = "generating"):

| Signal | What we check |
|---|---|
| **Stop button** | `button[aria-label*="Stop"]` is visible |
| **Send button disabled** | `button[aria-label*="Send"]` has `disabled` attribute |
| **Streaming indicator** | `[data-is-streaming="true"]` element present |
| **Loading spinner** | `.animate-spin` or `[data-testid="loading-spinner"]` visible |

When the state changes between `generating` ↔ `idle`, a message is sent to the background service worker which handles tab creation/destruction.

### SPA Navigation:
Claude is a Single Page App — the content script intercepts `history.pushState` / `popstate` to restart the observer on every conversation switch.

---

## 🚀 Installation Steps

### Step 1 — Generate Icons
```bash
cd ai-distraction-manager
node generate-icons.js
```
> Icons are now in `icons/`. For high-quality SVG-rendered icons, run `npm install canvas` first.

### Step 2 — Load the Extension in Chrome

1. Open Chrome and go to: `chrome://extensions`
2. Enable **Developer mode** (toggle in top-right corner)
3. Click **"Load unpacked"**
4. Select the `ai-distraction-manager/` folder
5. The extension icon (🧠) appears in your Chrome toolbar

### Step 3 — Test It

1. Open [claude.ai](https://claude.ai) in a tab
2. Send any message to Claude
3. Watch distraction tabs open automatically after the 2-second delay
4. When Claude finishes, all distraction tabs close automatically
5. A Chrome notification confirms Claude is ready

---

## 🎛️ Extension Popup Features

Click the 🧠 icon in your toolbar to open the popup:

| Feature | Description |
|---|---|
| **Enable/Disable toggle** | Turn the entire extension ON or OFF instantly |
| **Status indicator** | Live dot showing: 🟡 Generating / 🟢 Idle / ⚫ Disabled |
| **Site toggles** | Enable or disable individual distraction sites |
| **Add custom sites** | Add any URL to the distraction list |
| **Remove sites** | Remove any site with one click |
| **Open delay slider** | 0s – 10s delay before tabs open (default: 2s) |
| **Notifications toggle** | Show/hide Chrome notification when tabs close |

---

## 🛡️ Edge Cases Handled

| Edge Case | How It's Handled |
|---|---|
| User manually closes distraction tabs | Tracked via `chrome.tabs.onRemoved` — removed from Set |
| Claude becomes idle before delay elapsed | Timer cancelled, tabs never open |
| Tabs already open (duplicate prevention) | Checked before opening — skips if `openedTabIds.size > 0` |
| Page refresh / SPA navigation | Observer restarted, state reset to `idle` |
| Extension disabled mid-session | Observer stops, pending timers cancelled, idle signal sent |
| Tab closed by Chrome (crash/memory) | `chrome.tabs.get()` filters non-existent tabs before closing |

---

## 🔒 Permissions Explained

| Permission | Reason |
|---|---|
| `tabs` | Open and close tabs, track tab IDs |
| `storage` | Persist user settings (sites, delay, toggle state) |
| `notifications` | Show "Claude is ready" alert |
| Host: `claude.ai/*` | Inject content script to detect Claude's state |

---

## 🧩 Architecture Overview

```
┌─────────────────────────────────────┐
│           claude.ai tab             │
│  ┌───────────────────────────────┐  │
│  │  content.js                   │  │
│  │  MutationObserver watches DOM │  │
│  │  → sends "CLAUDE_GENERATING"  │  │
│  │  → sends "CLAUDE_IDLE"        │  │
│  └─────────────┬─────────────────┘  │
└────────────────│────────────────────┘
                 │ chrome.runtime.sendMessage
                 ▼
┌─────────────────────────────────────┐
│         background.js               │
│  Service Worker                     │
│  • Manages openedTabIds (Set)       │
│  • Debounced open delay timer       │
│  • chrome.tabs.create / remove      │
│  • chrome.storage.sync (settings)   │
└─────────────────────────────────────┘
                 │ reads/writes
                 ▼
┌─────────────────────────────────────┐
│  Distraction Tabs                   │
│  YouTube Shorts / Instagram / FB    │
└─────────────────────────────────────┘
```

---

## 💡 Tips

- **Adjusting delay**: Set a longer delay if Claude often gives quick single-line responses — this prevents tabs from flashing open and immediately closing.
- **Custom sites**: Add any URL via the popup. The label is optional (falls back to hostname).
- **Developer debugging**: Open `chrome://extensions` → click "Service Worker" under the extension to view background.js logs.
