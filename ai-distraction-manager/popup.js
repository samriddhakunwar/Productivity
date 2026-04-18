/**
 * AI Distraction Manager - Popup Script
 * Handles UI rendering, settings persistence, and status display.
 */

"use strict";

// ─── DOM References ───────────────────────────────────────────────────────────

const mainToggle    = document.getElementById("main-toggle");
const statusDot     = document.getElementById("status-dot");
const statusText    = document.getElementById("status-text");
const siteList      = document.getElementById("site-list");
const addSiteBtn    = document.getElementById("add-site-btn");
const addSiteForm   = document.getElementById("add-site-form");
const newSiteUrl    = document.getElementById("new-site-url");
const newSiteLabel  = document.getElementById("new-site-label");
const confirmAddBtn = document.getElementById("confirm-add-site");
const cancelAddBtn  = document.getElementById("cancel-add-site");
const delaySlider   = document.getElementById("delay-slider");
const delayValue    = document.getElementById("delay-value");
const notifToggle   = document.getElementById("notif-toggle");
const saveBtn       = document.getElementById("save-btn");
const saveFeedback  = document.getElementById("save-feedback");

// ─── State ────────────────────────────────────────────────────────────────────

let settings = null;

// ─── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  await loadSettings();
  renderAll();
  await refreshStatus();
});

// ─── Settings Load / Save ─────────────────────────────────────────────────────

async function loadSettings() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "GET_SETTINGS" }, (response) => {
      settings = response?.settings ?? getDefaultSettings();
      resolve();
    });
  });
}

async function saveSettings() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "SAVE_SETTINGS", settings }, (response) => {
      resolve(response?.ok);
    });
  });
}

function getDefaultSettings() {
  return {
    enabled: true,
    openDelay: 2000,
    showNotifications: true,
    sites: [
      { url: "https://www.youtube.com/shorts", enabled: true, label: "YouTube Shorts" },
      { url: "https://www.instagram.com",      enabled: true, label: "Instagram" },
      { url: "https://www.facebook.com",       enabled: true, label: "Facebook" }
    ]
  };
}

// ─── Render ───────────────────────────────────────────────────────────────────

function renderAll() {
  if (!settings) return;
  mainToggle.checked      = settings.enabled;
  delaySlider.value       = settings.openDelay;
  notifToggle.checked     = settings.showNotifications;
  delayValue.textContent  = formatDelay(settings.openDelay);
  renderSiteList();
}

function renderSiteList() {
  siteList.innerHTML = "";

  if (settings.sites.length === 0) {
    siteList.innerHTML = `<p style="font-size:11px;color:var(--clr-text-muted);padding:6px 2px;">No sites configured.</p>`;
    return;
  }

  settings.sites.forEach((site, index) => {
    const item = document.createElement("div");
    item.className = "site-item";
    item.innerHTML = `
      <img class="site-favicon"
           src="${faviconUrl(site.url)}"
           alt=""
           onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2216%22 height=%2216%22><rect width=%2216%22 height=%2216%22 fill=%22%23333%22 rx=%224%22/></svg>'" />
      <div class="site-info">
        <span class="site-label">${escapeHtml(site.label || new URL(site.url).hostname)}</span>
        <span class="site-url">${escapeHtml(site.url)}</span>
      </div>
      <div class="site-actions">
        <label class="toggle-switch toggle-sm" title="Enable/disable this site">
          <input type="checkbox" data-index="${index}" class="site-toggle" ${site.enabled ? "checked" : ""} />
          <span class="toggle-track"><span class="toggle-thumb"></span></span>
        </label>
        <button class="btn-icon-only remove-site" data-index="${index}" title="Remove site">✕</button>
      </div>
    `;
    siteList.appendChild(item);
  });

  // Bind site toggle events
  siteList.querySelectorAll(".site-toggle").forEach((checkbox) => {
    checkbox.addEventListener("change", (e) => {
      const idx = parseInt(e.target.dataset.index, 10);
      settings.sites[idx].enabled = e.target.checked;
    });
  });

  // Bind remove events
  siteList.querySelectorAll(".remove-site").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const idx = parseInt(e.target.dataset.index, 10);
      settings.sites.splice(idx, 1);
      renderSiteList();
    });
  });
}

// ─── Status ───────────────────────────────────────────────────────────────────

async function refreshStatus() {
  if (!settings?.enabled) {
    setStatus("off", "Extension is disabled");
    return;
  }

  // Query all Claude tabs for current state
  try {
    const tabs = await chrome.tabs.query({ url: ["https://claude.ai/*", "https://*.claude.ai/*"] });
    if (tabs.length === 0) {
      setStatus("idle", "No Claude tab open");
      return;
    }

    // Ask background for aggregate state
    chrome.runtime.sendMessage({ type: "GET_STATE" }, (response) => {
      if (!response) {
        setStatus("idle", "Monitoring Claude…");
        return;
      }

      const states = Object.values(response.claudeTabStates ?? {});
      const anyGenerating = states.includes("generating");

      if (anyGenerating) {
        setStatus("generating", `Claude is generating · ${response.openedTabCount} tab(s) open`);
      } else {
        setStatus("idle", `Claude is ready · Monitoring ${tabs.length} tab(s)`);
      }
    });
  } catch {
    setStatus("idle", "Monitoring Claude…");
  }
}

function setStatus(state, text) {
  statusDot.className = `status-dot ${state}`;
  statusText.textContent = text;
}

// ─── Event Listeners ──────────────────────────────────────────────────────────

// Main enable/disable toggle
mainToggle.addEventListener("change", () => {
  settings.enabled = mainToggle.checked;
  refreshStatus();
});

// Delay slider
delaySlider.addEventListener("input", () => {
  const val = parseInt(delaySlider.value, 10);
  settings.openDelay = val;
  delayValue.textContent = formatDelay(val);
});

// Notifications toggle
notifToggle.addEventListener("change", () => {
  settings.showNotifications = notifToggle.checked;
});

// Show add-site form
addSiteBtn.addEventListener("click", () => {
  addSiteForm.classList.remove("hidden");
  addSiteBtn.classList.add("hidden");
  newSiteUrl.focus();
});

// Cancel adding a site
cancelAddBtn.addEventListener("click", () => {
  addSiteForm.classList.add("hidden");
  addSiteBtn.classList.remove("hidden");
  newSiteUrl.value = "";
  newSiteLabel.value = "";
});

// Confirm adding a site
confirmAddBtn.addEventListener("click", () => {
  const rawUrl = newSiteUrl.value.trim();
  if (!rawUrl) return;

  let finalUrl = rawUrl;
  if (!finalUrl.startsWith("http://") && !finalUrl.startsWith("https://")) {
    finalUrl = "https://" + finalUrl;
  }

  try {
    new URL(finalUrl); // validate
  } catch {
    newSiteUrl.style.borderColor = "var(--clr-error)";
    newSiteUrl.focus();
    setTimeout(() => (newSiteUrl.style.borderColor = ""), 1200);
    return;
  }

  const label = newSiteLabel.value.trim() || new URL(finalUrl).hostname;
  settings.sites.push({ url: finalUrl, enabled: true, label });
  renderSiteList();

  // Reset form
  newSiteUrl.value = "";
  newSiteLabel.value = "";
  addSiteForm.classList.add("hidden");
  addSiteBtn.classList.remove("hidden");
});

// Allow Enter key in URL field
newSiteUrl.addEventListener("keydown", (e) => { if (e.key === "Enter") confirmAddBtn.click(); });

// Save button
saveBtn.addEventListener("click", async () => {
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";

  await saveSettings();

  saveBtn.disabled = false;
  saveBtn.textContent = "Save Settings";
  saveFeedback.classList.remove("hidden");
  setTimeout(() => saveFeedback.classList.add("hidden"), 2000);

  await refreshStatus();
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDelay(ms) {
  if (ms === 0) return "0s";
  if (ms < 1000) return `${ms}ms`;
  return `${ms / 1000}s`;
}

function faviconUrl(siteUrl) {
  try {
    const hostname = new URL(siteUrl).hostname;
    return `https://www.google.com/s2/favicons?domain=${hostname}&sz=32`;
  } catch {
    return "";
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
