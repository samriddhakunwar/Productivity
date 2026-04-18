/**
 * AI Distraction Manager - Background Service Worker
 * Handles tab creation, tracking, and cleanup when Claude is generating responses.
 */

// ─── State ────────────────────────────────────────────────────────────────────

/** Set of tab IDs opened by this extension */
const openedTabIds = new Set();

/** Whether Claude is currently generating (per tab, keyed by Claude's tab ID) */
const claudeTabStates = new Map();

/** Delay timer before opening distraction tabs */
let openDelayTimer = null;

/** Default settings */
const DEFAULT_SETTINGS = {
  enabled: true,
  openDelay: 2000, // ms before opening tabs
  showNotifications: true,
  sites: [
    { url: "https://www.youtube.com/shorts", enabled: true, label: "YouTube Shorts" },
    { url: "https://www.instagram.com",      enabled: true, label: "Instagram" },
    { url: "https://www.facebook.com",       enabled: true, label: "Facebook" }
  ]
};

// ─── Initialization ───────────────────────────────────────────────────────────

/**
 * On install, seed storage with default settings.
 */
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get("settings", (result) => {
    if (!result.settings) {
      chrome.storage.sync.set({ settings: DEFAULT_SETTINGS });
    }
  });
  console.log("[ADM] Extension installed and ready.");
});

// ─── Message Handling ─────────────────────────────────────────────────────────

/**
 * Listen for messages from content scripts.
 * Expected message shapes:
 *   { type: "CLAUDE_GENERATING", claudeTabId: number }
 *   { type: "CLAUDE_IDLE",       claudeTabId: number }
 *   { type: "GET_STATE" }
 *   { type: "GET_SETTINGS" }
 *   { type: "SAVE_SETTINGS", settings: object }
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const claudeTabId = message.claudeTabId ?? sender.tab?.id;

  switch (message.type) {
    case "CLAUDE_GENERATING":
      handleClaudeGenerating(claudeTabId);
      sendResponse({ ok: true });
      break;

    case "CLAUDE_IDLE":
      handleClaudeIdle(claudeTabId);
      sendResponse({ ok: true });
      break;

    case "GET_STATE":
      sendResponse({
        enabled: true,
        openedTabCount: openedTabIds.size,
        claudeTabStates: Object.fromEntries(claudeTabStates)
      });
      break;

    case "GET_SETTINGS":
      chrome.storage.sync.get("settings", (result) => {
        sendResponse({ settings: result.settings ?? DEFAULT_SETTINGS });
      });
      return true; // keep channel open for async response

    case "SAVE_SETTINGS":
      chrome.storage.sync.set({ settings: message.settings }, () => {
        sendResponse({ ok: true });
      });
      return true;

    default:
      console.warn("[ADM] Unknown message type:", message.type);
  }
});

// ─── Tab Event Listeners ──────────────────────────────────────────────────────

/**
 * If the user manually closes one of our opened tabs, remove it from tracking.
 */
chrome.tabs.onRemoved.addListener((tabId) => {
  if (openedTabIds.has(tabId)) {
    openedTabIds.delete(tabId);
    console.log(`[ADM] Tracked tab ${tabId} was closed manually.`);
  }
});

// ─── Core Logic ───────────────────────────────────────────────────────────────

/**
 * Called when Claude starts generating a response.
 * @param {number} claudeTabId
 */
async function handleClaudeGenerating(claudeTabId) {
  const settings = await getSettings();

  if (!settings.enabled) {
    console.log("[ADM] Extension is disabled, skipping tab open.");
    return;
  }

  // If already marked as generating for this tab, skip
  if (claudeTabStates.get(claudeTabId) === "generating") return;

  claudeTabStates.set(claudeTabId, "generating");
  console.log(`[ADM] Claude generating on tab ${claudeTabId}. Opening distraction tabs in ${settings.openDelay}ms...`);

  // Clear any pending timer
  if (openDelayTimer) {
    clearTimeout(openDelayTimer);
    openDelayTimer = null;
  }

  openDelayTimer = setTimeout(async () => {
    // Double-check state hasn't changed during the delay
    if (claudeTabStates.get(claudeTabId) !== "generating") return;

    // Avoid opening if tabs are already open
    if (openedTabIds.size > 0) {
      console.log("[ADM] Distraction tabs already open, skipping.");
      return;
    }

    await openDistractionTabs(settings, claudeTabId);
  }, settings.openDelay);
}

/**
 * Called when Claude finishes generating or is waiting for input.
 * @param {number} claudeTabId
 */
async function handleClaudeIdle(claudeTabId) {
  const wasGenerating = claudeTabStates.get(claudeTabId) === "generating";
  claudeTabStates.set(claudeTabId, "idle");

  // Cancel any pending open timer
  if (openDelayTimer) {
    clearTimeout(openDelayTimer);
    openDelayTimer = null;
    console.log("[ADM] Claude became idle before delay elapsed — cancelled tab open.");
  }

  if (wasGenerating && openedTabIds.size > 0) {
    console.log(`[ADM] Claude idle on tab ${claudeTabId}. Closing distraction tabs...`);
    await closeDistractionTabs();

    const settings = await getSettings();
    if (settings.showNotifications) {
      showNotification("Claude is ready!", "Distraction tabs have been closed. Time to get back to work! 🚀");
    }
  }
}

/**
 * Opens enabled distraction sites in new background tabs.
 * @param {object} settings
 * @param {number} claudeTabId - The Claude tab to keep focus on
 */
async function openDistractionTabs(settings, claudeTabId) {
  const enabledSites = settings.sites.filter((s) => s.enabled);
  if (enabledSites.length === 0) {
    console.log("[ADM] No enabled sites to open.");
    return;
  }

  console.log(`[ADM] Opening ${enabledSites.length} distraction tab(s)...`);

  for (const site of enabledSites) {
    try {
      const tab = await chrome.tabs.create({
        url: site.url,
        active: false // open in background, keep focus on Claude
      });
      openedTabIds.add(tab.id);
      console.log(`[ADM] Opened tab ${tab.id} → ${site.url}`);
    } catch (err) {
      console.error(`[ADM] Failed to open ${site.url}:`, err);
    }
  }
}

/**
 * Closes all tabs that were opened by this extension.
 */
async function closeDistractionTabs() {
  if (openedTabIds.size === 0) return;

  const tabIdsToClose = [...openedTabIds];
  openedTabIds.clear();

  // Filter to only tabs that still exist
  const existingTabs = await Promise.allSettled(
    tabIdsToClose.map((id) => chrome.tabs.get(id))
  );

  const stillOpenIds = existingTabs
    .filter((r) => r.status === "fulfilled")
    .map((r) => r.value.id);

  if (stillOpenIds.length === 0) {
    console.log("[ADM] No distraction tabs left to close (all manually closed).");
    return;
  }

  try {
    await chrome.tabs.remove(stillOpenIds);
    console.log(`[ADM] Closed ${stillOpenIds.length} distraction tab(s).`);
  } catch (err) {
    console.error("[ADM] Error closing tabs:", err);
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Retrieve settings from storage with fallback to defaults.
 * @returns {Promise<object>}
 */
function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get("settings", (result) => {
      resolve(result.settings ?? DEFAULT_SETTINGS);
    });
  });
}

/**
 * Show a Chrome notification.
 * @param {string} title
 * @param {string} message
 */
function showNotification(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
    priority: 1
  });
}
