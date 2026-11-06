"""The Python side of the browser-control layer.

RESPONSIBILITY SPLIT (brief section 4)
--------------------------------------
    shell_scripts/*.sh   keyboard, mouse, clipboard, window ids.  No job
                         roles, no city list, no business rules.
    this module          runs those scripts, parses what they say, turns
                         their exit codes into named Python exceptions, and
                         owns every timeout and delay as configuration.

THE PROTOCOL
------------
Each script prints machine-readable results on stdout as ``RESULT:key=value``
and everything else on stderr, then exits with a code that classifies the
failure.  So parsing is exact rather than heuristic, and a failure is
reported as the thing that actually went wrong -- which is brief section
22's requirement: "Do not treat all failures as HTTP 403."
"""

import json
import os
import shlex
import subprocess
import time

# ---------------------------------------------------------------------------
# EXIT CODES -- these mirror shell_scripts/_common.sh exactly.
# ---------------------------------------------------------------------------
EX_OK = 0
EX_USAGE = 2
EX_NO_DEPENDENCY = 10
EX_NO_DISPLAY = 11
EX_LAUNCH = 12
EX_NO_WINDOW = 13
EX_FOCUS = 14
EX_FULLSCREEN = 15
EX_NAVIGATION = 16
EX_CONTEXT_MENU = 17
EX_CLIPBOARD_EMPTY = 18
EX_CLIPBOARD_STALE = 19
EX_IDENTITY = 20
EX_ACCESS_DENIED = 21


# ---------------------------------------------------------------------------
# EXCEPTIONS -- one per failure class the brief names in section 22.
# ---------------------------------------------------------------------------

class BrowserError(RuntimeError):
    """Base: something in the browser-control layer failed.

    ``stage`` is the script that failed, ``code`` its exit status and
    ``results`` whatever it managed to report before giving up -- all three
    go into the log line, so a failure can be placed in the browser, the
    clipboard, the extractor, Excel or the checkpoint without guessing.
    """

    def __init__(self, message, stage="", code=None, results=None,
                 stderr=""):
        super(BrowserError, self).__init__(message)
        self.stage = stage
        self.code = code
        self.results = results or {}
        self.stderr = stderr

    def detail(self):
        parts = [str(self)]
        if self.stage:
            parts.append("stage=%s" % self.stage)
        if self.code is not None:
            parts.append("exit=%s" % self.code)
        return " | ".join(parts)


class MissingDependency(BrowserError):
    """firefox, xdotool, xclip or xprop is not installed."""


class NoDisplay(BrowserError):
    """There is no usable X display to drive."""


class BrowserLaunchFailed(BrowserError):
    """Firefox would not start."""


class WindowNotFound(BrowserError):
    """A window that should exist does not."""


class FocusFailed(BrowserError):
    """A window would not take keyboard focus."""


class FullscreenFailed(BrowserError):
    """Fullscreen could not be established or verified (brief section 4)."""


class NavigationFailed(BrowserError):
    """The expected page did not appear."""


class ContextMenuFailed(BrowserError):
    """Right-click + Down + Return did not open a job window."""


class ClipboardEmpty(BrowserError):
    """The copy produced nothing."""


class ClipboardStale(BrowserError):
    """The clipboard still held this run's nonce: nothing was copied.

    This is the failure the college scripts cannot see.  Treating it as its
    own class is what stops the previous job's text being saved as the
    current job's description.
    """


class WrongJobWindow(BrowserError):
    """The window is not the job that was asked for."""


class AccessDenied(BrowserError):
    """The page is an access refusal.

    Raised ONLY when a page actually says so.  Every other failure gets its
    own class above, because the brief forbids reporting an unrelated
    failure as a refusal -- and forbids working around a real one.
    """


_BY_CODE = {
    EX_NO_DEPENDENCY: MissingDependency,
    EX_NO_DISPLAY: NoDisplay,
    EX_LAUNCH: BrowserLaunchFailed,
    EX_NO_WINDOW: WindowNotFound,
    EX_FOCUS: FocusFailed,
    EX_FULLSCREEN: FullscreenFailed,
    EX_NAVIGATION: NavigationFailed,
    EX_CONTEXT_MENU: ContextMenuFailed,
    EX_CLIPBOARD_EMPTY: ClipboardEmpty,
    EX_CLIPBOARD_STALE: ClipboardStale,
    EX_IDENTITY: WrongJobWindow,
    EX_ACCESS_DENIED: AccessDenied,
}


def exception_for(code):
    """The exception class a shell exit code maps to."""
    return _BY_CODE.get(int(code), BrowserError)


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

class ControllerConfig(object):
    """Everything the browser layer can be tuned with.

    Built by ``find_indeed_job.build_controller_config()`` from the single
    block of settings at the top of that file, so there are no timings
    buried in the code (brief section 21: "Do not use hardcoded timings
    throughout the code").
    """

    def __init__(self, project_dir, rank=1, base_url="https://in.indeed.com",
                 firefox_binary="firefox", display=None,
                 xauth_copy=None,
                 search_mode="form",
                 search_field_delay_seconds=7.0,
                 search_results_wait_seconds=10.0,
                 card_x=430, first_card_y=440, card_max_y=1000,
                 card_probe_step=55, card_probe_limit=12,
                 card_url_marker="vjk=",
                 window_size=(1845, 1046), window_pos=(0, 34),
                 what_xy=(700, 240), where_xy=(1100, 240),
                 pre_close_delay_seconds=10.0,
                 post_close_delay_seconds=10.0,
                 window_timeout=30, focus_timeout=10,
                 clipboard_timeout=10, page_settle_seconds=3.0,
                 poll_interval=0.25, key_delay_ms=40,
                 min_detail_chars=400, script_timeout=180,
                 xclip_timeout=5,
                 url_must_match=r"(viewjob|/rc/clk|/pagead/clk|jk=|job_detail)",
                 verbose=True, logger=None):
        self.project_dir = os.path.abspath(project_dir)
        self.rank = int(rank)
        self.base_url = base_url
        self.firefox_binary = firefox_binary
        self.display = display
        # An XAUTHORITY the snap can read.  See _common.sh FACT 2.
        self.xauth_copy = xauth_copy
        self.search_mode = search_mode
        # Settle time after Indeed loads, before its search boxes are clicked.
        self.search_field_delay_seconds = float(search_field_delay_seconds)
        # Wait after Return, before the first job card is selected.  This is
        # what replaced the post-search url/title verification: the search
        # is given time to land and the run then goes straight to the card.
        self.search_results_wait_seconds = float(search_results_wait_seconds)
        # Where the job cards are in the results column.
        #
        # NOTE WHAT IS NOT HERE ANY MORE: card_pitch.  Indeed's cards are
        # not a fixed height -- measured on one real page they were 259 and
        # 191 pixels apart, and the SELECTED card is taller again because it
        # expands.  Multiplying an index by a pitch therefore clicked the
        # same card twice and missed the third.  select_job_card.sh probes
        # downward instead and reports the y that worked.
        self.card_x = int(card_x)
        self.first_card_y = int(first_card_y)
        self.card_max_y = int(card_max_y)
        self.card_probe_step = int(card_probe_step)
        self.card_probe_limit = int(card_probe_limit)
        # The query parameter Indeed puts the selected job's key in.
        self.card_url_marker = card_url_marker
        # NORMAL WINDOW (not fullscreen), sized to the supplied screenshot.
        self.window_size = tuple(window_size)
        self.window_pos = tuple(window_pos)
        # Indeed's two search boxes, in screen coordinates for that window.
        self.what_xy = tuple(what_xy)
        self.where_xy = tuple(where_xy)
        self.pre_close_delay_seconds = float(pre_close_delay_seconds)
        self.post_close_delay_seconds = float(post_close_delay_seconds)
        self.window_timeout = int(window_timeout)
        self.focus_timeout = int(focus_timeout)
        self.clipboard_timeout = int(clipboard_timeout)
        self.page_settle_seconds = float(page_settle_seconds)
        self.poll_interval = float(poll_interval)
        self.key_delay_ms = int(key_delay_ms)
        self.min_detail_chars = int(min_detail_chars)
        self.script_timeout = int(script_timeout)
        # Every `xclip` call is wrapped in `timeout` by the shell layer,
        # because `xclip -o` can block forever against a Chromium-based
        # browser mid-transfer. See _common.sh, "MEASURED HAZARD".
        self.xclip_timeout = int(xclip_timeout)
        self.url_must_match = url_must_match
        self.verbose = bool(verbose)
        self.logger = logger or (lambda message: None)

    # -- paths --------------------------------------------------------------
    @property
    def shell_dir(self):
        return os.path.join(self.project_dir, "shell_scripts")

    @property
    def temp_dir(self):
        """``Temp_Data/rank_N`` -- independent per rank (brief section 14)."""
        return os.path.join(self.project_dir, "Temp_Data",
                            "rank_%d" % self.rank)

    @property
    def profile_dir(self):
        """A browser profile of this project's own.

        Restriction 6: "Do not reuse production browser sessions
        automatically."  This directory is created by this project, used
        only by this project, and is per-rank so two ranks cannot fight
        over one profile lock.
        """
        return os.path.join(self.project_dir, "config", "firefox_profile",
                            "rank_%d" % self.rank)

    @property
    def window_state_file(self):
        return os.path.join(self.temp_dir, "browser_window.json")

    def script(self, name):
        return os.path.join(self.shell_dir, name)

    def environment(self):
        """The environment every shell script inherits.

        Every timing the scripts use is passed in here, which is what makes
        "keep it configurable" true rather than aspirational.
        """
        env = dict(os.environ)
        env.update({
            "POLL_INTERVAL": str(self.poll_interval),
            "WINDOW_TIMEOUT": str(self.window_timeout),
            "FOCUS_TIMEOUT": str(self.focus_timeout),
            "CLIPBOARD_TIMEOUT": str(self.clipboard_timeout),
            "XCLIP_TIMEOUT": str(self.xclip_timeout),
            "PAGE_SETTLE_SECONDS": str(self.page_settle_seconds),
            "KEY_DELAY_MS": str(self.key_delay_ms),
            "FIREFOX_BIN": self.firefox_binary,
            "CARD_X": str(self.card_x),
            "START_Y": str(self.first_card_y),
            "CARD_MAX_Y": str(self.card_max_y),
            "PROBE_STEP": str(self.card_probe_step),
            "PROBE_LIMIT": str(self.card_probe_limit),
            "WINDOW_WIDTH": str(self.window_size[0]),
            "WINDOW_HEIGHT": str(self.window_size[1]),
            "WINDOW_X": str(self.window_pos[0]),
            "WINDOW_Y": str(self.window_pos[1]),
            "SEARCH_MODE": str(self.search_mode),
            "SEARCH_FIELD_DELAY_SECONDS": str(self.search_field_delay_seconds),
            "SEARCH_RESULTS_WAIT_SECONDS": str(self.search_results_wait_seconds),
            "VERBOSE_SHELL": "1" if self.verbose else "0",
        })
        if self.display:
            env["DISPLAY"] = self.display
        if self.xauth_copy:
            # The snap cannot always read the live mutter Xauthority; a copy
            # under $HOME can be. See _common.sh FACT 2.
            env["FIREFOX_XAUTH_COPY"] = str(self.xauth_copy)
        return env


# ---------------------------------------------------------------------------
# THE CONTROLLER
# ---------------------------------------------------------------------------

class JobWindow(object):
    """One open job-detail window: its id and the url it actually holds."""

    def __init__(self, window_id, url, fullscreen=True, job_key=""):
        self.window_id = str(window_id)
        self.url = str(url)
        self.fullscreen = bool(fullscreen)
        #: The job's own key from the url (Indeed's vjk=/jk=), when it has
        #: one.  This is the only stable identity a job has here.
        self.job_key = str(job_key)
        #: "preselected" when Indeed had already selected it, "click" when
        #: a probe found it.  Worth logging: an all-"click" run means the
        #: pre-selection detection is not firing.
        self.selection_method = ""
        #: The y a probe actually landed on, so the caller can start the
        #: next card's probe below it instead of guessing a pitch.
        self.learned_card_y = 0

    def __repr__(self):                                  # pragma: no cover
        return "JobWindow(%s, %r)" % (self.window_id, self.url)


class IndeedController(object):
    """Drives Firefox through the shell scripts.  Owns no business rules."""

    def __init__(self, config):
        self.config = config
        self.firefox_pid = None
        #: The job Indeed auto-selected on the current results page.
        self.preselected_key = ""
        self.listing_window = None
        self.open_job_windows = []
        self._last_results = {}

    # -- logging ------------------------------------------------------------
    def log(self, message):
        self.config.logger(message)

    # -- running a script ---------------------------------------------------
    def run_script(self, name, args, timeout=None, allow_codes=()):
        """Run one shell script.  Returns ``(code, results, stderr)``.

        Raises the mapped exception for any non-zero code that is not in
        ``allow_codes``, so a caller that wants to handle a failure itself
        can, and a caller that does not gets a named exception rather than
        a silent zero.
        """
        path = self.config.script(name)
        if not os.path.isfile(path):
            raise MissingDependency("shell script not found: %s" % path,
                                    stage=name)
        if not os.access(path, os.X_OK):
            os.chmod(path, 0o755)

        command = [path] + [str(part) for part in args]
        timeout = int(timeout or self.config.script_timeout)

        if self.config.verbose:
            self.log("      $ %s" % " ".join(shlex.quote(c) for c in command))

        started = time.time()
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self.config.environment(), timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise BrowserError(
                "%s did not finish within %ss. The desktop may be blocked by "
                "a modal dialog or a pointer grab." % (name, timeout),
                stage=name, code=None)
        except OSError as error:
            raise MissingDependency("cannot run %s: %s" % (path, error),
                                    stage=name)

        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
        results = parse_results(stdout)
        self._last_results = results
        elapsed = time.time() - started

        if self.config.verbose:
            for line in stderr.strip().splitlines():
                self.log("        %s" % line)
            self.log("        -> exit %d in %.1fs %s"
                     % (completed.returncode, elapsed,
                        _summarise(results)))

        code = completed.returncode
        if code != EX_OK and code not in allow_codes:
            message = results.get("error") or (
                stderr.strip().splitlines() or ["no diagnostic"])[-1]
            raise exception_for(code)(message, stage=name, code=code,
                                      results=results, stderr=stderr)
        return code, results, stderr

    # -- 1. launch ----------------------------------------------------------
    def open_browser(self, start_url=None, expect_host=None):
        """Start OUR Firefox fullscreen on Indeed and verify it got there."""
        os.makedirs(self.config.temp_dir, exist_ok=True)
        os.makedirs(self.config.profile_dir, exist_ok=True)

        url = start_url or self.config.base_url
        host = expect_host
        if host is None:
            host = _host_of(url)

        _, results, _ = self.run_script("open_firefox.sh", [
            "--profile", self.config.profile_dir,
            "--url", url,
            "--state-file", self.config.window_state_file,
            "--expect-host", host,
            "--download-dir", self.config.temp_dir,
            "--window-size", "%dx%d" % self.config.window_size,
            "--window-pos", "%d,%d" % self.config.window_pos,
        ], timeout=max(self.config.script_timeout, 180))

        self.firefox_pid = results.get("firefox_pid")
        self.listing_window = results.get("window_id")
        if not self.firefox_pid or not self.listing_window:
            raise BrowserLaunchFailed(
                "open_firefox.sh exited 0 but reported no pid/window id",
                stage="open_firefox.sh", results=results)
        self.log("   browser ready: pid=%s window=%s fullscreen=%s"
                 % (self.firefox_pid, self.listing_window,
                    results.get("fullscreen")))
        return results

    def browser_is_alive(self):
        if not self.listing_window:
            return False
        try:
            subprocess.run(["xdotool", "getwindowgeometry",
                            str(self.listing_window)],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           env=self.config.environment(), timeout=10,
                           check=True)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                OSError):
            return False

    # -- 2. search ----------------------------------------------------------
    def search(self, keyword, city, start=0, listing_file=None):
        """One keyword+city search.  Both values come from Python.

        NO LISTING-PAGE COPY.  This used to pass --temp-file so the shell
        would Ctrl+A/Ctrl+C the whole results page into listing_data.txt and
        fail the search when the clipboard did not change.  That check is
        gone: readiness is now proved from the url and the window title.
        ``listing_file`` is accepted and ignored so older callers do not
        break.

        Returns the shell's RESULT map, which now carries:
            results_ready    yes|no   -- informational only
            preselected_key  the job Indeed auto-selected, if any

        NO POST-SEARCH VERIFICATION.  The shell no longer checks that the
        results url contains this keyword and city, and no longer waits for
        a vjk= before returning.  Job identity is still guaranteed, but
        further down: select_job_card.sh reads the key from the url,
        save_page_source.sh refuses to save a page that does not carry it,
        and indeed_source.py isolates that key out of the saved document.
        """
        args = [
            "--window", self.listing_window,
            "--keyword", keyword,
            "--city", city,
            "--base-url", self.config.base_url,
            "--mode", self.config.search_mode,
            "--what-xy", "%d,%d" % (self.config.what_xy[0], self.config.what_xy[1]),
            "--where-xy", "%d,%d" % (self.config.where_xy[0], self.config.where_xy[1]),
        ]
        if start:
            args += ["--start", str(start)]
        _, results, _ = self.run_script("search_jobs.sh", args)
        self.preselected_key = results.get("preselected_key", "")
        return results

    # -- 3. one job card ----------------------------------------------------
    def select_job_card(self, card_index, seen_keys=(), start_y=None,
                        expect_title="", detail_file=None):
        """Select job card ``card_index`` (0-based) and prove its identity.

        THREE THINGS THIS HANDLES THAT THE FIRST VERSION DID NOT:

          1. Indeed PRE-SELECTS the first job, so card 0 usually needs no
             click at all.  ``preselected_key`` from the search is passed
             through and the shell takes it without clicking.
          2. Card heights vary, so there is no pitch to multiply.  The
             shell probes downward from ``start_y`` and reports the y that
             worked, which this method returns so the caller can learn the
             spacing for the next card.
          3. ``seen_keys`` stops a probe accepting a job already handled.

        Returns a JobWindow whose ``job_key`` is the job's own identity.
        """
        if start_y is None:
            start_y = self.config.first_card_y

        args = [
            "--window", self.listing_window,
            "--index", str(int(card_index)),
            "--card-x", str(self.config.card_x),
            "--start-y", str(int(start_y)),
            "--max-y", str(self.config.card_max_y),
            "--probe-step", str(self.config.card_probe_step),
            "--probe-limit", str(self.config.card_probe_limit),
            "--marker", self.config.card_url_marker,
        ]
        if seen_keys:
            args += ["--seen-keys", ",".join(str(k) for k in seen_keys if k)]
        if card_index == 0 and getattr(self, "preselected_key", ""):
            args += ["--preselected-key", self.preselected_key]

        _, results, _ = self.run_script("select_job_card.sh", args)

        url = results.get("selected_url")
        if not url:
            raise WrongJobWindow(
                "select_job_card.sh exited 0 without a selected url",
                stage="select_job_card.sh", results=results)

        window = JobWindow(self.listing_window, url, False,
                           job_key=results.get("selected_key", ""))
        window.selection_method = results.get("selection_method", "")
        try:
            window.learned_card_y = int(results.get("learned_card_y") or 0)
        except (TypeError, ValueError):
            window.learned_card_y = 0
        return window

    # -- 4. save the job's page source --------------------------------------
    def save_job_source(self, window, card_index=0):
        """Ctrl+U, Ctrl+S -- the job's source into ``Temp_Data/rank_N``.

        Returns the path of the saved file.  The file is Firefox's RENDERED
        view-source document, not raw html; indeed_source.py unwraps it.
        """
        name = "job_%s_%04d.html" % (self.config.rank, int(card_index))
        out_path = os.path.join(self.config.temp_dir, name)

        args = ["--window", self.listing_window, "--out", out_path]
        if window is not None and getattr(window, "url", ""):
            # Hard identity check: the page in the window must still be the
            # job we selected.  If it drifted, nothing is saved.
            args += ["--expect-url",
                     _identity_fragment(window.url, self.config.card_url_marker)]

        _, results, _ = self.run_script(
            "save_page_source.sh", args,
            timeout=max(self.config.script_timeout, 120))

        saved = results.get("saved_file")
        if not saved or not os.path.isfile(saved) or os.path.getsize(saved) == 0:
            raise NavigationFailed(
                "save_page_source.sh exited 0 but %s is missing or empty"
                % saved, stage="save_page_source.sh", results=results)

        self.log("   saved source: %s (%s bytes)"
                 % (saved, results.get("saved_bytes", "?")))
        return saved

    # -- 5. close the source tab, with BOTH mandated delays -----------------
    def close_source_tab(self, pre_delay=None, post_delay=None,
                         expect_listing=""):
        """Close the view-source tab, sleeping before and after.

        THE ORDER IS THE REQUIREMENT, not an implementation detail:

            ... caller has processed the job and written it to Excel ...
            sleep pre_close_delay_seconds     (default 10)   <- FIRST delay
            close the source tab
            sleep post_close_delay_seconds    (default 10)   <- SECOND delay
            ... caller selects the next job card ...

        So the first delay belongs to the job just finished and the second
        belongs to the page settling before the next selection.  Callers
        must not sleep again around this method.
        """
        pre = self.config.pre_close_delay_seconds if pre_delay is None \
            else pre_delay
        post = self.config.post_close_delay_seconds if post_delay is None \
            else post_delay

        if pre:
            self.log("   waiting %.1fs before closing the source tab" % pre)
            time.sleep(pre)

        args = ["--window", self.listing_window]
        if expect_listing:
            args += ["--expect-listing", expect_listing]
        _, results, _ = self.run_script("close_source_tab.sh", args)

        if post:
            self.log("   waiting %.1fs before the next job card" % post)
            time.sleep(post)
        return results

    def force_close_source_tab(self):
        """Best-effort cleanup with no delays -- for error paths only."""
        try:
            return self.close_source_tab(pre_delay=0, post_delay=0)
        except BrowserError as error:
            self.log("   could not close the source tab: %s" % error)
            return {}

    # -- 6. scrolling / pagination -----------------------------------------
    def scroll_listing(self, steps=6, out_text=None):
        out_text = out_text or os.path.join(self.config.temp_dir,
                                            "listing_scrolled.txt")
        _, results, _ = self.run_script("scroll_jobs.sh", [
            "--window", self.listing_window,
            "--steps", str(int(steps)),
            "--target", "list",
            "--out-text", out_text,
        ])
        return results

    # -- shutdown -----------------------------------------------------------
    def close_browser(self):
        """Close OUR Firefox, and only ours."""
        if not self.firefox_pid:
            return False
        try:
            subprocess.run(["kill", str(self.firefox_pid)],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
            self.log("   closed our Firefox (pid %s)" % self.firefox_pid)
            return True
        except (OSError, subprocess.TimeoutExpired) as error:
            self.log("   [WARN] could not close Firefox pid %s: %s"
                     % (self.firefox_pid, error))
            return False

    def kill_browser(self):
        """Immediate, for a Ctrl+C path that must not wait for anything."""
        if not self.firefox_pid:
            return False
        try:
            subprocess.run(["kill", "-9", str(self.firefox_pid)],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False


# ---------------------------------------------------------------------------
# PARSING THE PROTOCOL
# ---------------------------------------------------------------------------

RESULT_PREFIX = "RESULT:"


def parse_results(stdout):
    """``RESULT:key=value`` lines -> dict.  Everything else is ignored.

    A value may itself contain "=" (urls do), so only the FIRST "=" splits.
    """
    results = {}
    for line in str(stdout or "").splitlines():
        line = line.strip()
        if not line.startswith(RESULT_PREFIX):
            continue
        body = line[len(RESULT_PREFIX):]
        if "=" not in body:
            continue
        key, value = body.split("=", 1)
        results[key.strip()] = value.strip()
    return results


CAPTURE_HEADER = "#NEW_INDEED_CAPTURE_V1"
CAPTURE_BODY_MARKER = "#---BEGIN PAGE TEXT---"


def read_capture(path):
    """Read a capture file written with CAPTURE_BODY_MARKER, header stripped.

    RETAINED, NOT DEAD.  The Ctrl+U/Ctrl+S workflow does not use this --
    job fields now come from the saved page SOURCE via indeed_source.py --
    but select_job_card.sh's optional --temp-file still writes the detail
    pane's visible text through this format, which is useful when a saved
    source turns out not to contain a field and you need to see what the
    page actually displayed.

    The header is a guarantee, not decoration: a file without it was not
    written by this run's capture step, so it is refused rather than parsed.
    That is what stops a stale file in ``Temp_Data`` being treated as newly
    extracted data (brief section 14).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    except OSError:
        return ""
    if not raw.startswith(CAPTURE_HEADER):
        return ""
    marker = raw.find(CAPTURE_BODY_MARKER)
    if marker < 0:
        return ""
    return raw[marker + len(CAPTURE_BODY_MARKER):].lstrip("\n")


def capture_metadata(path):
    """The ``#key=value`` header of a capture file, as a dict."""
    meta = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith(CAPTURE_BODY_MARKER):
                    break
                if line.startswith("#") and "=" in line:
                    key, value = line[1:].split("=", 1)
                    meta[key.strip()] = value.strip()
    except OSError:
        pass
    return meta


def _identity_fragment(url, marker="vjk="):
    """The part of a job url that identifies the job, for --expect-url.

    The whole url is not used: Indeed rewrites query parameters (tracking
    ids, paging state) as you move around a results page, so matching the
    full string would reject the RIGHT job. The job key is the stable part;
    with no key, host+path still beats nothing.
    """
    url = str(url or "")
    if marker and marker in url:
        key = url.split(marker, 1)[1].split("&", 1)[0]
        if key:
            return marker + key
    return url.split("?", 1)[0]

def _host_of(url):
    text = str(url or "")
    if "://" in text:
        text = text.split("://", 1)[1]
    return text.split("/", 1)[0]


def _summarise(results):
    """The few keys worth putting on the one-line script summary."""
    interesting = ("window_id", "job_window_id", "fullscreen", "identity",
                   "chars", "closed", "listing_fullscreen", "card_markers",
                   "access_denied", "verified")
    parts = ["%s=%s" % (key, results[key])
             for key in interesting if key in results]
    return "(%s)" % " ".join(parts) if parts else ""
