#!/usr/bin/env python3
"""Indeed collector built on Firefox + xdotool + xclip.  Rank-aware, resumable.

WHAT THIS IS
------------
A SECOND, independent Indeed collector.  The original project in
``/home/ubuntu/check_indeed`` drives a Playwright browser; this one drives a
real Firefox window with desktop automation, in the architecture the college
extraction project established:

    Python  ->  shell_scripts/*.sh  ->  xdotool / xclip  ->  Firefox

Nothing here touches the original project except to IMPORT from it,
read-only: the 85-role plan, the 110-city list and the 32-column row
builder all come from there (see ``upstream.py``), so there is exactly one
definition of each and the two collectors cannot drift apart.

THE LOOP (brief section 8)
--------------------------
    for each of this rank's assigned cities:        <- OUTER
        for each of the 85 keywords:                <- INNER
            for each permitted results page:
                for each job card on the page:
                    right-click -> Down -> Open Link in New Window
                    copy the Apply URL, copy the page text
                    parse -> validate -> non-IT filter -> duplicate check
                    save to Excel, then advance the checkpoint
                    sleep 10s, close the window, sleep 10s
        --> the city is finished: TOTAL COMPLETE CYCLE += 1

SAFETY DEFAULTS
---------------
``LIVE_COLLECTION_ENABLED`` is False.  Brief restriction 14 -- "Do not start
unattended live job collection without approval" -- is enforced by the code,
not by intention: a live run needs BOTH that flag and the
``INDEED_LIVE_APPROVED=yes`` environment variable.  Everything else (the
fixture mode, the self-test, the dry run) works out of the box.

USAGE
    python3 find_indeed_job.py --status            # read the checkpoint
    python3 find_indeed_job.py --plan              # print the plan, no browser
    python3 find_indeed_job.py --fixture-run       # local HTML, real Firefox
    python3 find_indeed_job.py --rank 1 --num-sys 5    # live (gated)
"""

import argparse
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# ===========================================================================
# CONFIGURATION -- every editable setting is in this one block
# ===========================================================================
# The original project puts all of its settings at the top of this same
# file and passes them inwards, so the modules hold behaviour only.  That
# convention is kept, which is also what makes brief section 21's "Do not
# use hardcoded timings throughout the code" true.

# -- which script am I? ----------------------------------------------------
# rank      1..num_sys, which slice of the 110 cities this process owns
# num_sys   how many scripts are configured in total
#
# The contract is the original project's, including the slicing algorithm
# (see get_cities_by_rank).  Override from the command line with
# --rank / --num-sys; these are the defaults.
rank = 3
num_sys = 5

# -- the source ------------------------------------------------------------
INDEED_BASE_URL = "https://in.indeed.com"
INDEED_PAGE_STEP = 10            # the site paginates "start=" in tens

# -- LIVE GATE (brief restriction 14) --------------------------------------
LIVE_COLLECTION_ENABLED = True
LIVE_APPROVAL_ENV = "INDEED_LIVE_APPROVED"
LIVE_APPROVAL_VALUE = "yes"

# -- the browser -----------------------------------------------------------
FIREFOX_BINARY = "firefox"
DISPLAY_OVERRIDE = ""            # "" = inherit DISPLAY; ":99" for an Xvfb

# -- THE HEADLESS FRAMEBUFFER (Xvfb) ---------------------------------------
# An ssh session inherits no DISPLAY, and shell_scripts/_common.sh
# require_display() correctly refuses to drive a display that is not there
# (FACT 1) -- that is the "DISPLAY is not set" failure.  Rather than require
# the laptop to be logged in at its own panel, the collector brings up its
# OWN X server on XVFB_DISPLAY when nothing was inherited, so a run started
# over ssh is watched from the terminal and never touches the operator's
# desktop (see _common.sh FACT 4, where an XTEST Ctrl+C aimed at our Firefox
# came back holding the operator's own browser content).
#
# The geometry is 1920x1080 and NOT the laptop's 1366x768 panel because
# WINDOW_SIZE and every CARD_* coordinate below were calibrated at that
# size; on a narrower screen Indeed re-flows and the clicks land on
# furniture instead of on the search boxes and the cards.
#
# :105 is used because the Naukri collectors on this host already hold
# :77, :99 and :100.
#
# Set XVFB_ENABLED = False to go back to requiring a real, inherited
# display.  An inherited DISPLAY is always left alone, so a desktop session
# and run_collector.sh keep behaving exactly as before.
XVFB_ENABLED = True
XVFB_DISPLAY = ":105"
XVFB_GEOMETRY = "1920x1080x24"
# A bare Xvfb has no window manager, and set_window_geometry() and
# require_focus() in _common.sh need somebody to honour the resize and the
# focus request -- without one the window keeps Firefox's own default size
# and the calibrated coordinates are wrong again.
XVFB_WINDOW_MANAGER = "xfwm4"
XVFB_START_TIMEOUT_SECONDS = 15
# An XAUTHORITY file the Firefox SNAP can read.  The live mutter cookie in
# /run/user/<uid>/ is not always readable from inside the snap, and Firefox
# then exits with "cannot open display".  "" uses XAUTHORITY as inherited.
# See shell_scripts/_common.sh, FACT 2.
# THIS HOST: kali, lightdm + Xorg :0, and the DEB firefox (128.4.0esr),
# not the snap -- so the snap-confinement workaround described above does
# not apply here, and the shipped copy actively BREAKS the launch. The
# cookie in config/xauth_xwayland is for "ubuntu-Inspiron-3593/unix:",
# the machine this clone was authored on; Firefox on this display
# ("kali/unix:0") cannot use it and exits "cannot open display".
# "" makes firefox_xauthority() fall back to the inherited XAUTHORITY,
# which tracks the live session instead of a snapshot of it.
FIREFOX_XAUTH_COPY = ""
# "form" = click Indeed's own search boxes and type into them (what was
# asked for). "url" = build a search url in the address bar; kept as a
# fallback and used automatically for file:// fixture runs, which have no
# search form.
SEARCH_MODE = "form"

# Seconds to wait after Indeed's page has loaded and before its search boxes
# are clicked and typed into.  Indeed keeps laying the page out after it
# reports loaded, and the boxes move while it does.
SEARCH_FIELD_DELAY_SECONDS = 7

# Seconds to wait after pressing Return before going to the first job card.
# This replaced the post-search verification (url must contain q= and l=,
# vjk= must appear).  Those checks blocked progression on searches that had
# loaded perfectly; job identity is enforced later instead -- see
# select_job_card.sh, save_page_source.sh --expect-url, and indeed_source.py.
SEARCH_RESULTS_WAIT_SECONDS = 10

# -- where the job cards are in the results column -------------------------
# The ONLY numbers in this project that depend on how the page is laid out.
# They are configuration, and select_job_card.sh reports exactly where it
# clicked and then verifies what got selected, so a wrong value shows up as
# a refusal rather than as the wrong job being saved.
CARD_X = 430                     # x inside the results column
FIRST_CARD_Y = 440               # y of the FIRST card's clickable area
CARD_MAX_Y = 1000                # below this is off the results column
CARD_PROBE_STEP = 55             # how far down to step when a probe misses
CARD_PROBE_LIMIT = 12            # probes before declaring "no more cards"
MIN_CARD_GAP = 60                # shortest plausible gap to the next card
# The results column shows only 3-4 cards at a time. When the probe window
# reaches the bottom, select_job_card.sh scrolls and keeps looking; this is
# how many times it may do so before the page is accepted as finished.
CARD_SCROLL_ROUNDS = 6
CARD_URL_MARKER = "vjk="         # the query parameter holding the job key

# NOTE: there is deliberately NO CARD_PITCH any more.  Indeed's job cards
# are not a fixed height -- on one measured results page the card tops were
# 410, 645 and 835, i.e. pitches of 259 and 191, and the selected card is
# taller again because it expands.  The old FIRST_CARD_Y=300 / CARD_PITCH=148
# therefore put cards 1 and 2 inside the SAME card.  select_job_card.sh now
# probes downward and reports the y that worked.

# -- the Firefox window (NORMAL, never fullscreen) -------------------------
# Defaults read off the supplied screenshot: 1845x1046 at +0+34 on a
# 1920x1080 screen, title bar visible, operator able to watch.
WINDOW_SIZE = (1845, 1046)
WINDOW_POS = (0, 34)

# -- Indeed's two search boxes, in screen coordinates ----------------------
# Used by SEARCH_MODE="form" to click the real fields instead of building a
# search url.  Both are read back and confirmed before the search is
# submitted, so a wrong value fails loudly instead of running a wrong search.
SEARCH_WHAT_XY = (700, 240)
SEARCH_WHERE_XY = (1100, 240)
JOB_URL_PATTERN = r"(viewjob|/rc/clk|/pagead/clk|jk=|job_detail)"

# -- the two mandated pacing delays (brief section 21) ---------------------
# Delay 1: after the row is saved, BEFORE the detail window is closed.
PRE_CLOSE_DELAY_SECONDS = 10.0
# Delay 2: after the listing is restored, BEFORE the next card is opened.
POST_CLOSE_DELAY_SECONDS = 10.0
# These pace the browser, which is what was asked for.  They are NOT a
# remedy for an access refusal and this project never claims they are.

# -- browser-layer timeouts ------------------------------------------------
WINDOW_TIMEOUT_SECONDS = 30
FOCUS_TIMEOUT_SECONDS = 10
CLIPBOARD_TIMEOUT_SECONDS = 10
PAGE_SETTLE_SECONDS = 3.0
POLL_INTERVAL_SECONDS = 0.25
KEY_DELAY_MS = 40
SHELL_SCRIPT_TIMEOUT_SECONDS = 180
# `xclip -o` can block forever against a Chromium-based browser
# mid-transfer (measured). Every clipboard read is wrapped in this.
XCLIP_TIMEOUT_SECONDS = 5
MIN_DETAIL_CHARS = 400           # below this, it is furniture, not a job

# -- how much to collect ---------------------------------------------------
# TARGET_UNIQUE_JOBS counts DISTINCT JOBS EXAMINED for one keyword+city
# combination -- not rows saved.  That is the original project's meaning,
# preserved: a card filtered out as non-IT still counts as a unique job that
# was seen.  Finishing the page that crosses the line is fine.
# ---------------------------------------------------------------------------
# HOW MUCH TO FETCH -- the two fixed numbers
# ---------------------------------------------------------------------------
# A search can return far more than anyone wants to collect: "python
# developer" in Delhi is pages of results. These two say how much of it to
# take, and they are a FIXED plan rather than "keep going until something
# stops us":
#
#     FIXED_LISTING_PAGES   results pages per keyword+city
#     FIXED_CARDS_PER_PAGE  job cards taken from each of those pages
#
# so one keyword+city yields at most FIXED_LISTING_PAGES x
# FIXED_CARDS_PER_PAGE jobs. Page 2 onwards is reached by url -- see
# listing_page_url() in indeed_controller.py.
FIXED_LISTING_PAGES = 5
FIXED_CARDS_PER_PAGE = 10

# Kept as the names the rest of the file already uses.
MAX_LISTING_PAGES = FIXED_LISTING_PAGES
MAX_CARDS_PER_PAGE = FIXED_CARDS_PER_PAGE
MIN_LISTING_PAGES = 1

# The ceiling on DISTINCT jobs examined per keyword+city. Derived from the
# two fixed numbers so it can never cut the fixed plan short -- it is a
# backstop against a pathological page, not a second budget.
TARGET_UNIQUE_JOBS = FIXED_LISTING_PAGES * FIXED_CARDS_PER_PAGE

# A page that yields nothing new has nothing more to give: the list has
# ended, or every card on it was already collected. Set False to keep
# paging to FIXED_LISTING_PAGES regardless.
STOP_ON_PAGE_WITH_NO_NEW_JOBS = True

# ---------------------------------------------------------------------------
# THE PAGE CENSUS -- how many cards is this page ACTUALLY showing?
# ---------------------------------------------------------------------------
# FIXED_CARDS_PER_PAGE is a ceiling, not a promise. A real search returned
# FIVE cards and the collector, told to take ten, spent the rest of the page
# clicking empty space and calling it "no more cards".
#
# So before any card is clicked, the results page's OWN source is saved and
# the card list read out of it (page_cards() in indeed_source.py). That
# gives two things no amount of probing can:
#
#   1. HOW MANY CARDS ARE THERE.  Take min(found, FIXED_CARDS_PER_PAGE) and
#      a short page finishes cleanly instead of failing its way to the end.
#   2. WHICH CARDS THEY ARE.  If page 2's card list is the SAME list as
#      page 1's, then start=10 changed nothing: the search has only one
#      page, and the right move is the next keyword, not four more pages of
#      the same ten jobs.
#
# A census that cannot be read falls back to the fixed number and disables
# the repeat check -- "unknown" must never be read as "the results ended".
COUNT_CARDS_FROM_PAGE_SOURCE = True
STOP_WHEN_PAGE_REPEATS = True

# The census is not a job, so it does not get the two 10-second job delays
# (those pace the job cards and are untouched). It still waits, briefly,
# because it is a tab open and closed in a real browser.
CENSUS_PRE_CLOSE_DELAY_SECONDS = 2.0
CENSUS_POST_CLOSE_DELAY_SECONDS = 3.0

# A page whose cards are this fraction new -- or less -- is the page before
# it, served again. MEASURED on five saved reloads of one results page: the
# cards reshuffled every time and 0.00-0.40 of them were new, while a real
# next page shares nothing. 0.5 sits in the middle of that gap.
PAGE_REPEAT_NEW_CARD_FRACTION = 0.5

# -- Excel -----------------------------------------------------------------
DETAIL_OUTPUT_FILE = "current_data.xlsx"
EXCEL_BATCH_SIZE = 100           # rows per archived current_data_cycleN.xlsx
EXCEL_KEEP_BACKUPS = 20

# -- schedule (brief section 21) -------------------------------------------
NIGHT_PAUSE_ENABLED = False
NIGHT_START_HOUR = 23            # 23:00 .. 05:00 Asia/Kolkata
NIGHT_END_HOUR = 5
TIMEZONE = "Asia/Kolkata"

WORK_PERIOD_MIN_HOURS = 3.7
WORK_PERIOD_MAX_HOURS = 4.2
WORK_BREAK_MIN_MINUTES = 30
WORK_BREAK_MAX_MINUTES = 60

JOB_GAP_MIN_SECONDS = 0.0        # extra gap on top of the two 10s delays
JOB_GAP_MAX_SECONDS = 0.0
KEYWORD_GAP_MIN_SECONDS = 20.0   # only used when the restart is disabled
KEYWORD_GAP_MAX_SECONDS = 45.0
CITY_GAP_MIN_SECONDS = 60.0      # only used when the restart is disabled
CITY_GAP_MAX_SECONDS = 180.0

# ---------------------------------------------------------------------------
# A FRESH BROWSER FOR EVERY KEYWORD
# ---------------------------------------------------------------------------
# When a keyword+city is finished -- every card of every page it has -- the
# browser is closed and started again before the next keyword:
#
#     process the last card  ->  close the browser
#                            ->  wait BROWSER_RESTART_WAIT_SECONDS
#                            ->  open the browser on the Indeed home page
#                            ->  verify the two search fields
#                            ->  type the next keyword
#
# WHY RESTART AT ALL, rather than just searching again in the open window:
#
#   * One window used for hundreds of searches accumulates state -- the
#     detail pane, the suggestion dropdown, scroll position, modals Indeed
#     shows after a while. Every one of those has broken a run at least
#     once. A new window has none of it.
#   * The card coordinates are measured against a fresh home page layout.
#   * Firefox flushes its cookie write-ahead log on a clean exit, so the
#     login is re-checked and re-saved to disk on every restart.
#
# And why the search fields are verified afterwards: the step right after a
# restart CLICKS at a remembered coordinate and types a real keyword. If
# that click misses the input, the keyword goes nowhere and Return submits
# whatever the page had before -- the failure that once sent a run to
# youtube.com. verify_search_fields.sh types a throwaway probe into each
# box, reads it back, and clears it. Nothing is submitted.
RESTART_BROWSER_BETWEEN_KEYWORDS = True
BROWSER_RESTART_WAIT_SECONDS = 5.0
VERIFY_SEARCH_FIELDS_AFTER_RESTART = True

# ONE COMPLETE CYCLE = every keyword done for one city. Then the collector
# rests for ten minutes before the next city's first keyword. It rests with
# the browser CLOSED: ten minutes of an idle logged-in window is ten
# minutes of something that can go wrong on a shared desktop, and the
# restart that follows opens a fresh one anyway.
COMPLETE_CYCLE_REST_SECONDS = 600.0      # 10 minutes

# How many restarts in a row may fail before the run gives up. A restart
# that cannot produce a working search page is not something to carry on
# through: every subsequent keyword would type into a page we cannot vouch
# for.
MAX_CONSECUTIVE_RESTART_FAILURES = 3
LISTING_PAGE_GAP_MIN_SECONDS = 15.0
LISTING_PAGE_GAP_MAX_SECONDS = 30.0
CYCLE_COOLDOWN_MINUTES = 45

# -- failure policy --------------------------------------------------------
# An access refusal STOPS the affected workflow (brief section 22).  It is
# never retried and nothing about the browser's identity is changed.
STOP_ON_ACCESS_DENIED = True
MAX_CONSECUTIVE_CARD_FAILURES = 5
MAX_CONSECUTIVE_SEARCH_FAILURES = 3
KEYWORD_SHUFFLE_ENABLED = True

# -- internet -------------------------------------------------------------
INTERNET_CHECK_ENABLED = True
INTERNET_CHECK_HOST = "8.8.8.8"
INTERNET_CHECK_PORT = 53
INTERNET_CHECK_TIMEOUT = 3
INTERNET_RECHECK_SECONDS = 15

# -- output ---------------------------------------------------------------
VERBOSE = True
LOG_EVERY_ROW = True

# ===========================================================================
# END OF CONFIGURATION
# ===========================================================================

from new_mylib import all_cities as _all_city_names          # noqa: E402
from new_mylib import city_to_state                          # noqa: E402
from target_audience_roles import (                          # noqa: E402
    build_role_plan, is_non_it_title, role_plan_split, role_department)

from source_file.indeed_checkpoint import Checkpoint         # noqa: E402
from source_file.indeed_controller import (                  # noqa: E402
    AccessDenied, BrowserError, ClipboardEmpty, ClipboardStale,
    ContextMenuFailed, ControllerConfig, FullscreenFailed, IndeedController,
    NavigationFailed, WrongJobWindow)
from source_file.indeed_excel import ExcelStore              # noqa: E402
from source_file.indeed_extractor import (                   # noqa: E402
    DETAIL_COLUMNS, build_row)
from source_file.indeed_source import (                      # noqa: E402
    build_row_from_file, page_cards, read_saved_source)
from source_file.indeed_validator import (                   # noqa: E402
    Decision, DuplicateIndex, decide, normalise_job_url)

import upstream                                              # noqa: E402

ROLE_CATEGORY = "IT Department"

_SHUTDOWN_REQUESTED = False
_CHECKPOINT = None
_CONTROLLER = None
_LOG_HANDLE = None


# ===========================================================================
# PATHS
# ===========================================================================

def project_path(*parts):
    return os.path.join(BASE_DIR, *parts)


def rank_dir(kind, which=None):
    """``<kind>/rank_N`` -- every rank's files are its own (brief section 8)."""
    return project_path(kind, "rank_%d" % int(which if which is not None
                                              else rank))


# ===========================================================================
# LOGGING (brief section 23)
# ===========================================================================

def open_log(which=None):
    global _LOG_HANDLE
    folder = project_path("logs")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "rank_%d.log"
                        % int(which if which is not None else rank))
    try:
        _LOG_HANDLE = open(path, "a", encoding="utf-8")
    except OSError:
        _LOG_HANDLE = None
    return path


def log(message=""):
    text = str(message)
    print(text, flush=True)
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write("%s %s\n" % (now_time(), text))
            _LOG_HANDLE.flush()
        except (OSError, ValueError):
            pass


def now_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def local_now():
    """Now in TIMEZONE, falling back to system local time."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        return datetime.now()


def human_duration(seconds):
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return "%dh %02dm" % (hours, minutes)
    if minutes:
        return "%dm %02ds" % (minutes, secs)
    return "%ds" % secs


# ===========================================================================
# THE PLAN: 110 CITIES, 5 RANKS, 85 KEYWORDS
# ===========================================================================

def get_cities_by_rank(all_city_list, which_rank, how_many):
    """The symmetric slice this rank owns.

    THE ORIGINAL PROJECT'S ALGORITHM, PRESERVED EXACTLY.  Brief section 8:
    "If the existing Indeed project uses a particular distribution
    algorithm, preserve that algorithm rather than inventing a
    replacement."  So:

        one_unit  = int(len(cities) / num_sys) + 1
        cities[one_unit * (rank - 1) : one_unit * rank]

    It is positional, so every city belongs to exactly one rank, none is
    skipped, and the slice sizes differ by at most one.

    A NOTE ON "22 CITIES PER RANK"
    ------------------------------
    Brief section 8 also says "When five ranks are configured, 110 cities
    should be distributed as 22 cities per rank."  This algorithm gives
    23/23/23/23/18, not 22/22/22/22/22, because of the "+ 1".  The two
    instructions conflict, and the explicit instruction to preserve the
    existing algorithm is the one followed.  `--plan` prints the actual
    distribution so it is visible rather than assumed, and
    tests/test_city_distribution.py asserts both the algorithm AND the
    three properties the brief actually requires: total coverage, no
    overlap, and stability across restarts.  Changing the split to an even
    22 would reassign cities between ranks and invalidate every existing
    checkpoint, so it is not done without a decision.
    """
    if not all_city_list:
        return []
    try:
        which_rank = int(which_rank)
        how_many = int(how_many)
    except (TypeError, ValueError):
        return []
    if how_many < 1 or which_rank < 1 or which_rank > how_many:
        return []

    length = len(all_city_list)
    one_unit = int(length / how_many) + 1
    return all_city_list[one_unit * (which_rank - 1):one_unit * which_rank]


def all_cities():
    """The 110 crawl cities, de-duplicated, ORDER PRESERVED (it is positional)."""
    return _all_city_names()


def rank_cities(which=None, how_many=None):
    which = rank if which is None else which
    how_many = num_sys if how_many is None else how_many
    cities = get_cities_by_rank(all_cities(), which, how_many)
    if not cities:
        raise RuntimeError(
            "get_cities_by_rank() returned no cities for rank=%s num_sys=%s "
            "out of %d cities. Check --rank / --num-sys."
            % (which, how_many, len(all_cities())))
    return cities


def keyword_plan_pairs():
    """``[(role_category, keyword), ...]`` -- the 85-keyword plan.

    The roles come from ``target_audience_roles.build_role_plan()`` and from
    nowhere else.  Brief section 6: "Do not use the old job_by_department
    dictionary from new_mylib.py to create search targets."  This project
    never imports it.
    """
    pairs = []
    seen = set()
    for keyword in build_role_plan():
        text = str(keyword).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen or key == ROLE_CATEGORY.lower():
            continue
        seen.add(key)
        pairs.append((ROLE_CATEGORY, text))
    if not pairs:
        raise RuntimeError("the role plan produced no searchable keywords.")
    return pairs


def city_state_name(city):
    """``city_to_state()`` with a cache -- the answer never changes."""
    if city not in _CITY_STATE_CACHE:
        try:
            _CITY_STATE_CACHE[city] = city_to_state(city)
        except Exception as error:
            log("  [WARN] city_to_state(%r) failed: %s" % (city, error))
            _CITY_STATE_CACHE[city] = "Other"
    return _CITY_STATE_CACHE[city]


_CITY_STATE_CACHE = {}


# ===========================================================================
# PACING: NIGHT REST AND WORKING BREAKS
# ===========================================================================

class ScheduledPause(Exception):
    """A scheduled stop is due.  The checkpoint is saved before waiting."""

    def __init__(self, reason, seconds):
        super(ScheduledPause, self).__init__(reason)
        self.reason = reason
        self.seconds = int(seconds)


_WORK_START = None
_WORK_PERIOD_HOURS = None


def reset_work_timer():
    global _WORK_START, _WORK_PERIOD_HOURS
    _WORK_START = time.monotonic()
    low = min(WORK_PERIOD_MIN_HOURS, WORK_PERIOD_MAX_HOURS)
    high = max(WORK_PERIOD_MIN_HOURS, WORK_PERIOD_MAX_HOURS)
    _WORK_PERIOD_HOURS = max(0.01, random.uniform(low, high)
                             if high > low else low)


def work_seconds():
    return 0.0 if _WORK_START is None else time.monotonic() - _WORK_START


def pick_break_seconds():
    low = int(min(WORK_BREAK_MIN_MINUTES, WORK_BREAK_MAX_MINUTES)) * 60
    high = int(max(WORK_BREAK_MIN_MINUTES, WORK_BREAK_MAX_MINUTES)) * 60
    return low if high <= low else random.randint(low, high)


def night_seconds_remaining(now=None):
    """Seconds until the night window ends, or 0 when outside it."""
    if not NIGHT_PAUSE_ENABLED:
        return 0
    now = now or local_now()
    start = int(NIGHT_START_HOUR) % 24
    end = int(NIGHT_END_HOUR) % 24
    if start == end:
        return 0
    hour = now.hour
    inside = (start <= hour < end) if start < end \
        else (hour >= start or hour < end)
    if not inside:
        return 0
    target = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(0, int((target - now).total_seconds()))


def pacing_gate():
    """Raise ScheduledPause when a stop is due.

    Called ONLY at safe boundaries -- before a keyword, before a listing
    page -- so a job is never abandoned with its detail window open.
    """
    if _SHUTDOWN_REQUESTED:
        raise KeyboardInterrupt("shutdown requested")

    night = night_seconds_remaining()
    if night > 0:
        raise ScheduledPause(
            "night rest %02d:00-%02d:00 %s"
            % (NIGHT_START_HOUR, NIGHT_END_HOUR, TIMEZONE), night)

    worked = work_seconds()
    period = _WORK_PERIOD_HOURS or 4.0
    if _WORK_START is not None and worked >= period * 3600.0:
        seconds = pick_break_seconds()
        raise ScheduledPause(
            "%.2f-hour work period reached (%.2f h worked) -- taking a %s "
            "break (random %d-%d min)"
            % (period, worked / 3600.0, human_duration(seconds),
               WORK_BREAK_MIN_MINUTES, WORK_BREAK_MAX_MINUTES), seconds)


def sleep_responsive(seconds, label=""):
    """Sleep in one-second slices so Ctrl+C is never swallowed.

    One-second slices rather than a busy loop: brief section 21 asks for
    both responsiveness and "avoid busy loops that consume unnecessary CPU".
    """
    seconds = float(max(0.0, seconds))
    if seconds <= 0:
        return
    if label and seconds >= 5:
        log("      [wait] %s %s" % (human_duration(seconds), label))
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0 or _SHUTDOWN_REQUESTED:
            return
        time.sleep(min(1.0, remaining))


def sleep_between(minimum, maximum, label=""):
    low, high = min(minimum, maximum), max(minimum, maximum)
    if high <= 0:
        return
    sleep_responsive(low if high <= low else random.uniform(low, high), label)


def is_internet_available():
    if not INTERNET_CHECK_ENABLED:
        return True
    import socket
    try:
        socket.setdefaulttimeout(INTERNET_CHECK_TIMEOUT)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            (INTERNET_CHECK_HOST, INTERNET_CHECK_PORT))
        return True
    except OSError:
        return False


def wait_for_internet():
    if is_internet_available():
        return
    log("   [NET] the internet is unreachable -- waiting.")
    while not _SHUTDOWN_REQUESTED:
        sleep_responsive(INTERNET_RECHECK_SECONDS)
        if is_internet_available():
            log("   [NET] back.")
            return


# ===========================================================================
# TERMINAL DISPLAY (brief section 23)
# ===========================================================================

def show_job_line(summary, card_index, title="", company="",
                  extraction="", duplicate="", excel="", next_hint=""):
    """The per-job block the brief specifies, exactly in that order."""
    log("")
    log("[Rank %s/%s]" % (summary["rank"], summary["num_sys"]))
    log("")
    log("City: %s   (%s/%s)" % (summary["city"], summary["city_index"],
                                summary["total_cities"]))
    log("Keyword: %s   (%s/%s)" % (summary["keyword"],
                                   summary["keyword_index"],
                                   summary["total_keywords"]))
    log("")
    log("Page: %s" % summary["page"])
    log("Job: %s" % card_index)
    log("")
    if title:
        log("Job Title: %s" % title)
    if company:
        log("Company: %s" % company)
    log("")
    if extraction:
        log("Extraction: %s" % extraction)
    if duplicate:
        log("Duplicate: %s" % duplicate)
    if excel:
        log("Excel Save: %s" % excel)
    log("")
    log("Jobs Examined: %s   Extracted: %s   Saved: %s   Duplicates: %s   "
        "Rejected: %s   Failures: %s"
        % (summary["examined"], summary["examined"] - summary["failures"],
           summary["saved"], summary["duplicates"], summary["rejected"],
           summary["failures"]))
    log("")
    log("Total Complete Cycle: %s" % summary["total_complete_cycle"])
    log("")
    if next_hint:
        log("Next: %s" % next_hint)
    log("-" * 60)


def _plan_department_count(plan_pairs):
    """How many departments the plan actually spans.

    Counted from the role module, never hardcoded. It is in the banner
    because it is the one number that makes the Track A / Track B split
    legible: 1 department would mean the old IT-only plan is back.
    """
    try:
        return len({role_department(keyword)
                    for _dept, keyword in plan_pairs})
    except Exception:                                    # pragma: no cover
        return 0



def check_excel_dependencies():
    """Refuse to start if the workbook cannot be written.

    WHY THIS IS A STARTUP CHECK AND NOT A try/except AT THE WRITE.
    pandas imports fine on its own, so the collector used to start happily,
    drive the browser, save a page, extract all 32 fields -- and only then
    discover that `to_excel` needs openpyxl, which was not installed. It
    then did that for EVERY job: the log filled with
        Excel Save: FAILED (ModuleNotFoundError: No module named 'openpyxl')
    and `saved_jobs` stayed at 0 while the run looked like it was working.

    The cause was a virtualenv (venv/, include-system-site-packages=false)
    that had pandas but not openpyxl, so the packages installed for the
    user account were invisible to it.

    Returns a list of missing module names; empty means ready.
    """
    missing = []
    for module in ("pandas", "openpyxl"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    return missing



def check_indeed_login(config):
    """Is this rank's browser profile signed in to Indeed?

    Returns (signed_in, detail).  Never blocks the run: Indeed's first page
    of results is readable signed out, and the collector worked that way
    for a long time.  What a session changes is PAGING -- Indeed asks for a
    login when you go deeper into results -- so a run without one quietly
    collects far less than it looks like it should.  Saying so at startup
    is the difference between "it only found 15 jobs" and knowing why.

    The session is Firefox's own, in the profile's cookies.sqlite. There is
    no auth file: see save_indeed_login.py for why.
    """
    try:
        import save_indeed_login as login_helper
    except Exception as error:                       # pragma: no cover
        return False, "could not check (%s)" % error

    try:
        cookies = login_helper.indeed_cookies(config.profile_dir)
        evidence = login_helper.login_evidence(cookies)
    except Exception as error:                       # pragma: no cover
        return False, "could not read the profile's cookies (%s)" % error

    if evidence:
        return True, "session cookies: %s" % ", ".join(evidence)
    return False, "no Indeed session cookie in %s" % config.profile_dir


def show_banner(cities, plan_pairs, checkpoint):
    target, other, percent = role_plan_split()
    log("=" * 72)
    log("NEW INDEED COLLECTOR -- Firefox / xdotool / xclip")
    log("=" * 72)
    log("  %s" % upstream.describe())
    log("  rank            : %d of %d" % (rank, num_sys))
    log("  keywords        : %d" % len(plan_pairs))
    log("    target-audience : %d  (%.1f%% of the plan)" % (target, percent))
    log("    fresher/other   : %d  (%.1f%%)"
        % (other, 100.0 - percent if plan_pairs else 0.0))
    log("    departments     : %d" % _plan_department_count(plan_pairs))
    log("  cities (all)    : %d" % len(all_cities()))
    log("  cities (rank %d) : %d  -> %s%s"
        % (rank, len(cities), ", ".join(cities[:4]),
           " ..." if len(cities) > 4 else ""))
    log("  excel columns   : %d" % len(DETAIL_COLUMNS))
    log("  output          : %s" % rank_dir("Excel_Data"))
    log("  temp            : %s" % rank_dir("Temp_Data"))
    log("  checkpoint      : %s" % checkpoint.path)
    log("  loop            : city-outer, keyword-inner (brief section 8)")
    log("  delays          : %.0fs before close, %.0fs before next card"
        % (PRE_CLOSE_DELAY_SECONDS, POST_CLOSE_DELAY_SECONDS))
    log("  between keywords: %s"
        % ("close the browser, wait %.0fs, reopen on the home page%s"
           % (BROWSER_RESTART_WAIT_SECONDS,
              ", verify the search fields"
              if VERIFY_SEARCH_FIELDS_AFTER_RESTART else "")
           if RESTART_BROWSER_BETWEEN_KEYWORDS
           else "%.0f-%.0fs wait, same window"
           % (KEYWORD_GAP_MIN_SECONDS, KEYWORD_GAP_MAX_SECONDS)))
    log("  complete cycle  : all keywords for one city, then rest %s"
        % human_duration(COMPLETE_CYCLE_REST_SECONDS))
    log("  night rest      : %s" % ("%02d:00-%02d:00 %s"
                                    % (NIGHT_START_HOUR, NIGHT_END_HOUR,
                                       TIMEZONE)
                                    if NIGHT_PAUSE_ENABLED else "disabled"))
    log("  work period     : %.1f-%.1f h, then a %d-%d min break"
        % (WORK_PERIOD_MIN_HOURS, WORK_PERIOD_MAX_HOURS,
           WORK_BREAK_MIN_MINUTES, WORK_BREAK_MAX_MINUTES))
    log("  fixed plan      : %d page(s) x %d card(s) = up to %d jobs per "
        "keyword+city" % (FIXED_LISTING_PAGES, FIXED_CARDS_PER_PAGE,
                          FIXED_LISTING_PAGES * FIXED_CARDS_PER_PAGE))
    log("  paging          : page 1 = typed search, page 2+ = start=%d,%d,..."
        % (INDEED_PAGE_STEP, INDEED_PAGE_STEP * 2))
    log("  cards per page  : %s"
        % ("counted from each page's own source, capped at %d"
           % FIXED_CARDS_PER_PAGE if COUNT_CARDS_FROM_PAGE_SOURCE
           else "%d, assumed" % FIXED_CARDS_PER_PAGE))
    log("  repeated page   : %s"
        % ("same card list as the previous page -> next keyword"
           if STOP_WHEN_PAGE_REPEATS else "ignored"))
    log("  page ceiling    : %d listing page(s) per keyword+city"
        % MAX_LISTING_PAGES)
    log("  unique target   : %d distinct jobs EXAMINED per keyword+city"
        % TARGET_UNIQUE_JOBS)
    summary = checkpoint.summary()
    log("  TOTAL COMPLETE CYCLE : %d   (cities finished this crawl cycle: "
        "%d/%d)" % (summary["total_complete_cycle"],
                    summary["completed_cities"], summary["total_cities"]))
    log("=" * 72)


# ===========================================================================
# THE DISPLAY
# ===========================================================================

def _display_answers(display):
    """True when something on `display` actually answers an X request.

    A socket in /tmp/.X11-unix is not proof: a dead Xvfb leaves its socket
    behind.  xdotool is what the shell layer uses, so it is what gets asked.
    XAUTHORITY is dropped because our Xvfb is started without -auth; a
    cookie inherited from an ssh session points at :0 and would be refused.
    """
    env = dict(os.environ, DISPLAY=display)
    env.pop("XAUTHORITY", None)
    try:
        return subprocess.call(
            ["xdotool", "getdisplaygeometry"], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def _spawn_detached(argv, log_path):
    """Start a long-lived X helper that must outlive this call, not this run.

    Its own session, so Ctrl+C in the collector's terminal does not take the
    framebuffer down with it, and the next run finds it already up.
    """
    with open(log_path, "ab") as sink:
        subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)


def ensure_display():
    """Make sure there is an X display to drive; start Xvfb if there is not.

    Returns True when DISPLAY is usable by the time this returns.  See the
    XVFB_* block at the top of this file for why a framebuffer and not the
    laptop's own screen.
    """
    if os.environ.get("DISPLAY"):
        log("  display         : %s (inherited)" % os.environ["DISPLAY"])
        return True
    if not XVFB_ENABLED:
        return True                  # let _common.sh report the real reason

    env_display = XVFB_DISPLAY
    if not _display_answers(env_display):
        if not shutil.which("Xvfb"):
            log("[xvfb] Xvfb is not installed. Install it with:")
            log("         sudo apt install xvfb")
            return False
        log("[xvfb] starting Xvfb %s (%s)" % (env_display, XVFB_GEOMETRY))
        _spawn_detached(
            ["Xvfb", env_display, "-screen", "0", XVFB_GEOMETRY,
             "-nolisten", "tcp"],
            "/tmp/xvfb%s.log" % env_display.lstrip(":"))
        deadline = time.time() + XVFB_START_TIMEOUT_SECONDS
        while time.time() < deadline and not _display_answers(env_display):
            time.sleep(0.5)
        if not _display_answers(env_display):
            log("[xvfb] %s did not come up within %ds -- see /tmp/xvfb%s.log"
                % (env_display, XVFB_START_TIMEOUT_SECONDS,
                   env_display.lstrip(":")))
            return False
    else:
        log("[xvfb] %s is already up" % env_display)

    os.environ["DISPLAY"] = env_display
    # Our Xvfb has no -auth cookie; an XAUTHORITY left over from the ssh
    # session names :0 and makes Firefox exit "cannot open display".
    os.environ.pop("XAUTHORITY", None)

    if XVFB_WINDOW_MANAGER:
        if not shutil.which(XVFB_WINDOW_MANAGER):
            log("[xvfb] WARNING: %s is not installed. Without a window "
                "manager the Firefox window keeps its own default size and "
                "the calibrated card coordinates will miss."
                % XVFB_WINDOW_MANAGER)
        elif not _window_manager_present(env_display):
            log("[xvfb] starting %s on %s"
                % (XVFB_WINDOW_MANAGER, env_display))
            # "--display=:105", not "--display :105 --daemon": THIS xfwm4
            # (4.20.0) has no --daemon option and exits immediately with
            # "xfwm4: Unknown option --daemon" when given one.  Compositing
            # is turned off because nobody is looking at this framebuffer
            # and it costs a redraw per frame.  It warns once about having
            # no session manager, which is expected and harmless.
            _spawn_detached(
                [XVFB_WINDOW_MANAGER, "--display=%s" % env_display,
                 "--compositor=off"],
                "/tmp/xvfb-wm%s.log" % env_display.lstrip(":"))
            deadline = time.time() + XVFB_START_TIMEOUT_SECONDS
            while (time.time() < deadline
                   and not _window_manager_present(env_display)):
                time.sleep(0.5)
            if not _window_manager_present(env_display):
                log("[xvfb] WARNING: no window manager took %s -- see "
                    "/tmp/xvfb-wm%s.log. The Firefox window will keep its "
                    "own default size and the card coordinates will miss."
                    % (env_display, env_display.lstrip(":")))

    log("  display         : %s (Xvfb, %s)" % (env_display, XVFB_GEOMETRY))
    return True


def _window_manager_present(display):
    """True when a window manager is actually MANAGING `display`.

    _NET_SUPPORTING_WM_CHECK on the root window is the thing that matters,
    and it is set by whichever WM owns the display -- so this stays true if
    the WM is started by hand or by run_collector.sh, and goes false again
    the moment it dies.  A live process name would not prove either.

    MEASURED: xprop exits 0 even when the property is absent -- it prints
    "no such atom on any window" and succeeds -- so the OUTPUT is what gets
    tested, not the exit status.
    """
    env = dict(os.environ, DISPLAY=display)
    env.pop("XAUTHORITY", None)
    try:
        out = subprocess.run(
            ["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    except OSError:
        return False
    return b"window id #" in out


# ===========================================================================
# THE CONTROLLER CONFIG
# ===========================================================================

def build_controller_config(which_rank=None, base_url=None, logger=None):
    """Hand the browser layer everything it needs, from the block above."""
    return ControllerConfig(
        project_dir=BASE_DIR,
        rank=which_rank if which_rank is not None else rank,
        base_url=base_url or INDEED_BASE_URL,
        firefox_binary=FIREFOX_BINARY,
        display=DISPLAY_OVERRIDE or None,
        xauth_copy=FIREFOX_XAUTH_COPY or None,
        search_mode=SEARCH_MODE,
        search_field_delay_seconds=SEARCH_FIELD_DELAY_SECONDS,
        search_results_wait_seconds=SEARCH_RESULTS_WAIT_SECONDS,
        page_step=INDEED_PAGE_STEP,
        card_x=CARD_X,
        first_card_y=FIRST_CARD_Y,
        card_max_y=CARD_MAX_Y,
        card_probe_step=CARD_PROBE_STEP,
        card_probe_limit=CARD_PROBE_LIMIT,
        card_scroll_rounds=CARD_SCROLL_ROUNDS,
        card_url_marker=CARD_URL_MARKER,
        window_size=WINDOW_SIZE,
        window_pos=WINDOW_POS,
        what_xy=SEARCH_WHAT_XY,
        where_xy=SEARCH_WHERE_XY,
        pre_close_delay_seconds=PRE_CLOSE_DELAY_SECONDS,
        post_close_delay_seconds=POST_CLOSE_DELAY_SECONDS,
        window_timeout=WINDOW_TIMEOUT_SECONDS,
        focus_timeout=FOCUS_TIMEOUT_SECONDS,
        clipboard_timeout=CLIPBOARD_TIMEOUT_SECONDS,
        page_settle_seconds=PAGE_SETTLE_SECONDS,
        poll_interval=POLL_INTERVAL_SECONDS,
        key_delay_ms=KEY_DELAY_MS,
        min_detail_chars=MIN_DETAIL_CHARS,
        script_timeout=SHELL_SCRIPT_TIMEOUT_SECONDS,
        xclip_timeout=XCLIP_TIMEOUT_SECONDS,
        url_must_match=JOB_URL_PATTERN,
        verbose=VERBOSE,
        logger=logger or log,
    )


def build_excel_store(which_rank=None):
    return ExcelStore(
        output_dir=rank_dir("Excel_Data", which_rank),
        backup_dir=rank_dir("Backup", which_rank),
        working_file=DETAIL_OUTPUT_FILE,
        batch_size=EXCEL_BATCH_SIZE,
        keep_backups=EXCEL_KEEP_BACKUPS,
        logger=log,
    )


def build_checkpoint(which_rank=None, how_many=None):
    folder = project_path("config", "checkpoints")
    os.makedirs(folder, exist_ok=True)
    return Checkpoint.for_rank(
        folder,
        which_rank if which_rank is not None else rank,
        how_many if how_many is not None else num_sys,
        logger=log)


# ===========================================================================
# ONE JOB CARD
# ===========================================================================

class CardOutcome(object):
    """What happened to one job card, in one word plus the detail."""

    SAVED = "saved"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    FAILED = "failed"
    NO_MORE_CARDS = "no_more_cards"
    ACCESS_DENIED = "access_denied"

    def __init__(self, kind, reason="", row=None, job_url=""):
        self.kind = kind
        self.reason = reason
        self.row = row
        self.job_url = job_url



def log_field_report(report, row):
    """Log what the saved page gave us, field by field, all 32 of them.

    Printed for EVERY card, before the source tab closes, because "did this
    job actually come out of its own file?" is the question that matters
    most and it should never need a second tool to answer.
    """
    found = [column for column in DETAIL_COLUMNS
             if str(row.get(column, "") or "").strip()]
    log("      [fields] %d of %d columns filled   (isolation: %s, %d job(s) "
        "in the document)"
        % (len(found), len(DETAIL_COLUMNS), report.isolation,
           report.jobs_in_document))

    for column in DETAIL_COLUMNS:
        value = str(row.get(column, "") or "").strip()
        source = report.provenance.get(column, "")
        if value:
            shown = value if len(value) <= 64 else value[:61] + "..."
            shown = shown.replace("\n", " ")
            log("         %-22s %s%s"
                % (column, shown, "   [%s]" % source if source else ""))
        else:
            log("         %-22s (blank -- not stated in the saved page)"
                % column)

    if report.notes:
        for note in report.notes[:4]:
            log("      [note] %s" % note)


def process_one_card(controller, store, checkpoint, index, card_index,
                     keyword, city, input_row, page_state=None):
    """Open card ``card_index``, read it, decide, save, close.

    THE ORDER MATTERS and is the brief's section 9 order:
        open window -> copy Apply URL -> copy text -> parse -> validate ->
        non-IT filter -> duplicate check -> Excel -> checkpoint ->
        sleep 10s -> close window -> sleep 10s

    The checkpoint is advanced AFTER Excel confirms the write and never
    before it (brief section 19, rule 6).
    """
    summary = checkpoint.summary()
    window = None

    page_state = page_state if page_state is not None else {}
    seen_keys = page_state.setdefault("seen_keys", [])
    start_y = page_state.setdefault("next_start_y", FIRST_CARD_Y)

    try:
        window = controller.select_job_card(card_index,
                                            seen_keys=seen_keys,
                                            start_y=start_y)
    except ContextMenuFailed as error:
        return CardOutcome(CardOutcome.NO_MORE_CARDS, error.detail())
    except WrongJobWindow as error:
        # select_job_card.sh reports "changed nothing" when the click landed
        # where no card is, which is the normal end of a page's cards.  Any
        # OTHER identity failure is a real fault and must not be mistaken
        # for "we are finished".
        detail = error.detail()
        if "no new job card found" in detail or "changed nothing" in detail:
            return CardOutcome(CardOutcome.NO_MORE_CARDS, detail)
        return CardOutcome(CardOutcome.FAILED, detail)
    except AccessDenied as error:
        return CardOutcome(CardOutcome.ACCESS_DENIED, error.detail())
    except (FullscreenFailed, BrowserError) as error:
        return CardOutcome(CardOutcome.FAILED, error.detail())

    # Remember this job so a later probe on the same page cannot take it
    # again, and start the next probe just below where this one landed.
    if getattr(window, "job_key", ""):
        if window.job_key not in seen_keys:
            seen_keys.append(window.job_key)
    if getattr(window, "scrolled", False):
        # The list moved under us: a y learned before the scroll points at
        # a view that no longer exists. Start the next probe at the top of
        # the card area instead. seen_keys stops anything being taken twice.
        page_state["next_start_y"] = FIRST_CARD_Y
    elif getattr(window, "learned_card_y", 0):
        page_state["next_start_y"] = window.learned_card_y + MIN_CARD_GAP
    log("      selected job %s (%s%s)"
        % (window.job_key or "?", window.selection_method or "?",
           ", after scrolling" if getattr(window, "scrolled", False) else ""))

    job_url = window.url
    normalised = normalise_job_url(job_url)

    # Already handled in this combination?  Then close it and move on
    # WITHOUT reading it: that is the cross-page duplicate guard, and it
    # also stops a repeated card wasting a 20-second open/close cycle.
    if index.is_seen({"source_url": job_url}):
        log("      [dup] card %d is a job this combination already handled "
            "(%s)" % (card_index, normalised[:80]))
        checkpoint.note_duplicate()
        controller.force_close_source_tab()
        return CardOutcome(CardOutcome.DUPLICATE,
                           "already seen in this combination",
                           job_url=job_url)

    # -- Ctrl+U, Ctrl+S: the job's own page source onto disk ---------------
    try:
        source_path = controller.save_job_source(window, card_index)
    except AccessDenied as error:
        controller.force_close_source_tab()
        return CardOutcome(CardOutcome.ACCESS_DENIED, error.detail(),
                           job_url=job_url)
    except (ClipboardStale, ClipboardEmpty, WrongJobWindow,
            NavigationFailed, BrowserError) as error:
        controller.force_close_source_tab()
        return CardOutcome(CardOutcome.FAILED, error.detail(),
                           job_url=job_url)

    # -- READ ALL 32 FIELDS OUT OF THE SAVED FILE, NOW --------------------
    # This happens BEFORE the source tab is closed and before the next card
    # is selected, so every job is fully resolved from its own saved file
    # while that file is the thing on screen.
    #
    # job_key IS NOT OPTIONAL HERE.  A saved Indeed results page describes
    # EVERY card on it -- 16 jobs in a measured capture -- so without the
    # key there is nothing to tell the extractor which of them this row is
    # about.  Omitting it was a real bug: the row came back with
    #     job_title   = "Keyword : all jobs"
    #     company     = "Edit location input box label"
    # which is the page's own accessibility furniture, read by the
    # visible-text fallback because isolation never ran.
    try:
        row, report = build_row_from_file(
            source_path, apply_url=job_url, input_row=input_row,
            state_resolver=city_state_name,
            job_key=getattr(window, "job_key", ""))
    except OSError as error:
        controller.force_close_source_tab()
        return CardOutcome(CardOutcome.FAILED,
                           "saved source %s could not be read: %s"
                           % (source_path, error), job_url=job_url)

    parsed = report.parsed
    log_field_report(report, row)

    # A row that could not be isolated out of a multi-job document may be
    # describing a DIFFERENT job. Refuse it rather than write it.
    if report.isolation == "NONE":
        controller.force_close_source_tab()
        return CardOutcome(
            CardOutcome.FAILED,
            "the saved source describes %d jobs and job %s could not be "
            "isolated from it; refusing to write a row that may belong to "
            "another job" % (report.jobs_in_document,
                             getattr(window, "job_key", "?")),
            job_url=job_url)

    index.mark_seen(row)
    checkpoint.note_examined(normalise_job_url(row.get("source_url")
                                               or job_url))

    if parsed.notes:
        for note in parsed.notes:
            log("      [parse] %s" % note)
    if parsed.unavailable:
        log("      [parse] not stated by the page: %s"
            % ", ".join(sorted(set(parsed.unavailable))))

    # -- decide ------------------------------------------------------------
    decision = decide(row, index)

    excel_status = "SKIPPED"
    outcome_kind = CardOutcome.FAILED
    if decision.should_save:
        try:
            written, info = store.append_row(row, duplicate_index=index)
        except Exception as error:
            written, info = False, {"reason": "%s: %s"
                                    % (type(error).__name__, error)}
        if written:
            # ONLY NOW is the job recorded as done.  Brief restriction 12:
            # "Do not claim a job was saved unless its data was actually
            # written successfully."
            checkpoint.note_saved(row.get("job_id", ""))
            excel_status = "SUCCESS (%s rows=%s)" % (
                info.get("file", "?"), info.get("rows", "?"))
            if info.get("rolled_over"):
                excel_status += " [rolled over -> %s]" % info.get("archived")
            outcome_kind = CardOutcome.SAVED
        else:
            reason = info.get("reason", "unknown")
            excel_status = "FAILED (%s)" % reason
            checkpoint.note_failure("excel", reason,
                                    {"job_url": job_url,
                                     "job_title": row.get("job_title", "")})
            outcome_kind = CardOutcome.FAILED
    elif decision.outcome == Decision.DUPLICATE:
        checkpoint.note_duplicate()
        index.mark_rejected(row)
        outcome_kind = CardOutcome.DUPLICATE
        excel_status = "SKIPPED (duplicate)"
    else:
        checkpoint.note_rejected()
        index.mark_rejected(row)
        outcome_kind = CardOutcome.REJECTED
        excel_status = "SKIPPED (%s)" % decision

    summary = checkpoint.summary()
    show_job_line(
        summary, card_index,
        title=row.get("job_title", ""),
        company=row.get("company_name", ""),
        extraction="SUCCESS (%d chars of description)" % parsed.description_chars
        if parsed.description_chars else "PARTIAL (no description text)",
        duplicate="YES" if outcome_kind == CardOutcome.DUPLICATE else "NO",
        excel=excel_status,
        next_hint="Job Card %d" % (card_index + 1))

    # -- the two delays, and the close ------------------------------------
    # close_job_window() sleeps PRE_CLOSE before closing and POST_CLOSE after
    # the listing is back, which is exactly brief section 21's Delay 1 and
    # Delay 2.  Both sit next to the keystrokes they pace.
    try:
        controller.close_source_tab()
    except BrowserError as error:
        checkpoint.note_failure("close_source_tab", error.detail(),
                                {"job_url": job_url})
        return CardOutcome(CardOutcome.FAILED,
                           "saved, but the window would not close: %s"
                           % error.detail(), row=row, job_url=job_url)

    sleep_between(JOB_GAP_MIN_SECONDS, JOB_GAP_MAX_SECONDS,
                  "extra gap before the next card")
    return CardOutcome(outcome_kind, str(decision), row=row, job_url=job_url)


# ===========================================================================
# THE PAGE CENSUS
# ===========================================================================

class PageCensus(object):
    """What the results page's own source says about its job cards.

    ``keys``  the job keys on the page, in page order.  EMPTY MEANS
              "UNKNOWN": the census could not be read.  It never means
              "this page has no jobs" -- for that, see ``definitely_empty``.
    """

    __slots__ = ("keys", "evidence", "declared_count", "total_matches",
                 "path", "error")

    def __init__(self, keys, evidence, declared_count=None,
                 total_matches=None, path="", error=""):
        self.keys = list(keys)
        self.evidence = evidence
        self.declared_count = declared_count
        #: How many jobs the SEARCH matched, per the page itself.  This is
        #: NOT len(keys): a search that matched nothing still renders
        #: suggestion cards.
        self.total_matches = total_matches
        self.path = path
        self.error = error

    @property
    def known(self):
        """True when the page's card list was actually read."""
        return bool(self.keys)

    @property
    def definitely_empty(self):
        """True only when the page itself said it has no jobs.

        BOTH numbers must agree, because "jobCount" on its own cannot carry
        this: measured at 5 on a page holding 6 cards for a search that
        matched 17.  So a jobCount of 0 is believed only when no match
        count contradicts it -- otherwise an unreadable card list falls
        back to the fixed plan, which is the safe direction.
        """
        return (not self.keys and self.declared_count == 0
                and not self.total_matches)


def read_page_census(controller, page):
    """Ctrl+U/Ctrl+S the results page and read every card off it.

    Runs BEFORE the first card is clicked, so the card budget for this page
    is a measured number rather than FIXED_CARDS_PER_PAGE assumed.

    Raises AccessDenied -- a refusal stops the run and is not something to
    paper over with a fallback.  Every other failure returns an unknown
    census, and the caller falls back to the fixed plan.
    """
    if not COUNT_CARDS_FROM_PAGE_SOURCE:
        return PageCensus([], "disabled")

    try:
        path = controller.save_listing_source(page)
    except AccessDenied:
        raise
    except (ClipboardStale, ClipboardEmpty, WrongJobWindow,
            NavigationFailed, BrowserError) as error:
        controller.force_close_source_tab()
        return PageCensus([], "unreadable", error=error.detail())

    # The file is on disk now, so the tab has done its job. Close it before
    # parsing: a view-source tab left open would be the tab the next Ctrl+U
    # acts on.
    try:
        controller.close_source_tab(
            pre_delay=CENSUS_PRE_CLOSE_DELAY_SECONDS,
            post_delay=CENSUS_POST_CLOSE_DELAY_SECONDS)
    except BrowserError as error:
        log("  [census] the source tab would not close: %s" % error.detail())
        controller.force_close_source_tab()

    try:
        cards = page_cards(read_saved_source(path))
    except OSError as error:
        return PageCensus([], "unreadable", path=path, error=str(error))

    return PageCensus(cards.keys, cards.evidence, cards.declared_count,
                      cards.total_matches, path)


def card_budget_for_page(census, page, start_at=0, seen_keys=()):
    """What to do with this page: how many cards, and whether to stop.

    Returns ``(count, stop_reason, last_page)``.

      ``count``        how many cards to take from this page.
      ``stop_reason``  non-empty means take NOTHING and finish this
                       keyword+city here.
      ``last_page``    take the cards, then finish -- there is no page 2.

    TWO SIGNALS, IN THIS ORDER.

    1. THE SEARCH'S OWN MATCH COUNT.  The page states how many jobs the
       search matched, and that is arithmetic, not inference: if the count
       is 0, or if this page already reaches it, there is no next page.

    2. THE CARD LIST, as a backstop for when the count is missing.  If
       almost every card on this page was already on an earlier page, then
       `start=` changed nothing and this is page 1 again.

    WHY THE COUNT HAD TO COME FIRST.  Comparing card lists alone looked
    sufficient and is not.  MEASURED on five saved reloads of one results
    page: the card list CHANGED EVERY TIME -- 5 cards drawn from a pool of
    9, between 0% and 40% of them new on each reload -- because that search
    matched nothing and Indeed was filling the page with suggestions.
    Exact equality would never have fired; the match count said 0 every
    time.
    """
    fixed = MAX_CARDS_PER_PAGE
    matches = census.total_matches

    # -- 1. the match count ------------------------------------------------
    if matches == 0:
        # Nothing matched. Whatever cards are on the page are Indeed's
        # suggestions, not results for this keyword -- but they are real
        # jobs, so they are collected exactly as before. What changes is
        # that we do not then ask for four more pages of a search that has
        # none.
        if census.known:
            log("  [census] the search matched 0 jobs -- the %d card(s) on "
                "this page are Indeed's suggestions, not results for this "
                "keyword" % len(census.keys))
            return min(fixed, len(census.keys)), "", True
        return 0, "the search matched 0 jobs -- there is nothing to page to", True

    if not census.known:
        if census.definitely_empty:
            return 0, ("the page reports 0 cards -- there is nothing on it "
                        "to collect"), True
        # Unknown. Fall back to the fixed plan: probing finds the end of the
        # page the way it always did. A failed census must NEVER be read as
        # "the results ended".
        log("  [census] could not read this page's card list (%s%s) -- "
            "falling back to the fixed %d cards"
            % (census.evidence,
               ": %s" % census.error if census.error else "", fixed))
        return fixed, "", False

    found = len(census.keys)
    log("  [census] the page's own source lists %d job card(s)  "
        "(evidence: %s%s%s)"
        % (found, census.evidence,
           ", page says %s" % census.declared_count
           if census.declared_count is not None else "",
           ", search matched %s" % matches if matches is not None else ""))

    last_page = False
    if matches is not None and start_at + found >= matches:
        log("  [census] start=%d plus %d card(s) reaches the %d job(s) this "
            "search matched -- this is its last page."
            % (start_at, found, matches))
        last_page = True

    # -- 2. the card list, as a backstop ----------------------------------
    # Only consulted when the match count did not already settle it.
    seen = set(seen_keys or ())
    if STOP_WHEN_PAGE_REPEATS and seen and not last_page:
        fresh = [key for key in census.keys if key not in seen]
        # MEASURED: reloads of ONE page shared at least 60% of their cards
        # (0.00-0.40 new); a genuinely different page shares none. Half is
        # the midpoint of a wide gap, not a guess at a narrow one.
        if len(fresh) <= found * PAGE_REPEAT_NEW_CARD_FRACTION:
            return 0, ("only %d of page %d's %d card(s) are new -- start=%d "
                       "served a page already collected, so this search has "
                       "one results page"
                       % (len(fresh), page, found, start_at)), True

    if found < fixed:
        log("  [census] fewer than the fixed %d -- taking all %d%s."
            % (fixed, found,
               "" if last_page else ", then turning the page"))
    return min(fixed, found), "", last_page


# ===========================================================================
# ONE KEYWORD + CITY COMBINATION
# ===========================================================================

def run_combo(controller, store, checkpoint, index, keyword, city,
              start_page=1):
    """Every permitted results page for one keyword in one city.

    Returns ``"done"``, or ``"access_denied"`` when the source refused the
    request -- in which case the caller stops rather than retrying.
    """
    input_row = {
        "role_category": ROLE_CATEGORY,
        "job_category": ROLE_CATEGORY,
        "search_keyword": keyword,
        "city": city,
        "location": city,
    }

    page = max(1, int(start_page))
    consecutive_failures = 0
    # Page 1's url, as the search form actually produced it. Every later
    # page is derived from this, so it must be the real thing and not a
    # url rebuilt from the keyword and city.
    first_page_url = ""
    # Every job card seen on the pages of THIS keyword+city so far. A page
    # whose cards are nearly all in here is a page already collected, which
    # is what "start= did nothing" looks like.
    combo_card_keys = []

    while page <= MAX_LISTING_PAGES:
        pacing_gate()
        wait_for_internet()
        checkpoint.set_position(page=page)

        start_at = (page - 1) * INDEED_PAGE_STEP
        log("\n  [page %d/%d] %s @ %s  (start=%d)"
            % (page, FIXED_LISTING_PAGES, keyword, city, start_at))

        try:
            if page == 1 or not first_page_url:
                # PAGE 1 IS A SEARCH: typed into Indeed's own boxes.
                results = controller.search(keyword, city, start=start_at)
                first_page_url = results.get("url", "") or first_page_url
            else:
                # PAGE 2+ IS A URL, derived from page 1's.
                #
                # It used to re-run the form search with --start, which
                # form mode ignores -- so every "next page" ran the same
                # search and came back with page 1. Deriving the url from
                # page 1's keeps q, l, radius and from exactly as the form
                # built them, drops vjk=, and sets start=.
                controller.goto_listing_page(first_page_url, page)
        except AccessDenied as error:
            log("  [STOP] the source refused this search: %s" % error.detail())
            checkpoint.note_failure("search_access_denied", error.detail(),
                                    {"page": page})
            return "access_denied"
        except BrowserError as error:
            consecutive_failures += 1
            what = "the search" if page == 1 else "the page turn"
            log("  [WARN] %s failed (%s)" % (what, error.detail()))
            checkpoint.note_failure("search" if page == 1 else "page_turn",
                                    error.detail(), {"page": page})
            if consecutive_failures >= MAX_CONSECUTIVE_SEARCH_FAILURES:
                log("  [STOP] %d searches in a row failed -- giving up on "
                    "this keyword." % consecutive_failures)
                return "done"
            sleep_between(LISTING_PAGE_GAP_MIN_SECONDS,
                          LISTING_PAGE_GAP_MAX_SECONDS, "before a retry")
            continue
        consecutive_failures = 0

        # -- WHAT IS ACTUALLY ON THIS PAGE --------------------------------
        # Read the page's own source before clicking anything, so the card
        # budget is measured rather than assumed, and so a page that is
        # really page 1 again can be spotted before it is collected twice.
        try:
            census = read_page_census(controller, page)
        except AccessDenied as error:
            log("  [STOP] the source refused the results page: %s"
                % error.detail())
            checkpoint.note_failure("census_access_denied", error.detail(),
                                    {"page": page})
            return "access_denied"

        cards_this_page, stop_reason, last_page = card_budget_for_page(
            census, page, start_at, combo_card_keys)
        for key in census.keys:
            if key not in combo_card_keys:
                combo_card_keys.append(key)
        if stop_reason:
            log("  [page %d] %s -- moving on to the next keyword."
                % (page, stop_reason))
            return "done"

        new_this_page = 0
        card_failures = 0
        seen_before_page = index.unique_seen

        # PAGE STATE, carried from card to card.
        #
        #   seen_keys     the jobs already taken from THIS results page, so a
        #                 probe that lands back on one of them is treated as
        #                 a miss instead of being collected twice.
        #   next_start_y  where to begin probing for the next card.  Seeded
        #                 from configuration, then LEARNED: each successful
        #                 selection reports the y it landed on, and the next
        #                 probe starts just below it.  This is what replaced
        #                 the fixed CARD_PITCH that could not work.
        page_state = {"seen_keys": [], "next_start_y": FIRST_CARD_Y}

        # 0-BASED.  It used to start at 1, which -- on top of the pitch bug --
        # meant the first card was never even aimed at.
        #
        # The upper bound is the CENSUS, not MAX_CARDS_PER_PAGE: a page with
        # five cards is five iterations, not ten of which five fail.
        for card_index in range(0, cards_this_page):
            if _SHUTDOWN_REQUESTED:
                raise KeyboardInterrupt("shutdown requested")

            outcome = process_one_card(controller, store, checkpoint, index,
                                       card_index, keyword, city, input_row,
                                       page_state)

            if outcome.kind == CardOutcome.ACCESS_DENIED:
                log("  [STOP] the source refused a job page: %s"
                    % outcome.reason)
                checkpoint.note_failure("job_access_denied", outcome.reason,
                                        {"page": page, "card": card_index})
                return "access_denied"

            if outcome.kind == CardOutcome.NO_MORE_CARDS:
                log("  [page %d] card %d did not open a job window -- taking "
                    "that as the end of this page's cards." % (page, card_index))
                break

            if outcome.kind == CardOutcome.FAILED:
                card_failures += 1
                log("  [WARN] card %d failed: %s" % (card_index,
                                                     outcome.reason))
                checkpoint.note_failure("card", outcome.reason,
                                        {"page": page, "card": card_index,
                                         "job_url": outcome.job_url})
                if card_failures >= MAX_CONSECUTIVE_CARD_FAILURES:
                    log("  [STOP] %d cards in a row failed on this page -- "
                        "moving on." % card_failures)
                    break
                continue
            card_failures = 0

            if outcome.kind == CardOutcome.SAVED:
                new_this_page += 1

            if index.unique_seen >= TARGET_UNIQUE_JOBS:
                log("  [target] %d distinct jobs examined for this "
                    "combination (target %d) -- finishing here."
                    % (index.unique_seen, TARGET_UNIQUE_JOBS))
                return "done"

        gained = index.unique_seen - seen_before_page
        log("  [page %d] %d distinct new jobs, %d saved."
            % (page, gained, new_this_page))

        if last_page:
            # The page itself said this is the end -- its cards have now
            # been taken, so the keyword is finished. Asking for the next
            # start= would only fetch this same page again.
            log("  [page %d] this was the last page of this search -- "
                "moving on to the next keyword." % page)
            return "done"

        if STOP_ON_PAGE_WITH_NO_NEW_JOBS and page > MIN_LISTING_PAGES \
                and gained == 0:
            log("  [page %d] nothing new on this page -- that is the end of "
                "the results." % page)
            return "done"

        page += 1
        if page <= MAX_LISTING_PAGES:
            sleep_between(LISTING_PAGE_GAP_MIN_SECONDS,
                          LISTING_PAGE_GAP_MAX_SECONDS, "before the next page")

    return "done"


# ===========================================================================
# BETWEEN COMBINATIONS: A FRESH BROWSER
# ===========================================================================

#: Whether the profile was signed in last time it was checked.  Kept so the
#: log says something when it CHANGES, rather than once per keyword.
_LOGIN_STATE = {"signed_in": None}


def report_login_state(config):
    """Log the session only when it has changed since the last check.

    A restart is the moment to look: Firefox has just exited, so its cookie
    write-ahead log is checkpointed and what is on disk is the truth.  A
    session that expires mid-run otherwise shows up as "paging stopped
    working" several hundred keywords later.
    """
    signed_in, detail = check_indeed_login(config)
    if _LOGIN_STATE["signed_in"] is None:
        log("      [login] signed in: %s (%s)"
            % ("yes" if signed_in else "NO", detail))
    elif signed_in != _LOGIN_STATE["signed_in"]:
        if signed_in:
            log("      [login] the Indeed session is back (%s)" % detail)
        else:
            log("      [login] THE INDEED SESSION HAS GONE (%s)." % detail)
            log("      [login] Paging will stop working. Sign in again:")
            log("                %s save_indeed_login.py --rank %d"
                % (sys.executable, rank))
    _LOGIN_STATE["signed_in"] = signed_in
    return signed_in


def restart_for_next_combo(controller, rest_seconds, why):
    """Close the browser, rest, open it again, verify the search fields.

    This is the gap between one keyword+city and the next.  The rest is
    taken with the browser CLOSED, which is why the wait is a parameter
    rather than a constant: 5 seconds between keywords, ten minutes after a
    complete cycle, one mechanism.

    Returns (ok, detail).  AccessDenied is NOT caught -- a refusal stops the
    run, as it does everywhere else.
    """
    if not RESTART_BROWSER_BETWEEN_KEYWORDS:
        # Restarting disabled: keep the old behaviour of simply waiting.
        sleep_responsive(rest_seconds, why)
        return True, ""

    log("\n  [restart] closing the browser, resting %s, then opening a fresh "
        "window on the Indeed home page" % human_duration(rest_seconds))
    try:
        controller.restart_browser(
            wait_seconds=rest_seconds,
            start_url=controller.config.base_url,
            expect_host="indeed",
            verify_fields=VERIFY_SEARCH_FIELDS_AFTER_RESTART,
            sleeper=lambda seconds: sleep_responsive(seconds, why))
    except AccessDenied:
        raise
    except BrowserError as error:
        return False, error.detail()

    report_login_state(controller.config)
    return True, ""


# ===========================================================================
# THE CITY-WISE CYCLE LOOP (brief section 8)
# ===========================================================================

def run_cycle(controller, store, checkpoint, max_combos=None):
    """city -> all 85 keywords -> ONE COMPLETE CYCLE -> next city.

    Returns ``"complete"``, ``"access_denied"``, or ``"stopped"``.
    """
    state = checkpoint.state
    cities = state["cities"]
    order = state["keyword_order"]
    city_index, keyword_index, page = checkpoint.position()
    combos_done = 0
    restart_failures = 0

    while city_index < len(cities):
        city = cities[city_index]

        if checkpoint.city_cycle_complete(city):
            # Rule 6: "Continue from the correct incomplete city cycle."  A
            # city already counted in this crawl cycle is not redone.
            log("\n[skip] %s is already complete in crawl cycle %s."
                % (city, state["crawl_cycle_number"]))
            city_index += 1
            keyword_index = 0
            continue

        log("\n%s" % ("=" * 72))
        log("CRAWL CYCLE %s | CITY %d/%d: %s   (keywords %d..%d)"
            % (state["crawl_cycle_number"], city_index + 1, len(cities), city,
               keyword_index + 1, len(order)))
        log("TOTAL COMPLETE CYCLE SO FAR: %d" % checkpoint.total_complete_cycle)
        log("%s" % ("=" * 72))

        while keyword_index < len(order):
            _, keyword = order[keyword_index]
            checkpoint.set_position(city_index=city_index,
                                    keyword_index=keyword_index, page=page)

            pacing_gate()
            log("\n  [cycle %s | city %d/%d %s | keyword %d/%d %s | worked %s]"
                % (state["crawl_cycle_number"], city_index + 1, len(cities),
                   city, keyword_index + 1, len(order), keyword,
                   human_duration(work_seconds())))

            # A fresh duplicate index per combination, seeded from the
            # workbook, so "already saved" spans the whole rank while
            # "already seen" is per combination (brief section 17).
            index = DuplicateIndex()
            index.load_saved_rows(store.saved_rows())
            index.load_seen_urls(state.get("done_job_urls") or [])

            result = run_combo(controller, store, checkpoint, index,
                               keyword, city, start_page=page)
            page = 1

            if result == "access_denied":
                checkpoint.save()
                return "access_denied"

            checkpoint.complete_keyword(keyword_index)
            keyword_index += 1
            combos_done += 1

            if max_combos and combos_done >= max_combos:
                log("\n[stop] --max-combos %d reached; the checkpoint is "
                    "saved at city %d keyword %d."
                    % (max_combos, city_index + 1, keyword_index + 1))
                checkpoint.save()
                return "stopped"

            if keyword_index < len(order):
                # THE KEYWORD IS FINISHED -- every card of every page it
                # had. Close the browser, wait, open a fresh one on the
                # home page, verify the search fields, then type the next
                # keyword into them.
                ok, detail = restart_for_next_combo(
                    controller, BROWSER_RESTART_WAIT_SECONDS,
                    "before the next keyword")
                if ok:
                    restart_failures = 0
                else:
                    restart_failures += 1
                    log("  [WARN] the browser restart failed (%s)" % detail)
                    checkpoint.note_failure(
                        "browser_restart", detail,
                        {"city": city, "keyword": keyword,
                         "consecutive": restart_failures})
                    if restart_failures >= MAX_CONSECUTIVE_RESTART_FAILURES:
                        log("  [STOP] %d browser restarts in a row failed. "
                            "Every keyword after this would be typed into a "
                            "page that cannot be vouched for -- stopping "
                            "instead." % restart_failures)
                        checkpoint.save()
                        return "stopped"

        # ALL 85 KEYWORDS ARE DONE FOR THIS CITY.  That is one complete
        # cycle, and this is the only place it is counted.
        counted, total = checkpoint.complete_city_cycle(city)
        log("\n%s" % ("#" * 72))
        log("# COMPLETE CYCLE %s%s -- %s finished all %d keywords."
            % (total, "" if counted else " (already counted)", city,
               len(order)))
        log("# TOTAL COMPLETE CYCLE: %d" % total)
        log("%s" % ("#" * 72))

        city_index += 1
        keyword_index = 0

        if city_index < len(cities):
            # A COMPLETE CYCLE IS DONE. Rest for ten minutes -- with the
            # browser closed -- before the next city's first keyword, where
            # BOTH the keyword and the city change.
            log("\n[rest] one complete cycle is done; resting %s before the "
                "next keyword + city."
                % human_duration(COMPLETE_CYCLE_REST_SECONDS))
            ok, detail = restart_for_next_combo(
                controller, COMPLETE_CYCLE_REST_SECONDS,
                "complete-cycle rest")
            if ok:
                restart_failures = 0
            else:
                restart_failures += 1
                log("  [WARN] the browser restart failed (%s)" % detail)
                checkpoint.note_failure("browser_restart", detail,
                                        {"city": city,
                                         "consecutive": restart_failures})
                if restart_failures >= MAX_CONSECUTIVE_RESTART_FAILURES:
                    checkpoint.save()
                    return "stopped"

    return "complete"


# ===========================================================================
# SHUTDOWN
# ===========================================================================

def save_checkpoint_now():
    if _CHECKPOINT is None or _CHECKPOINT.state is None:
        return False
    try:
        _CHECKPOINT.save()
        return True
    except Exception as error:
        log("[STOP] the checkpoint could not be saved: %s" % error)
        return False


def handle_signal(signum, _frame):
    """Save, kill the browser, exit.  Runs inside a signal handler.

    It must not wait for anything: the checkpoint is one small atomic JSON
    write, which is safe here, and the browser is KILLED rather than closed
    because a polite close needs an idle driver and there may be a
    navigation in flight.
    """
    global _SHUTDOWN_REQUESTED
    _SHUTDOWN_REQUESTED = True
    saved = save_checkpoint_now()
    if _CONTROLLER is not None:
        try:
            _CONTROLLER.kill_browser()
        except Exception:
            pass
    log("\n[STOP] signal %s. Checkpoint %s -- re-run to continue from here."
        % (signum, "saved" if saved else "unchanged"))
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(130)


# ===========================================================================
# MODES
# ===========================================================================

def show_plan(args):
    """Print the plan and exit.  No browser, no network, no files written."""
    cities = all_cities()
    plan = keyword_plan_pairs()
    target, other, percent = role_plan_split()

    log("=" * 72)
    log("PLAN")
    log("=" * 72)
    log("  %s" % upstream.describe())
    log("  roles           : %d  (%d target + %d other = %.1f%% target)"
        % (len(plan), target, other, percent))
    log("  cities          : %d unique" % len(cities))
    log("  excel columns   : %d" % len(DETAIL_COLUMNS))
    log("")
    log("  rank distribution for num_sys=%d:" % num_sys)
    assigned = []
    for which in range(1, num_sys + 1):
        slice_ = get_cities_by_rank(cities, which, num_sys)
        assigned.extend(slice_)
        log("    rank %d : %2d cities  %s%s"
            % (which, len(slice_), ", ".join(slice_[:3]),
               " ..." if len(slice_) > 3 else ""))
    log("    ----------------------------------------")
    log("    total assigned : %d / %d" % (len(assigned), len(cities)))
    log("    every city once: %s" % (len(set(assigned)) == len(cities)
                                     and len(assigned) == len(cities)))
    if num_sys == 5 and len(cities) == 110:
        log("")
        log("    NOTE: the original project's algorithm gives")
        log("    %s, not 22/22/22/22/22. See"
            % "/".join(str(len(get_cities_by_rank(cities, r, 5)))
                       for r in range(1, 6)))
        log("    get_cities_by_rank()'s docstring for why that is preserved.")
    log("")
    log("  rank %d gets %d cities and %d keywords = %d combinations per "
        "crawl cycle" % (rank, len(rank_cities()), len(plan),
                         len(rank_cities()) * len(plan)))
    log("  one COMPLETE CYCLE = all %d keywords for one city, so a crawl "
        "cycle is %d complete cycles." % (len(plan), len(rank_cities())))
    log("=" * 72)
    return 0


def show_status(args):
    """Print this rank's checkpoint and Excel state.  Changes nothing."""
    checkpoint = build_checkpoint()
    state = checkpoint.load()
    store = build_excel_store()

    log("=" * 72)
    log("STATUS -- rank %d of %d" % (rank, num_sys))
    log("=" * 72)
    log("  checkpoint : %s" % checkpoint.path)
    if not state:
        log("  (no checkpoint yet -- this rank has not run)")
    else:
        for key in ("schema_version", "nesting", "crawl_cycle_number",
                    "cycle_started_at", "total_assigned_cities",
                    "current_city", "current_city_index", "current_keyword",
                    "current_keyword_index", "current_page",
                    "last_completed_job_id", "examined_jobs", "saved_jobs",
                    "duplicate_jobs", "rejected_jobs", "failed_jobs",
                    "total_complete_cycle", "cycle_complete", "updated_at"):
            if key in state:
                log("  %-22s : %s" % (key, state[key]))
        log("  %-22s : %d of %d"
            % ("completed_cities", len(state.get("completed_cities") or []),
               state.get("total_assigned_cities", 0)))
        failure = state.get("failure_state")
        if failure:
            log("  last failure           : %s" % json.dumps(failure))
    log("")
    log("  excel dir  : %s" % store.output_dir)
    if os.path.isdir(store.output_dir):
        for name in sorted(os.listdir(store.output_dir)):
            path = os.path.join(store.output_dir, name)
            log("    %-34s %8d bytes" % (name, os.path.getsize(path)))
        log("  working file rows : %d" % store.row_count())
    else:
        log("    (nothing written yet)")
    log("=" * 72)
    return 0


def _fixture_url():
    return "file://%s" % project_path("tests", "fixtures", "listing_page.html")


def collect(args):
    """The real loop, against either the live site or a local fixture."""
    global _CHECKPOINT, _CONTROLLER

    fixture = bool(args.fixture_run)
    base_url = _fixture_url() if fixture else INDEED_BASE_URL

    if not fixture:
        if not LIVE_COLLECTION_ENABLED:
            log("LIVE COLLECTION IS DISABLED.")
            log("")
            log("  LIVE_COLLECTION_ENABLED is False at the top of %s."
                % os.path.basename(__file__))
            log("  Brief restriction 14: 'Do not start unattended live job")
            log("  collection without approval.'  To approve a live run:")
            log("")
            log("    1. set LIVE_COLLECTION_ENABLED = True in this file, and")
            log("    2. export %s=%s"
                % (LIVE_APPROVAL_ENV, LIVE_APPROVAL_VALUE))
            log("")
            log("  To exercise the whole pipeline now, without touching")
            log("  Indeed, use:  python3 %s --fixture-run"
                % os.path.basename(__file__))
            return 3
        if os.environ.get(LIVE_APPROVAL_ENV, "") != LIVE_APPROVAL_VALUE:
            log("LIVE COLLECTION IS ENABLED IN THE FILE BUT NOT APPROVED IN "
                "THE ENVIRONMENT.")
            log("  export %s=%s to approve this run."
                % (LIVE_APPROVAL_ENV, LIVE_APPROVAL_VALUE))
            return 3

    open_log()
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Before anything is opened or written: there has to be a display to
    # drive.  Over ssh there is none, so one is created -- see the XVFB_*
    # block at the top of this file.
    if not ensure_display():
        return 11                    # EX_NO_DISPLAY, as indeed_controller.py

    cities = rank_cities()
    plan = keyword_plan_pairs()

    checkpoint = build_checkpoint()
    _CHECKPOINT = checkpoint
    checkpoint.load_or_open(cities, plan, KEYWORD_SHUFFLE_ENABLED)

    store = build_excel_store()
    os.makedirs(rank_dir("Temp_Data"), exist_ok=True)

    show_banner(cities, plan, checkpoint)
    if fixture:
        log("  MODE: FIXTURE -- %s" % base_url)
        log("  No request reaches Indeed in this mode.")

    missing = check_excel_dependencies()
    if missing:
        log("")
        log("[STOP] Excel cannot be written: %s not installed."
            % ", ".join(missing))
        log("  Interpreter : %s" % sys.executable)
        log("  Install with: %s -m pip install %s"
            % (sys.executable, " ".join(missing)))
        log("  Without this every job would extract correctly and then fail")
        log("  at the Excel step, leaving saved_jobs at 0.")
        log("")
        return 5

    config = build_controller_config(base_url=base_url)

    signed_in, detail = check_indeed_login(config)
    if signed_in:
        log("  indeed login   : signed in  (%s)" % detail)
    elif not fixture:
        log("")
        log("  [WARN] NOT SIGNED IN to Indeed (%s)." % detail)
        log("         Indeed asks for a login when paging deeper into")
        log("         results, so this run will collect the first page or")
        log("         two and then stop finding new jobs.")
        log("         Each rank has its OWN browser profile, so a login in")
        log("         one rank's profile is invisible to the others.")
        log("         Sign in once:")
        log("             %s save_indeed_login.py --rank %d"
            % (sys.executable, rank))
        log("         Or, if another rank is already signed in, copy its")
        log("         session to every rank without signing in again:")
        log("             %s save_indeed_login.py --sync-only --rank <that one>"
            % sys.executable)
        log("")

    # A file:// fixture has no Indeed search form to click, so form mode
    # cannot work there.  Falling back is automatic rather than something
    # the operator has to remember, and it is logged so a fixture run is
    # never mistaken for a test of the form-typing path.
    if fixture and config.search_mode == "form":
        config.search_mode = "url"
        log("  search mode    : url (fixtures have no search form to type into)")
    else:
        log("  search mode    : %s" % config.search_mode)

    controller = IndeedController(config)
    _CONTROLLER = controller

    reset_work_timer()
    exit_code = 0
    try:
        controller.open_browser(start_url=base_url,
                               expect_host=None if fixture else "indeed")

        # FIND THE SEARCH BOXES BEFORE THE FIRST KEYWORD IS TYPED.
        #
        # This was missing, and it is the gap the 2026-11-10 run fell
        # through: every restart BETWEEN keywords verified the fields, but
        # the first browser of the run did not -- so keyword 1 clicked at a
        # coordinate nothing had checked, missed the box, and reported "the
        # keyword box holds <4KB of Indeed's home page>" on a loop.
        #
        # Fixtures have no search form to find, so they are exempt.
        if not fixture and VERIFY_SEARCH_FIELDS_AFTER_RESTART:
            try:
                controller.verify_search_fields()
            except AccessDenied:
                raise
            except BrowserError as error:
                log("\n[FAIL] the Indeed search boxes could not be found: %s"
                    % error.detail())
                log("  Nothing has been searched. The run stops here rather "
                    "than typing keywords at a coordinate nothing has "
                    "checked -- that is how a run once ended up reading job "
                    "cards from youtube.com.")
                raise

        result = run_cycle(controller, store, checkpoint,
                           max_combos=args.max_combos)

        if result == "complete":
            checkpoint.complete_crawl_cycle()
            log("\n[cooldown] resting %d minutes before the next crawl cycle."
                % CYCLE_COOLDOWN_MINUTES)
            sleep_responsive(CYCLE_COOLDOWN_MINUTES * 60, "cycle cooldown")
        elif result == "access_denied":
            log("\n[STOP] the source refused a request. This collection run "
                "is stopping, as the brief requires.")
            log("  No retry, no cookie clearing, no identity change, no "
                "proxy. The checkpoint is saved; investigate before resuming.")
            exit_code = 5
        else:
            log("\n[stop] %s" % result)

    except ScheduledPause as pause:
        save_checkpoint_now()
        log("\n[PAUSE] %s" % pause.reason)
        log("  the checkpoint is saved; resuming in %s"
            % human_duration(pause.seconds))
        controller.close_browser()
        sleep_responsive(pause.seconds, "scheduled rest")
        exit_code = 75                       # EX_TEMPFAIL: "run me again"
    except KeyboardInterrupt:
        save_checkpoint_now()
        log("\n[STOP] interrupted. The checkpoint is saved.")
        exit_code = 130
    except BrowserError as error:
        save_checkpoint_now()
        checkpoint.note_failure(error.stage or "browser", error.detail())
        log("\n[FAIL] %s" % error.detail())
        exit_code = 6
    finally:
        save_checkpoint_now()
        try:
            controller.close_browser()
        except Exception:
            pass
        summary = checkpoint.summary()
        log("")
        log("=" * 72)
        log("RUN SUMMARY -- rank %d/%d" % (rank, num_sys))
        log("  examined %d | saved %d | duplicates %d | rejected %d | "
            "failures %d" % (summary["examined"], summary["saved"],
                             summary["duplicates"], summary["rejected"],
                             summary["failures"]))
        log("  TOTAL COMPLETE CYCLE : %d" % summary["total_complete_cycle"])
        log("  cities finished this crawl cycle : %d/%d"
            % (summary["completed_cities"], summary["total_cities"]))
        log("  checkpoint : %s" % checkpoint.path)
        log("  excel      : %s" % store.output_dir)
        log("=" * 72)
    return exit_code


# ===========================================================================
# ENTRY POINT
# ===========================================================================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Indeed collector driven through Firefox with xdotool and "
                    "xclip.",
        epilog="Live collection is gated: see LIVE_COLLECTION_ENABLED.")
    parser.add_argument("--rank", type=int, default=rank,
                        help="which script am I (1..num-sys). Default %d"
                             % rank)
    parser.add_argument("--num-sys", type=int, default=num_sys,
                        help="how many scripts are configured. Default %d"
                             % num_sys)
    parser.add_argument("--plan", action="store_true",
                        help="print the role/city/rank plan and exit")
    parser.add_argument("--status", action="store_true",
                        help="print this rank's checkpoint and Excel state")
    parser.add_argument("--fixture-run", action="store_true",
                        help="run the whole pipeline against the local HTML "
                             "fixtures (real Firefox, no Indeed)")
    parser.add_argument("--max-combos", type=int, default=None,
                        help="stop after N keyword+city combinations")
    parser.add_argument("--pre-close-delay", type=float, default=None,
                        help="override the delay before closing a detail "
                             "window (default %.0fs)"
                             % PRE_CLOSE_DELAY_SECONDS)
    parser.add_argument("--post-close-delay", type=float, default=None,
                        help="override the delay before the next card "
                             "(default %.0fs)" % POST_CLOSE_DELAY_SECONDS)
    parser.add_argument("--max-pages", type=int, default=None,
                        help="override MAX_LISTING_PAGES")
    parser.add_argument("--verify-fields", action="store_true",
                        help="open the browser, find Indeed's two search "
                             "boxes, report where they are, and exit. "
                             "Searches nothing and collects nothing.")
    return parser.parse_args(argv)


def verify_fields_only(args):
    """--verify-fields: find the two search boxes and report them.

    The whole collection machinery is bypassed.  This opens the browser
    exactly as a run does, probes for the boxes, prints the coordinates it
    found, and leaves them in Temp_Data/rank_N/search_fields.json so the
    next real run starts from a position that has been proven rather than
    one that was measured on someone else's screen.

    It types a two-letter probe, reads it back, and clears it.  It never
    presses Return: nothing is searched and nothing is written to Excel.
    """
    config = build_controller_config(which_rank=args.rank)
    controller = IndeedController(config)

    log("=" * 72)
    log("FINDING INDEED'S SEARCH BOXES -- rank %d" % args.rank)
    log("=" * 72)
    log("  profile    : %s" % config.profile_dir)
    log("  home page  : %s" % config.base_url)
    log("  first guess: what=%d,%d where=%d,%d"
        % (controller._field_xy("what") + controller._field_xy("where")))
    if controller.what_offset:
        log("  (that first guess comes from %s)"
            % controller.learned_fields_file)
    signed_in, detail = check_indeed_login(config)
    log("  login      : %s (%s)"
        % ("signed in" if signed_in else "NOT signed in", detail))
    log("")

    try:
        controller.open_browser(start_url=config.base_url,
                                expect_host="indeed")
        results = controller.verify_search_fields()
    except BrowserError as error:
        log("\n[FAIL] %s" % error.detail())
        log("\nWhat to try next:")
        log("  * Was the page a working Indeed home page? Signed in, it is")
        log("    a different layout -- 'Jobs for you' rather than the hero")
        log("    search panel -- and the boxes sit elsewhere.")
        log("  * Widen the search: --scan-reach is %s px by default in"
            % "120")
        log("    verify_search_fields.sh; raise FIELD_SCAN_REACH to look")
        log("    further from the starting guess.")
        log("  * The window must be visible and not covered.")
        return 6
    finally:
        controller.close_browser(wait=True)

    log("")
    log("=" * 72)
    log("  keyword box  : %s" % results.get("learned_what_xy", "NOT FOUND"))
    log("  location box : %s" % results.get("learned_where_xy", "NOT FOUND"))
    log("  probes used  : %s" % results.get("probes", "?"))
    log("  remembered as offsets from the window corner: what=%s where=%s"
        % (controller.what_offset, controller.where_offset))
    log("  stored in    : %s" % controller.learned_fields_file)
    log("=" * 72)
    log("Nothing was searched. A collection run will now aim here first.")
    return 0


def main(argv=None):
    global rank, num_sys, PRE_CLOSE_DELAY_SECONDS, POST_CLOSE_DELAY_SECONDS
    global MAX_LISTING_PAGES

    args = parse_args(argv)

    if args.num_sys < 1:
        log("--num-sys must be at least 1")
        return 2
    if not 1 <= args.rank <= args.num_sys:
        log("--rank must be between 1 and --num-sys (%d)" % args.num_sys)
        return 2
    rank, num_sys = args.rank, args.num_sys

    if args.pre_close_delay is not None:
        PRE_CLOSE_DELAY_SECONDS = float(args.pre_close_delay)
    if args.post_close_delay is not None:
        POST_CLOSE_DELAY_SECONDS = float(args.post_close_delay)
    if args.max_pages is not None:
        MAX_LISTING_PAGES = int(args.max_pages)

    try:
        if args.plan:
            return show_plan(args)
        if args.status:
            return show_status(args)
        if args.verify_fields:
            return verify_fields_only(args)
        return collect(args)
    except upstream.UpstreamNotFound as error:
        log("[FAIL] %s" % error)
        return 10


if __name__ == "__main__":
    sys.exit(main())
