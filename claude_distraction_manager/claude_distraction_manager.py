# -*- coding: utf-8 -*-
"""
Claude AI Distraction Manager - Desktop Automation Script
Production-Ready v1.1

Detection Method: Playwright persistent-context DOM monitoring
  - Watches claude.ai for the "Stop generating" button (aria-label).
  - Polls the live DOM every ~1s — negligible CPU cost.
  - Far more reliable than OCR or window-title polling.

Window Management: subprocess + ctypes win32 API
  - Opens a separate browser window per social site.
  - Tracks windows by OS process ID — never touches user windows.
  - Uses SetWindowPos() for pixel-perfect tiling at any resolution.
"""

import asyncio
import ctypes
import logging
import os
import subprocess
import sys
import time
import threading
from dataclasses import dataclass
from typing import Optional
import winreg

# ---------------------------------------------------------------------------
# Third-party imports  (pip install playwright pygetwindow keyboard psutil)
# ---------------------------------------------------------------------------
try:
    import pygetwindow as gw          # noqa: F401  (kept for optional helpers)
    from playwright.async_api import async_playwright, Page
    import keyboard                   # global hotkey support
    import psutil                     # process tree management
except ImportError as exc:
    print(f"[ERROR] Missing dependency: {exc}")
    print("Run:   pip install playwright pygetwindow keyboard psutil")
    print("Then:  python -m playwright install chromium")
    sys.exit(1)


# ===========================================================================
#  CONFIGURATION  —  edit this block to customise behaviour
# ===========================================================================

@dataclass
class Config:
    # -- Claude interface URL ------------------------------------------------
    # Use "https://claude.ai" for the web app,
    # or e.g. "http://localhost:3000" for a local Antigravity instance.
    claude_url: str = "https://claude.ai"

    # -- Detection tuning ----------------------------------------------------
    # How often (seconds) to poll the DOM for the stop button.
    poll_interval: float = 1.0

    # How long (seconds) to wait after Claude starts generating before
    # opening windows.  Avoids flicker on very short responses.
    open_delay: float = 2.5

    # -- Social media URLs ---------------------------------------------------
    instagram_url: str = "https://www.instagram.com/reels/"
    youtube_url: str   = "https://www.youtube.com/shorts"
    facebook_url: str  = "https://www.facebook.com"

    # -- Browser executable --------------------------------------------------
    # Leave empty to auto-detect Chrome / Edge from registry & common paths.
    browser_exe: str = ""

    # -- Hotkey --------------------------------------------------------------
    toggle_hotkey: str = "ctrl+shift+d"

    # -- Logging -------------------------------------------------------------
    log_file: str = "distraction_manager.log"
    log_level: int = logging.INFO


CONFIG = Config()


# ===========================================================================
#  LOGGING
# ===========================================================================

def _setup_logging(cfg: Config) -> logging.Logger:
    logger = logging.getLogger("DistractionManager")
    logger.setLevel(cfg.log_level)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s",
                            datefmt="%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    fh = logging.FileHandler(cfg.log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


log = _setup_logging(CONFIG)


# ===========================================================================
#  SCREEN UTILITIES
# ===========================================================================

@dataclass
class ScreenRect:
    x: int
    y: int
    w: int
    h: int

    def __str__(self) -> str:
        return f"({self.x}, {self.y})  {self.w} x {self.h}"


def get_screen_size() -> tuple[int, int]:
    """Return (width, height) in physical pixels, DPI-aware."""
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def compute_layouts(sw: int, sh: int) -> dict[str, ScreenRect]:
    """
    Build window rects for the three social sites.

    Layout diagram:
        +-------------------+----------+
        |                   | YouTube  |  <- top-right   25%
        |    Instagram      +----------+
        |    (left 50%)     | Facebook |  <- bottom-right 25%
        +-------------------+----------+
    """
    half_w = sw // 2
    half_h = sh // 2
    return {
        "instagram": ScreenRect(0,      0,      half_w, sh),
        "youtube":   ScreenRect(half_w, 0,      half_w, half_h),
        "facebook":  ScreenRect(half_w, half_h, half_w, half_h),
    }


# ===========================================================================
#  BROWSER AUTO-DETECTION
# ===========================================================================

_REG_PATHS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
]

_COMMON_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser_exe() -> str:
    """Return the path to Chrome or Edge, auto-detected from registry/paths."""
    if CONFIG.browser_exe and os.path.isfile(CONFIG.browser_exe):
        return CONFIG.browser_exe

    for reg_path in _REG_PATHS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if os.path.isfile(val):
                    return val
        except OSError:
            pass

    for path in _COMMON_PATHS:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Cannot find Chrome or Edge.\n"
        "Set  CONFIG.browser_exe  to your browser executable path."
    )


# ===========================================================================
#  WIN32 WINDOW PLACEMENT
# ===========================================================================

_user32    = ctypes.windll.user32
_SW_RESTORE = 9
_SWP_SHOW   = 0x0040  # SWP_SHOWWINDOW

# Callback type for EnumWindows
_EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)


def _move_window(hwnd: int, rect: ScreenRect, retries: int = 5) -> bool:
    """Restore + resize a window to the given rect using raw Win32."""
    for _ in range(retries):
        _user32.ShowWindow(hwnd, _SW_RESTORE)
        ok = _user32.SetWindowPos(hwnd, 0, rect.x, rect.y, rect.w, rect.h, _SWP_SHOW)
        if ok:
            return True
        time.sleep(0.25)
    log.warning("SetWindowPos failed for HWND %s after %d retries", hwnd, retries)
    return False


def _find_hwnd_for_pid(pid: int, timeout: float = 12.0) -> Optional[int]:
    """
    Poll top-level windows until one owned by `pid` is visible.
    Returns the HWND or None on timeout.
    """
    found: list[int] = []

    def _cb(hwnd: int, _: int) -> bool:
        buf = ctypes.c_ulong()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(buf))
        if buf.value == pid and _user32.IsWindowVisible(hwnd):
            rc = (ctypes.c_long * 4)()
            ctypes.windll.user32.GetWindowRect(hwnd, rc)
            if (rc[2] - rc[0]) > 200 and (rc[3] - rc[1]) > 200:
                found.append(hwnd)
        return True

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found.clear()
        _user32.EnumWindows(_EnumProc(_cb), 0)
        if found:
            return found[0]
        time.sleep(0.35)
    return None


# ===========================================================================
#  SOCIAL WINDOW MANAGER
# ===========================================================================

@dataclass
class _ManagedWindow:
    name: str
    url: str
    proc: Optional[subprocess.Popen] = None
    hwnd: Optional[int] = None
    pid: Optional[int] = None


class SocialWindowManager:
    """
    Spawns, tiles, and closes the three social media browser windows.
    Tracks windows by process ID — never interferes with user's own windows.
    """

    def __init__(self, browser_exe: str) -> None:
        self._exe = browser_exe
        self._windows: dict[str, _ManagedWindow] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_all(self) -> None:
        """Launch and tile all three social media windows."""
        with self._lock:
            if self._windows:
                log.debug("Windows already open — skipping duplicate launch.")
                return

        sw, sh = get_screen_size()
        layouts = compute_layouts(sw, sh)

        sites = [
            _ManagedWindow("instagram", CONFIG.instagram_url),
            _ManagedWindow("youtube",   CONFIG.youtube_url),
            _ManagedWindow("facebook",  CONFIG.facebook_url),
        ]

        opened: dict[str, _ManagedWindow] = {}

        for site in sites:
            try:
                proc = self._spawn(site.url)
                site.proc = proc
                site.pid  = proc.pid
                log.info("Launched %-12s PID %d", site.name, proc.pid)
            except Exception as exc:
                log.error("Failed to launch %s: %s", site.name, exc)
                continue

            hwnd = _find_hwnd_for_pid(proc.pid)
            if hwnd is None:
                log.warning("Window not found for %s — cannot tile.", site.name)
            else:
                site.hwnd = hwnd
                rect = layouts[site.name]
                log.info("Tiling %-12s -> %s", site.name, rect)
                _move_window(hwnd, rect)

            opened[site.name] = site

        with self._lock:
            self._windows = opened

        log.info("[OK] All social windows open and arranged.")

    def close_all(self) -> None:
        """Terminate every window opened by this manager."""
        with self._lock:
            if not self._windows:
                return
            targets = list(self._windows.values())
            self._windows.clear()

        for site in targets:
            self._kill(site)

        log.info("[CLOSED] All social windows terminated.")

    def prune_dead(self) -> None:
        """Drop entries for windows the user manually closed."""
        with self._lock:
            dead = [n for n, s in self._windows.items()
                    if s.proc and s.proc.poll() is not None]
            for name in dead:
                log.debug("'%s' was closed externally — untracking.", name)
                del self._windows[name]

    @property
    def are_open(self) -> bool:
        with self._lock:
            return bool(self._windows)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _spawn(self, url: str) -> subprocess.Popen:
        """
        Open a new browser window in a dedicated profile so it does not
        merge with or pollute the user's normal Chrome session.
        """
        cmd = [
            self._exe,
            "--new-window",
            "--profile-directory=DistractionManager",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=TranslateUI",
            url,
        ]
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def _kill(self, site: _ManagedWindow) -> None:
        """Gracefully terminate a managed window and all its child processes."""
        if site.proc:
            try:
                site.proc.terminate()
                try:
                    site.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    site.proc.kill()
            except Exception as exc:
                log.debug("Error terminating %s: %s", site.name, exc)

        # Chrome spawns renderer, GPU, and utility sub-processes — kill them all
        if site.pid:
            try:
                parent = psutil.Process(site.pid)
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


# ===========================================================================
#  CLAUDE STATE DETECTOR  (Playwright DOM polling)
# ===========================================================================

# Ordered list of CSS selectors for Claude's "Stop generating" button.
# Using multiple selectors makes detection resilient to DOM refactors.
_STOP_SELECTORS: list[str] = [
    # Primary: aria-label (most stable across Claude versions)
    'button[aria-label="Stop generating"]',
    'button[aria-label*="Stop"]',
    # Secondary: the square SVG icon inside the stop button
    'button svg rect[width="10"][height="10"]',
    # Tertiary: data attribute fallback
    'button[data-value="stop"]',
    # Heuristic: any SVG rect inside a button (last resort)
    'button svg[viewBox] rect',
]

# Selector that is present ONLY when Claude is ready for input
_SEND_SELECTOR = 'button[aria-label="Send message"]'

# Selector to detect the login page (so we can prompt user to log in)
_LOGIN_SELECTOR = 'input[type="email"], button[data-testid="login-button"], a[href*="login"]'


class ClaudeStateDetector:
    """
    Opens a persistent Playwright Chromium window on Claude.ai.
    Polls the DOM every `poll_interval` seconds for the stop button.

    State machine:
        "generating"  ->  stop button is visible
        "idle"        ->  stop button gone (send button may be present)
        "unknown"     ->  page not loaded / navigating / error
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pw = None
        self._page: Optional[Page] = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the monitoring browser and navigate to Claude."""
        log.info("Starting detector -> %s", self.cfg.claude_url)
        self._pw = await async_playwright().start()

        # Persistent context = Claude login session survives restarts
        profile_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "DistractionManager", "pw-profile"
        )
        os.makedirs(profile_dir, exist_ok=True)

        ctx = await self._pw.chromium.launch_persistent_context(
            profile_dir,
            headless=False,                     # Must be visible for login
            args=[
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
            ],
            no_viewport=True,                   # Use the OS window size
        )

        self._page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        self._running = True

        log.info("Navigating to Claude ...")
        try:
            await self._page.goto(
                self.cfg.claude_url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )
        except Exception as exc:
            log.warning("Navigation note: %s", exc)

        await self._prompt_login_if_needed()

    async def stop(self) -> None:
        self._running = False
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Login detection
    # ------------------------------------------------------------------

    async def _prompt_login_if_needed(self) -> None:
        """If Claude's login page is shown, wait for the user to log in."""
        try:
            el = await self._page.query_selector(_LOGIN_SELECTOR)
            if el:
                log.info("")
                log.info("=" * 60)
                log.info("  ACTION REQUIRED: Please log into Claude in the")
                log.info("  browser window that just opened, then come back.")
                log.info("  The script will start monitoring automatically.")
                log.info("=" * 60)
                log.info("")
                # Wait until the login element disappears (user logged in)
                await self._page.wait_for_selector(
                    _LOGIN_SELECTOR,
                    state="hidden",
                    timeout=300_000,   # 5-minute login window
                )
                log.info("Login detected — monitoring started.")
        except Exception:
            pass  # Best-effort; non-critical

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll_state(self) -> str:
        """Return 'generating', 'idle', or 'unknown'."""
        if self._page is None:
            return "unknown"
        try:
            for selector in _STOP_SELECTORS:
                el = await self._page.query_selector(selector)
                if el and await el.is_visible():
                    return "generating"
            return "idle"
        except Exception as exc:
            log.debug("Poll error: %s", exc)
            return "unknown"

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_detection_loop(self, on_generating, on_idle) -> None:
        """
        Poll Claude's state and fire callbacks on transitions.

        `on_generating` and `on_idle` are regular (synchronous) callables
        executed in a thread-pool executor to avoid blocking the event loop.
        """
        prev_state = "unknown"
        loop = asyncio.get_running_loop()   # 3.10+ recommended API

        while self._running:
            await asyncio.sleep(self.cfg.poll_interval)

            state = await self.poll_state()

            if state == prev_state:
                continue

            log.info("Claude state: %s -> %s", prev_state, state)
            prev_state = state

            if state == "generating":
                # Capture cfg reference to avoid closure issue
                delay = self.cfg.open_delay

                async def _delayed_open(d=delay):
                    await asyncio.sleep(d)
                    # Re-confirm still generating after delay
                    if await self.poll_state() == "generating":
                        await loop.run_in_executor(None, on_generating)

                asyncio.create_task(_delayed_open())

            elif state == "idle":
                await loop.run_in_executor(None, on_idle)


# ===========================================================================
#  ORCHESTRATOR
# ===========================================================================

class DistractionManager:
    """
    Wires ClaudeStateDetector to SocialWindowManager.
    Handles the toggle hotkey and graceful shutdown.
    """

    def __init__(self) -> None:
        self.cfg = CONFIG
        self.enabled: bool = True

        browser_exe = find_browser_exe()
        log.info("Browser: %s", browser_exe)

        self.window_mgr = SocialWindowManager(browser_exe)
        self.detector   = ClaudeStateDetector(self.cfg)

        log.info("Toggle hotkey: %s", self.cfg.toggle_hotkey)
        keyboard.add_hotkey(self.cfg.toggle_hotkey, self._toggle, suppress=False)

    # ------------------------------------------------------------------
    # State-change callbacks
    # ------------------------------------------------------------------

    def on_generating(self) -> None:
        if not self.enabled:
            log.info("[PAUSED] Skipping open (manager is disabled).")
            return
        if self.window_mgr.are_open:
            return
        log.info("Claude is generating — opening social windows ...")
        self.window_mgr.open_all()

    def on_idle(self) -> None:
        if not self.window_mgr.are_open:
            return
        log.info("Claude finished — closing social windows ...")
        self.window_mgr.close_all()

    # ------------------------------------------------------------------
    # Hotkey handler
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        self.enabled = not self.enabled
        state_str = "ENABLED" if self.enabled else "DISABLED"
        log.info("Distraction Manager: %s", state_str)
        if not self.enabled:
            self.window_mgr.close_all()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self) -> None:
        log.info("=" * 60)
        log.info("  Claude AI Distraction Manager  v1.1")
        log.info("  Toggle : %s", self.cfg.toggle_hotkey)
        log.info("  Log    : %s", os.path.abspath(self.cfg.log_file))
        log.info("=" * 60)

        try:
            await self.detector.start()

            # Background task: prune windows the user closed manually
            async def _prune_loop():
                while True:
                    await asyncio.sleep(5)
                    self.window_mgr.prune_dead()

            asyncio.create_task(_prune_loop())

            await self.detector.run_detection_loop(
                on_generating=self.on_generating,
                on_idle=self.on_idle,
            )

        except (asyncio.CancelledError, KeyboardInterrupt):
            log.info("Interrupted.")
        finally:
            log.info("Shutting down ...")
            self.window_mgr.close_all()
            await self.detector.stop()
            log.info("Goodbye.")


# ===========================================================================
#  ENTRY POINT
# ===========================================================================

def main() -> None:
    # Enable per-monitor DPI awareness for correct screen metrics
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

    # Force UTF-8 output on Windows console
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    manager = DistractionManager()

    try:
        asyncio.run(manager.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
