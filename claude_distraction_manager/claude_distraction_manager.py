# -*- coding: utf-8 -*-
"""
Claude AI Distraction Manager - Desktop Automation Script
Production-Ready v2.0

Detection Method: Desktop window screenshot + pixel-diff (Antigravity app)
  - Locates the Antigravity window by partial title match.
  - Captures only that window's screen region every poll_interval seconds.
  - Compares consecutive frames: significant pixel change -> generating.
  - No DOM access, no browser APIs — works with any desktop UI.

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
# Third-party imports  (pip install pygetwindow keyboard psutil pillow)
# ---------------------------------------------------------------------------
try:
    import pygetwindow as gw          # locate Antigravity window by title
    from PIL import ImageChops, ImageStat  # pixel-diff between frames
    import PIL.ImageGrab as ImageGrab  # screen region capture
    import keyboard                   # global hotkey support
    import psutil                     # process tree management
except ImportError as exc:
    print(f"[ERROR] Missing dependency: {exc}")
    print("Run:   pip install pygetwindow keyboard psutil pillow")
    sys.exit(1)


# ===========================================================================
#  CONFIGURATION  —  edit this block to customise behaviour
# ===========================================================================

@dataclass
class Config:
    # -- Antigravity window detection ----------------------------------------
    # Partial title strings used to locate the Antigravity window.
    # Checked in order; first match wins. Case-insensitive.
    antigravity_titles: list = None

    def __post_init__(self):
        if self.antigravity_titles is None:
            self.antigravity_titles = ["antigravity", "claude"]

    # -- Detection tuning ----------------------------------------------------
    # How often (seconds) to capture and compare window screenshots.
    poll_interval: float = 1.0

    # Minimum mean pixel difference (0-255) to count as "content changing".
    # Raise if you get false positives from cursor blink / scrollbar.
    change_threshold: float = 1.2

    # How many consecutive "changed" polls before we declare "generating".
    change_streak_required: int = 2

    # How many consecutive "stable" polls before we declare "idle".
    stable_streak_required: int = 3

    # How long (seconds) to wait after detecting generating before opening
    # windows.  Avoids flicker on very short responses.
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
#  CLAUDE STATE DETECTOR  (Desktop screenshot pixel-diff — Antigravity app)
# ===========================================================================

def _find_antigravity_window(titles: list) -> Optional[object]:
    """
    Search all visible top-level windows for one whose title contains any
    of the given partial strings (case-insensitive).
    Returns a pygetwindow Window object, or None if not found.
    """
    try:
        all_windows = gw.getAllWindows()
    except Exception as exc:
        log.debug("gw.getAllWindows error: %s", exc)
        return None

    for win in all_windows:
        title_lower = (win.title or "").lower()
        for partial in titles:
            if partial.lower() in title_lower:
                return win
    return None


def _capture_window_region(win) -> Optional[object]:
    """
    Take a screenshot of the bounding box of `win`.
    Returns a PIL Image, or None if the window is minimised / off-screen.
    """
    try:
        left   = win.left
        top    = win.top
        right  = win.left + win.width
        bottom = win.top  + win.height

        # Guard against zero-size or minimised windows
        if win.width < 50 or win.height < 50:
            return None
        if right <= 0 or bottom <= 0:
            return None

        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        return img
    except Exception as exc:
        log.debug("Screenshot error: %s", exc)
        return None


def _mean_pixel_diff(img_a, img_b) -> float:
    """
    Return the mean absolute per-channel pixel difference between two
    same-size PIL Images.  Returns 0.0 if sizes differ or on any error.
    """
    try:
        if img_a.size != img_b.size:
            return 0.0
        diff = ImageChops.difference(
            img_a.convert("RGB"),
            img_b.convert("RGB"),
        )
        stat = ImageStat.Stat(diff)
        # mean across all channels
        return sum(stat.mean) / len(stat.mean)
    except Exception:
        return 0.0


class ClaudeStateDetector:
    """
    Monitors the Antigravity desktop window using screenshot-based pixel
    diffing.  No DOM or browser API access required.

    State machine:
        "generating"  ->  window content is continuously changing
                          (change_streak_required consecutive changed polls)
        "idle"        ->  window content has been stable
                          (stable_streak_required consecutive stable polls)
        "unknown"     ->  window not found / minimised
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._running: bool = False
        self._prev_frame = None          # last PIL Image capture
        self._change_streak: int = 0     # consecutive "changed" polls
        self._stable_streak: int = 0     # consecutive "stable" polls

    # ------------------------------------------------------------------
    # Lifecycle  (kept async for drop-in compatibility with orchestrator)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Locate the Antigravity window and begin monitoring."""
        self._running = True
        titles = self.cfg.antigravity_titles
        log.info("Detector started — looking for window matching: %s", titles)

        # Wait up to 30 s for the window to appear
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            win = _find_antigravity_window(titles)
            if win:
                log.info("Antigravity window found: '%s'", win.title)
                return
            log.info("Antigravity window not found — retrying in 3 s ...")
            await asyncio.sleep(3)

        log.warning(
            "Antigravity window still not found after 30 s.\n"
            "  Make sure the app is running.  Detection will continue "
            "and pick it up when it appears."
        )

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Single-poll detection
    # ------------------------------------------------------------------

    async def poll_state(self) -> str:
        """
        Capture the Antigravity window and compare with the previous frame.
        Updates change/stable streak counters and returns the current state.
        """
        titles = self.cfg.antigravity_titles
        win = _find_antigravity_window(titles)

        if win is None:
            log.debug("Antigravity window not found.")
            self._prev_frame = None
            self._change_streak = 0
            self._stable_streak = 0
            return "unknown"

        frame = await asyncio.get_running_loop().run_in_executor(
            None, _capture_window_region, win
        )

        if frame is None:
            # Window exists but is minimised / zero-size
            log.debug("Window minimised or zero-size — skipping frame.")
            self._prev_frame = None
            return "unknown"

        if self._prev_frame is None:
            # First frame — nothing to compare yet
            self._prev_frame = frame
            return "unknown"

        diff = await asyncio.get_running_loop().run_in_executor(
            None, _mean_pixel_diff, self._prev_frame, frame
        )
        self._prev_frame = frame

        log.debug("Pixel diff: %.3f  (threshold %.3f)",
                  diff, self.cfg.change_threshold)

        if diff >= self.cfg.change_threshold:
            self._change_streak += 1
            self._stable_streak = 0
        else:
            self._stable_streak += 1
            self._change_streak = 0

        if self._change_streak >= self.cfg.change_streak_required:
            return "generating"
        if self._stable_streak >= self.cfg.stable_streak_required:
            return "idle"
        # Not yet enough evidence either way
        return "unknown"

    # ------------------------------------------------------------------
    # Main detection loop  (identical contract to the old Playwright loop)
    # ------------------------------------------------------------------

    async def run_detection_loop(self, on_generating, on_idle) -> None:
        """
        Poll window content and fire callbacks on state transitions.

        `on_generating` and `on_idle` are regular (synchronous) callables
        executed in a thread-pool executor to avoid blocking the event loop.
        """
        prev_state = "unknown"
        generating_task: Optional[asyncio.Task] = None
        loop = asyncio.get_running_loop()

        while self._running:
            await asyncio.sleep(self.cfg.poll_interval)

            state = await self.poll_state()

            if state == prev_state or state == "unknown":
                continue

            log.info("Claude state: %s -> %s", prev_state, state)
            prev_state = state

            if state == "generating":
                delay = self.cfg.open_delay

                async def _delayed_open(d=delay):
                    await asyncio.sleep(d)
                    # Re-confirm still generating after the open delay
                    confirm = await self.poll_state()
                    if confirm == "generating":
                        await loop.run_in_executor(None, on_generating)

                # Cancel any pending open task before creating a new one
                if generating_task and not generating_task.done():
                    generating_task.cancel()
                generating_task = asyncio.create_task(_delayed_open())

            elif state == "idle":
                if generating_task and not generating_task.done():
                    generating_task.cancel()
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
        log.info("  Claude AI Distraction Manager  v2.0  (Antigravity mode)")
        log.info("  Window : %s", self.cfg.antigravity_titles)
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
