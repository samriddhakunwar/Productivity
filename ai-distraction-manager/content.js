/**
 * AI Distraction Manager - Content Script
 * Runs on claude.ai pages and detects when Claude is generating vs idle.
 * Uses MutationObserver for efficient, event-driven DOM monitoring.
 */

(function () {
  "use strict";

  // ─── State ──────────────────────────────────────────────────────────────────

  /** Tracks the last known state to prevent duplicate messages */
  let lastState = "idle"; // "idle" | "generating"

  /** MutationObserver watching Claude's UI */
  let observer = null;

  /** Debounce timer to prevent rapid state flipping */
  let debounceTimer = null;

  const DEBOUNCE_MS = 400;

  // ─── Claude DOM Selectors ────────────────────────────────────────────────────
  // These selectors target Claude's web UI indicators.
  // Multiple selectors are tried for resilience across layout updates.

  /**
   * Returns true if Claude is currently generating a response.
   * Detection strategy (any one match = generating):
   *   1. A "Stop generating" button is visible
   *   2. A streaming/loading indicator is present
   *   3. The send button is disabled (Claude is processing)
   *   4. A thinking/loading spinner is present
   */
  function isClaudeGenerating() {
    // 1. Stop button — the most reliable indicator
    const stopButton = document.querySelector(
      'button[aria-label*="Stop"], button[data-testid*="stop"], button.stop-button, [aria-label="Stop generating"]'
    );
    if (stopButton && isVisible(stopButton)) return true;

    // 2. Streaming content indicator (animated dots, progress bar, etc.)
    const streamIndicator = document.querySelector(
      '.loading-indicator, .streaming-indicator, [data-is-streaming="true"], .is-streaming'
    );
    if (streamIndicator && isVisible(streamIndicator)) return true;

    // 3. Send button disabled state — Claude disables it while generating
    const sendButton = document.querySelector(
      'button[aria-label*="Send"], button[data-testid*="send-button"], button[type="submit"]'
    );
    if (sendButton && sendButton.disabled) return true;

    // 4. Presence of a progress/spinner element specific to Claude
    const spinner = document.querySelector(
      '.animate-spin, [data-testid="loading-spinner"], .response-loading'
    );
    if (spinner && isVisible(spinner)) return true;

    // 5. Heuristic: check if there's an incomplete/streaming assistant message
    // Claude wraps streaming content differently from completed messages
    const incompleteMsg = document.querySelector(
      '[data-is-streaming], .font-claude-message:last-child.streaming, .response-message[data-complete="false"]'
    );
    if (incompleteMsg && isVisible(incompleteMsg)) return true;

    return false;
  }

  /**
   * Check if an element is actually visible in the viewport.
   * @param {Element} el
   * @returns {boolean}
   */
  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      style.opacity !== "0" &&
      el.offsetParent !== null
    );
  }

  // ─── State Machine ───────────────────────────────────────────────────────────

  /**
   * Evaluate current DOM state and notify background if state changed.
   */
  function evaluateState() {
    const generating = isClaudeGenerating();
    const newState = generating ? "generating" : "idle";

    if (newState === lastState) return; // No change

    lastState = newState;
    console.log(`[ADM Content] State changed → ${newState}`);

    if (newState === "generating") {
      chrome.runtime.sendMessage({ type: "CLAUDE_GENERATING" });
    } else {
      chrome.runtime.sendMessage({ type: "CLAUDE_IDLE" });
    }
  }

  /**
   * Debounced version of evaluateState to avoid rapid-fire calls
   * from MutationObserver bursts during streaming.
   */
  function debouncedEvaluate() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(evaluateState, DEBOUNCE_MS);
  }

  // ─── MutationObserver Setup ───────────────────────────────────────────────────

  /**
   * Start observing the Claude page for DOM changes.
   */
  function startObserving() {
    if (observer) {
      observer.disconnect();
    }

    // Observe the entire document body for subtree changes.
    // We watch attributes + childList to catch:
    //   - button disabled/enabled transitions
    //   - streaming content being added
    //   - spinner appearing/disappearing
    observer = new MutationObserver((mutations) => {
      // Filter to only meaningful mutations to avoid unnecessary work
      const relevant = mutations.some((m) => {
        // Attribute changes (e.g., disabled, aria-label, data-* attributes)
        if (m.type === "attributes") return true;

        // New nodes added (streaming text, spinners, etc.)
        if (m.type === "childList" && (m.addedNodes.length > 0 || m.removedNodes.length > 0)) {
          return true;
        }

        return false;
      });

      if (relevant) debouncedEvaluate();
    });

    const target = document.body || document.documentElement;
    observer.observe(target, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["disabled", "aria-label", "data-is-streaming", "class", "data-complete"]
    });

    console.log("[ADM Content] Observer started on", window.location.href);
    // Run an initial check
    evaluateState();
  }

  /**
   * Stop observing.
   */
  function stopObserving() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    console.log("[ADM Content] Observer stopped.");
  }

  // ─── SPA Navigation Handling ──────────────────────────────────────────────────
  // Claude is a Single Page Application. When navigating between conversations,
  // the page doesn't fully reload, so we must restart observation.

  let lastUrl = location.href;

  // Intercept history API to detect navigation
  const originalPushState = history.pushState.bind(history);
  const originalReplaceState = history.replaceState.bind(history);

  history.pushState = function (...args) {
    originalPushState(...args);
    onNavigation();
  };

  history.replaceState = function (...args) {
    originalReplaceState(...args);
    onNavigation();
  };

  window.addEventListener("popstate", onNavigation);

  function onNavigation() {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      console.log("[ADM Content] Navigation detected, restarting observer...");
      // Small delay to let the new page settle
      setTimeout(() => {
        lastState = "idle"; // reset state on navigation
        startObserving();
      }, 800);
    }
  }

  // ─── Init ────────────────────────────────────────────────────────────────────

  /**
   * Wait for document body to be ready before starting.
   */
  function init() {
    if (document.body) {
      startObserving();
    } else {
      document.addEventListener("DOMContentLoaded", startObserving, { once: true });
    }
  }

  // Listen for settings changes (e.g. extension toggled off)
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.settings) {
      const newSettings = changes.settings.newValue;
      if (!newSettings?.enabled) {
        stopObserving();
        // Ensure background clears state
        if (lastState === "generating") {
          chrome.runtime.sendMessage({ type: "CLAUDE_IDLE" });
          lastState = "idle";
        }
      } else {
        startObserving();
      }
    }
  });

  init();
})();
