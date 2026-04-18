You are an expert full-stack developer. Build a smart desktop/browser automation system called **“AI Distraction Manager”** with the following requirements:

## 🎯 Goal

When I am using Claude (via browser), the system should:

1. Detect when Claude is actively generating a response
2. Automatically open distraction websites (YouTube Shorts, Instagram, Facebook)
3. When Claude finishes OR asks for user input, automatically close those distraction tabs

---

## ⚙️ Core Features

### 1. Claude Activity Detection

* Detect when Claude is:

  * “Thinking” / generating response
  * Finished generating
  * Waiting for user input
* Use DOM observation (MutationObserver) to track UI changes in Claude’s web interface
* The detection should be reliable and efficient

---

### 2. Auto Open Distraction Tabs

When Claude starts generating:

* Open the following in new tabs:

  * https://www.youtube.com/shorts
  * https://www.instagram.com
  * https://www.facebook.com

---

### 3. Auto Close Tabs

When:

* Claude finishes generating OR
* Claude asks for permission/input

Then:

* Automatically close ONLY the tabs opened by this system
* Do NOT close unrelated tabs

---

### 4. Architecture

Build this as a **Chrome Extension (Manifest v3)**

Include:

* background script
* content script (for Claude page detection)
* tab management logic
* permissions setup

---

### 5. Technical Requirements

* Use JavaScript (no frameworks required)
* Use Chrome Tabs API to:

  * open tabs
  * track tab IDs
  * close specific tabs safely
* Use content scripts to monitor Claude page state
* Ensure performance is optimized (no heavy polling)

---

### 6. Edge Cases

* Prevent opening duplicate tabs repeatedly
* Handle user manually closing tabs
* Handle page refreshes
* Ensure system resets properly after each Claude response cycle

---

### 7. Bonus Features (optional but preferred)

* Add a toggle ON/OFF button in extension popup
* Allow user to customize which sites open
* Add delay before opening distraction tabs (e.g., 2 seconds)
* Add notification when tabs are closed

---

## 📦 Output Format

Provide:

1. Full project structure
2. All code files:

   * manifest.json
   * background.js
   * content.js
   * popup.html (if included)
3. Step-by-step instructions to install and test the extension
4. Clear explanation of how Claude detection works

---

## ⚠️ Important

* Do NOT use pseudo code
* Write production-ready code
* Ensure compatibility with latest Chrome (Manifest v3)
* Keep code clean and well-commented

---

## 🧠 Goal Quality

This should be a polished, usable tool — not a demo or rough script.
