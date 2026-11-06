#!/usr/bin/env bash
# Shared helpers for every Firefox control script in this project.
#
# Sourced, never executed.  It defines exit codes, logging, the window and
# clipboard primitives, and the environment Firefox has to be started in on
# this machine.
#
# ===========================================================================
# THREE MEASURED FACTS ABOUT THIS MACHINE
# ===========================================================================
# These were observed directly on 2026-11-05, not assumed.  Each one breaks
# the whole approach if it is ignored, so each one is written down.
#
# FACT 1.  THE DESKTOP SESSION IS WAYLAND, AND xdotool CANNOT DRIVE WAYLAND.
#
#   XDG_SESSION_TYPE=wayland, WAYLAND_DISPLAY=wayland-0.  A Wayland surface
#   is not an X11 window: xdotool cannot find it, focus it or type into it,
#   and xclip cannot read its selection.  There is no flag that changes
#   that; it is what Wayland is for.
#
#   XWayland IS running (DISPLAY=:0, /tmp/.X11-unix/X0) and xdotool talks to
#   it fine.  So Firefox is started with MOZ_ENABLE_WAYLAND=0 and
#   GDK_BACKEND=x11, which makes its window a REAL X11 window that xdotool
#   can see.  Verified: window 0x... appeared under `xdotool search --pid`
#   and F11/Ctrl+U/Ctrl+S all reached it.
#
# FACT 2.  FIREFOX HERE IS A SNAP, AND THE SNAP HAS A PRIVATE /tmp.
#
#   /usr/bin/firefox is the transitional package; the real browser is the
#   `firefox` snap (157.0).  Two consequences:
#
#     a) The snap CANNOT see the host's /tmp.  A page saved to /tmp by
#        Ctrl+S would be written into the snap's private tmp and be
#        invisible to Python.  Everything this project saves therefore goes
#        under $HOME (Temp_Data/), which the snap's `home` interface allows.
#        SAVE PATHS OUTSIDE $HOME DO NOT WORK.  This is why TEMP_ROOT is
#        validated below.
#
#     b) Starting it through the /usr/bin/firefox wrapper with the X11
#        environment forced did NOT work -- the wrapper re-derived its own
#        environment and the browser exited with "cannot open display: :0".
#        Starting the snap's inner binary inside `snap run --shell firefox`
#        with XAUTHORITY set DID work.  That is what firefox_launch_command()
#        below produces, and FIREFOX_LAUNCH_MODE overrides it.
#
# FACT 3.  A SECOND FIREFOX NEEDS --new-instance AND ITS OWN --profile.
#
#   A bare `firefox URL` while the user's Firefox is running just opens a
#   tab in THEIR browser and exits.  That would both fail to give us a
#   window we own and interfere with somebody else's session, which this
#   project must never do.  --new-instance plus a dedicated --profile makes
#   it a separate process whose pid identifies its windows.
#
#   Never adopt, focus or close a Firefox window this project did not start.
#
# ===========================================================================

# ---------------------------------------------------------------------------
# EXIT CODES.  Python reads these, so they are a contract.
# ---------------------------------------------------------------------------
EX_OK=0
EX_USAGE=2
EX_LAUNCH=3            # the browser would not start
EX_NO_WINDOW=4         # no window of ours exists / it disappeared
EX_FOCUS=5             # could not focus our window
EX_FULLSCREEN=6        # (retired) fullscreen could not be confirmed
EX_WINDOW_GEOMETRY=15  # the window is not a usable size
EX_NAVIGATION=7        # the expected page is not there
EX_CLIPBOARD_STALE=8   # Ctrl+C did not change the clipboard
EX_CLIPBOARD_EMPTY=9   # the copy produced nothing
EX_ACCESS_DENIED=10    # the site refused us -- STOP, never work around it
EX_IDENTITY=11         # the selected job is not the job we meant
EX_SOURCE_TAB=12       # Ctrl+U did not produce a view-source tab
EX_SAVE_DIALOG=13      # the Ctrl+S dialog did not appear or would not drive
EX_SAVE_FILE=14        # the dialog ran but no usable file arrived

# ---------------------------------------------------------------------------
# TUNABLES.  Every one is overridable from the environment, so Python's
# settings.json can set them without any script being edited.
# ---------------------------------------------------------------------------
: "${KEY_DELAY_MS:=14}"            # xdotool type --delay
: "${PAGE_SETTLE_SECONDS:=3}"      # after a navigation, before reading
# How long to let Indeed's page finish rendering AFTER it has loaded and
# BEFORE clicking into its search boxes.  This is not belt-and-braces: the
# "what" and "where" boxes move while the hero area lays out, so a click
# sent too early lands on the page background, the keyword goes nowhere,
# and the Return that follows is delivered to whatever has focus.
: "${SEARCH_FIELD_DELAY_SECONDS:=7}"
# How long to let the results page load after Return, before the first job
# card is selected.  This REPLACED a set of post-search verifications (url
# must contain q= and l=, vjk= must appear) that blocked progression; a
# plain wait is what was asked for instead.
: "${SEARCH_RESULTS_WAIT_SECONDS:=10}"
: "${CLIPBOARD_TIMEOUT:=8}"        # how long to wait for Ctrl+C to land
: "${FOCUS_TIMEOUT:=10}"
: "${FULLSCREEN_TIMEOUT:=10}"
: "${WINDOW_TIMEOUT:=45}"          # cold snap start is slow
: "${SAVE_DIALOG_TIMEOUT:=20}"
: "${SAVE_FILE_TIMEOUT:=25}"
: "${SOURCE_TAB_TIMEOUT:=15}"
: "${POLL_INTERVAL:=0.25}"
: "${MIN_SOURCE_BYTES:=500}"       # below this, a saved source is not a page

SCRIPT_NAME="${SCRIPT_NAME:-$(basename "${BASH_SOURCE[1]:-shell}" .sh)}"

# ---------------------------------------------------------------------------
# LOGGING.  stdout is the machine channel (RESULT: lines only); everything a
# human reads goes to stderr, so Python can parse stdout without filtering.
# ---------------------------------------------------------------------------
emit() { printf 'RESULT:%s\n' "$1"; }
note() { printf '[%s] %s\n' "$SCRIPT_NAME" "$1" >&2; }
warn() { printf '[%s] WARNING: %s\n' "$SCRIPT_NAME" "$1" >&2; }

fail() {
    local code="$1"; shift
    printf '[%s] ERROR(%s): %s\n' "$SCRIPT_NAME" "$code" "$*" >&2
    emit "error=$*"
    emit "exit_code=$code"
    exit "$code"
}

# ---------------------------------------------------------------------------
# PRECONDITIONS
# ---------------------------------------------------------------------------
require_tools() {
    local tool
    for tool in "$@"; do
        command -v "$tool" >/dev/null 2>&1 \
            || fail "$EX_USAGE" "required tool '$tool' is not installed"
    done
}

require_display() {
    [ -n "${DISPLAY:-}" ] \
        || fail "$EX_USAGE" "DISPLAY is not set -- there is no X display to drive (see FACT 1)"
    xdotool getactivewindow >/dev/null 2>&1 && return 0
    # getactivewindow fails when no X11 window is focused, which is normal on
    # a Wayland desktop with no XWayland client up yet.  Prove the connection
    # a different way before giving up.
    xdotool search --maxdepth 1 "" >/dev/null 2>&1 \
        || fail "$EX_USAGE" "cannot talk to X display '$DISPLAY' (XAUTHORITY=${XAUTHORITY:-unset})"
}

# ---------------------------------------------------------------------------
# WINDOWS
# ---------------------------------------------------------------------------
window_exists() { xdotool getwindowname "$1" >/dev/null 2>&1; }
window_name()   { xdotool getwindowname "$1" 2>/dev/null; }
window_pid()    { xdotool getwindowpid  "$1" 2>/dev/null; }

#: Every visible window belonging to a pid or any of its children.
window_id() {
    local pid="$1" found=""
    found=$(xdotool search --onlyvisible --pid "$pid" 2>/dev/null | head -1)
    printf '%s' "$found"
}

wait_for_window_of_pid() {
    local pid="$1" timeout="${2:-$WINDOW_TIMEOUT}" waited=0 win="" child
    while [ "$(printf '%.0f' "$waited")" -lt "$timeout" ]; do
        win=$(window_id "$pid")
        if [ -n "$win" ]; then printf '%s' "$win"; return 0; fi
        for child in $(pgrep -P "$pid" 2>/dev/null); do
            win=$(window_id "$child")
            if [ -n "$win" ]; then printf '%s' "$win"; return 0; fi
        done
        sleep "$POLL_INTERVAL"
        waited=$(awk "BEGIN{print $waited + $POLL_INTERVAL}")
    done
    return 1
}

#: MEASURED: `xdotool getactivewindow` is NOT reliable on this desktop.
#: It reads _NET_ACTIVE_WINDOW from the X root, and mutter does not publish
#: that while a native WAYLAND surface holds focus -- which is the normal
#: state whenever the user's own apps are in front.  Observed directly:
#: getactivewindow failed with "XGetWindowProperty[_NET_ACTIVE_WINDOW]
#: failed (code=1)" at the same moment Ctrl+L/Ctrl+C were demonstrably
#: reaching our Firefox window and returning its url.
#:
#: So focus is confirmed from the WINDOW's own _NET_WM_STATE_FOCUSED, which
#: mutter does maintain, and _NET_ACTIVE_WINDOW is only an optional
#: corroboration.
window_has_focus() {
    local win="$1" active
    xprop -id "$win" _NET_WM_STATE 2>/dev/null | grep -q "_NET_WM_STATE_FOCUSED" \
        && return 0
    active=$(xdotool getactivewindow 2>/dev/null) || return 1
    [ "$active" = "$win" ]
}

require_focus() {
    local win="$1" waited=0
    xdotool windowactivate --sync "$win" >/dev/null 2>&1
    while [ "$(printf '%.0f' "$waited")" -lt "$FOCUS_TIMEOUT" ]; do
        window_has_focus "$win" && return 0
        xdotool windowactivate "$win" >/dev/null 2>&1
        sleep "$POLL_INTERVAL"
        waited=$(awk "BEGIN{print $waited + $POLL_INTERVAL}")
    done
    fail "$EX_FOCUS" "could not focus window $win within ${FOCUS_TIMEOUT}s"
}

#: Close the address-bar suggestion panel.
#:
#: MEASURED, AND IT WRECKED THREE LIVE RUNS. Ctrl+L does not merely focus
#: the address bar -- it opens a suggestion DROPDOWN that covers the top of
#: the content area (roughly 500px tall, the full width of the page). Every
#: address-bar read therefore leaves a panel sitting on top of the page.
#:
#: The next thing the search does is click where Indeed's keyword box is...
#: which, with the panel open, is a row in that dropdown. Captured as a
#: screenshot: the click point landed exactly on "YouTube - youtube.com".
#: The browser dutifully navigated to YouTube, and on another run to
#: Wikipedia, and the search then "failed" for reasons that looked like
#: focus theft and were nothing of the kind.
#:
#: So: after reading the address bar and before clicking into the page, the
#: panel is dismissed. Escape is the one key that closes it. Escape also
#: means STOP LOADING, so this is only ever called when no navigation is in
#: flight -- never inside a wait loop.
dismiss_url_dropdown() {
    xdotool key --clearmodifiers Escape >/dev/null 2>&1
    sleep 0.4
}

#: Put keyboard focus in the PAGE, deterministically.
#:
#: THIS IS THE BUG THAT BROKE Ctrl+U, AND IT IS WORTH THE PARAGRAPH.
#:
#: The old body was `Escape; F6`, from whatever state focus happened to be
#: in. Two measurements on the live browser killed that:
#:
#:   * F6 TOGGLES between the address bar and the page. It does not "go to
#:     the page". From the address bar it reaches the page; from the page it
#:     goes to the ADDRESS BAR.
#:   * Escape does NOT move focus out of the address bar. Measured:
#:     Ctrl+L then Escape still had the caret in the address bar.
#:
#: So `Escape; F6` starting from page focus LANDED IN THE ADDRESS BAR, and
#: the Ctrl+U that followed was interpreted as a text-field edit -- Ctrl+U
#: in a GTK entry is "delete to start of line". Observed live: the address
#: bar was wiped, no view-source tab opened, and every later address-bar
#: read came back empty. That is the whole of:
#:
#:     ERROR(12): Ctrl+U did not produce the view-source tab within 15s.
#:                Address bar reads: <unreadable>
#:
#: The fix is to stop guessing the current state. Ctrl+L ALWAYS lands in the
#: address bar; F6 from there ALWAYS lands in the page. Measured from both
#: starting states, it gives PAGE either way.
#:
#: Escape is deliberately NOT used here: on a page that is still loading it
#: means STOP LOADING, which is a separate bug this project already had.
focus_page_content() {
    local win="$1"
    xdotool key --clearmodifiers ctrl+l >/dev/null 2>&1; sleep 0.35
    xdotool key --clearmodifiers F6     >/dev/null 2>&1; sleep 0.35
}

#: True when _NET_WM_STATE carries _NET_WM_STATE_FULLSCREEN.
is_fullscreen() {
    xprop -id "$1" _NET_WM_STATE 2>/dev/null | grep -q "_NET_WM_STATE_FULLSCREEN"
}

#: Fullscreen is REQUIRED for the whole workflow, so it is re-checked at the
#: start of every step rather than only at launch.
#: NORMAL WINDOW MODE -- fullscreen is deliberately NOT used any more.
#:
#: The project used to press F11 and refuse to continue unless
#: _NET_WM_STATE_FULLSCREEN was set.  That requirement has been WITHDRAWN:
#: Firefox now runs in an ordinary decorated window so the operator can
#: watch it, matching the supplied screenshot (1845x1046 on a 1920x1080
#: screen, title bar visible).
#:
#: What replaced it is NOT "nothing".  A window still has to be mapped,
#: focused and the size we expect before a coordinate-based click means
#: anything, so require_window_ready() checks exactly that.
exit_fullscreen_if_set() {
    local win="$1"
    is_fullscreen "$win" || return 0
    note "window $win is fullscreen; leaving fullscreen (normal window mode)"
    xdotool windowactivate --sync "$win" >/dev/null 2>&1
    focus_page_content "$win"
    xdotool key --clearmodifiers F11 >/dev/null 2>&1
    local waited=0
    while [ "$(printf '%.0f' "$waited")" -lt 6 ]; do
        is_fullscreen "$win" || { note "left fullscreen"; return 0; }
        sleep "$POLL_INTERVAL"
        waited=$(awk "BEGIN{print $waited + $POLL_INTERVAL}")
    done
    warn "could not leave fullscreen; continuing in whatever state it is in"
    return 1
}

#: Put the window where the screenshot has it.  Size and position are
#: arguments, never constants: a different screen needs different numbers
#: and nothing here should have to be edited to supply them.
#: MEASURED: a single windowsize/windowmove right after the window appears
#: is frequently IGNORED -- the window is still mapping and the compositor
#: overrides it.  Observed: asked for 1845x1046+0+34, got 1332x999+44+4.
#: That matters more than it looks, because the search-box and job-card
#: coordinates are measured against the intended size; in a 1332-wide
#: window the click lands somewhere else entirely.
#:
#: So the request is repeated until the geometry sticks, and the caller is
#: told what was actually achieved rather than what was asked for.
set_window_geometry() {
    local win="$1" x="$2" y="$3" width="$4" height="$5"
    local attempt=0 got_w got_h line X= Y= WIDTH= HEIGHT=

    while [ "$attempt" -lt 5 ]; do
        attempt=$((attempt + 1))
        [ -n "$width" ] && [ -n "$height" ] \
            && xdotool windowsize "$win" "$width" "$height" >/dev/null 2>&1
        [ -n "$x" ] && [ -n "$y" ] \
            && xdotool windowmove "$win" "$x" "$y" >/dev/null 2>&1
        sleep 0.7

        line=$(xdotool getwindowgeometry --shell "$win" 2>/dev/null) || return 1
        eval "$line"
        got_w="${WIDTH:-0}"; got_h="${HEIGHT:-0}"

        # Within a few pixels is fine: window managers round to increments.
        if [ "$(( got_w > width ? got_w - width : width - got_w ))" -le 8 ] \
           && [ "$(( got_h > height ? got_h - height : height - got_h ))" -le 8 ]; then
            note "window geometry set on attempt $attempt: ${got_w}x${got_h}+${X}+${Y}"
            return 0
        fi
        note "geometry attempt $attempt gave ${got_w}x${got_h}+${X}+${Y}, retrying"
    done

    warn "could not set the window to ${width}x${height}; it is ${got_w}x${got_h}. \
Coordinates calibrated for ${width}x${height} may not land correctly."
    return 1
}

#: WINDOW_GEOMETRY -> "WIDTHxHEIGHT+X+Y" as the X server currently sees it.
window_geometry() {
    local win="$1" line
    line=$(xdotool getwindowgeometry --shell "$win" 2>/dev/null) || return 1
    local X= Y= WIDTH= HEIGHT=
    eval "$line"
    printf '%sx%s+%s+%s' "$WIDTH" "$HEIGHT" "$X" "$Y"
}

#: The replacement for require_fullscreen(): the window must exist, be
#: focused, and be big enough that the results column is actually on
#: screen.  A 400x300 window would make every card coordinate meaningless,
#: so that is refused rather than clicked into.
: "${MIN_WINDOW_WIDTH:=900}"
: "${MIN_WINDOW_HEIGHT:=600}"
require_window_ready() {
    local win="$1"
    window_exists "$win" || fail "$EX_NO_WINDOW" "window $win no longer exists"
    require_focus "$win"

    local line X= Y= WIDTH= HEIGHT=
    line=$(xdotool getwindowgeometry --shell "$win" 2>/dev/null) \
        || fail "$EX_NO_WINDOW" "cannot read the geometry of window $win"
    eval "$line"

    if [ "${WIDTH:-0}" -lt "$MIN_WINDOW_WIDTH" ] \
       || [ "${HEIGHT:-0}" -lt "$MIN_WINDOW_HEIGHT" ]; then
        fail "$EX_WINDOW_GEOMETRY" \
            "the Firefox window is ${WIDTH}x${HEIGHT}, smaller than the \
${MIN_WINDOW_WIDTH}x${MIN_WINDOW_HEIGHT} minimum. Job-card coordinates are \
measured against a normal-sized window; clicking inside a window this small \
would select the wrong thing or nothing."
    fi
    return 0
}

# ---------------------------------------------------------------------------
# PAGE STATE WITHOUT THE CLIPBOARD
# ---------------------------------------------------------------------------
# The window TITLE is a free, instant, non-destructive read of what the page
# is.  Firefox puts the document title there, so a Cloudflare interstitial
# says "Just a moment...", a dead host says "Server not found", and a real
# Indeed results page says "<n> <keyword> jobs in <city>...".
#
# This is what replaced copying the whole listing page with Ctrl+A/Ctrl+C.
# That copy was only ever used to answer "did the page load, and is it a
# refusal?", and it answered it expensively: it depended on the clipboard
# changing, which is exactly the thing that failed in the field with
# "Ctrl+C did not change the clipboard".
title_says_access_denied() {
    printf '%s' "$1" | grep -qiE \
        "just a moment|access denied|forbidden|attention required|\
blocked|captcha|are you a robot|security check|unusual traffic|\
too many requests|rate limit|cloudflare"
}

title_says_error_page() {
    printf '%s' "$1" | grep -qiE \
        "server not found|problem loading|unable to connect|\
connection (timed out|reset|failure)|did not respond|page not found|\
not found|network protocol error|secure connection failed"
}

#: Poll the window title until it stops changing -- a page that is still
#: loading keeps retitling.  Returns the settled title.
wait_for_title_to_settle() {
    local win="$1" timeout="${2:-15}" previous="" current="" stable=0 waited=0
    while [ "$(printf '%.0f' "$waited")" -lt "$timeout" ]; do
        current=$(window_name "$win")
        if [ -n "$current" ] && [ "$current" = "$previous" ]; then
            stable=$((stable + 1))
            [ "$stable" -ge 2 ] && break
        else
            stable=0
        fi
        previous="$current"
        sleep 0.5
        waited=$(awk "BEGIN{print $waited + 0.5}")
    done
    printf '%s' "$current"
}

#: Poll the ADDRESS BAR until it matches an extended regex, or time out.
#: Uses the quiet read, so it never cancels a load in progress.
wait_for_url_match() {
    local win="$1" pattern="$2" timeout="${3:-20}" url="" waited=0
    while [ "$(printf '%.0f' "$waited")" -lt "$timeout" ]; do
        url=$(copy_address_bar_quiet "$win" 5) || url=""
        if [ -n "$url" ] && printf '%s' "$url" | grep -qE "$pattern"; then
            printf '%s' "$url"
            return 0
        fi
        sleep 1
        waited=$(awk "BEGIN{print $waited + 1}")
    done
    printf '%s' "$url"
    return 1
}

# ---------------------------------------------------------------------------
# CLIPBOARD
# ---------------------------------------------------------------------------
# Every read is NONCE-GUARDED.  The clipboard is first set to a unique
# string; the copy keystroke is sent; the clipboard is then polled until it
# differs from that string.  Without this, a Ctrl+C that silently did
# nothing returns the PREVIOUS job's text and one job's details are written
# under another job's name -- the single worst failure this project can have.
_clipboard_nonce() { printf 'ff-nonce-%s-%s-%s' "$$" "$(date +%s%N)" "$RANDOM"; }

_set_clipboard() { printf '%s' "$1" | xclip -selection clipboard -i >/dev/null 2>&1; }
_get_clipboard() { xclip -selection clipboard -o 2>/dev/null; }

#: _copy_with_nonce WINDOW TIMEOUT KEYS...  -> prints what was copied.
_copy_with_nonce() {
    local win="$1" timeout="$2"; shift 2
    local nonce current waited=0
    nonce=$(_clipboard_nonce)
    _set_clipboard "$nonce"
    xdotool windowactivate --sync "$win" >/dev/null 2>&1
    sleep 0.4
    # XTEST (no --window), deliberately.  MEASURED: `xdotool key --window
    # <id>` delivers a SYNTHETIC XSendEvent, and mixing synthetic key events
    # with XTEST ones left this Firefox in states its own address bar did
    # not agree with (a stray about:blank tab appeared mid-run).  Plain
    # XTEST into the window we just activated is what was observed to work
    # every time, so every keystroke in this project goes that way.
    local key
    for key in "$@"; do
        xdotool key --clearmodifiers "$key" >/dev/null 2>&1
        sleep 0.25
    done
    while [ "$(printf '%.0f' "$waited")" -lt "$timeout" ]; do
        current=$(_get_clipboard)
        if [ "$current" != "$nonce" ]; then
            printf '%s' "$current"
            [ -n "$current" ] && return 0
            return "$EX_CLIPBOARD_EMPTY"
        fi
        sleep "$POLL_INTERVAL"
        waited=$(awk "BEGIN{print $waited + $POLL_INTERVAL}")
    done
    return "$EX_CLIPBOARD_STALE"
}

#: The address bar, read by focusing it and copying.  Escape afterwards so
#: focus returns to the page and the next keystroke is not typed into the bar.
# MEASURED, AND THE CAUSE OF A LONG RUN OF "THE KEY DID NOTHING" FAILURES:
# Ctrl+L leaves the caret IN THE ADDRESS BAR, and Escape does not take it
# out again -- Escape only reverts the typed text.  Every page-level
# shortcut sent afterwards (F11, Ctrl+U, Ctrl+S) is then swallowed by the
# address bar and silently does nothing.  Observed repeatedly: F11 appeared
# dead until Escape+F6 preceded it, after which it worked every time.
#
# So reading the address bar ALWAYS hands focus back to the page.  Callers
# can send a page shortcut immediately after a read and have it arrive.
copy_address_bar() {
    local win="$1" timeout="${2:-$CLIPBOARD_TIMEOUT}" url=""
    url=$(_copy_with_nonce "$win" "$timeout" ctrl+l ctrl+a ctrl+c)
    local status=$?
    focus_page_content "$win"
    printf '%s' "$url"
    return $status
}

#: The same read WITHOUT the trailing Escape -- for use while a page is
#: still loading.
#:
#: MEASURED, AND IT COST AN HOUR: Escape in a browser means STOP LOADING.
#: copy_address_bar() ends with focus_page_content(), which presses Escape,
#: so polling with it in a wait loop CANCELS the very load being waited for.
#: Ctrl+U opens its view-source tab as about:blank and then loads the source
#: into it; polling with copy_address_bar() stopped that load on every pass,
#: and the tab sat at "view-source:about:blank" until the timeout expired.
#:
#: So: wait loops use this function, and only code that is about to send a
#: page-level shortcut uses copy_address_bar().
copy_address_bar_quiet() {
    local win="$1" timeout="${2:-$CLIPBOARD_TIMEOUT}"
    _copy_with_nonce "$win" "$timeout" ctrl+l ctrl+a ctrl+c
}

#: MEASURED: the FIRST clipboard read after a script boundary fails often
#: enough to matter.  In the live Ctrl+U test, search_jobs.sh read the url
#: fine, then select_job_card.sh's very first read came back empty, and a
#: read two seconds later worked.  The window needs a moment to actually
#: hold focus after `windowactivate`, and a single attempt lands inside
#: that window.
#:
#: This is the direct cause of the "<unreadable>" in the error the operator
#: reported.  One retry removes it; the retry count is a tunable rather
#: than a magic 2 because a loaded machine may need more.
: "${ADDRESS_BAR_ATTEMPTS:=3}"
copy_address_bar_retry() {
    local win="$1" timeout="${2:-$CLIPBOARD_TIMEOUT}" url="" attempt=0
    while [ "$attempt" -lt "$ADDRESS_BAR_ATTEMPTS" ]; do
        attempt=$((attempt + 1))
        url=$(copy_address_bar_quiet "$win" "$timeout")
        if [ -n "$url" ]; then
            [ "$attempt" -gt 1 ] && note "address bar read on attempt $attempt"
            printf '%s' "$url"
            return 0
        fi
        xdotool windowactivate --sync "$win" >/dev/null 2>&1
        sleep 0.8
    done
    return 1
}

#: All visible text on the page.
copy_page_text() {
    local win="$1" timeout="${2:-$CLIPBOARD_TIMEOUT}"
    _copy_with_nonce "$win" "$timeout" ctrl+a ctrl+c
}

# ---------------------------------------------------------------------------
# PAGE CLASSIFICATION
# ---------------------------------------------------------------------------
# An access refusal is NOT a transient error.  When one is seen the caller
# stops that unit of work and reports it.  Nothing in this project retries a
# refusal, rotates an identity, changes a user agent or cycles a session:
# the brief forbids it and so does ordinary decency toward the site.
looks_like_access_denied() {
    printf '%s' "$1" | grep -qiE \
        "access denied|forbidden|403 forbidden|you (have been|were) blocked|\
request (was )?blocked|unusual traffic|verify (you are|you're) (a )?human|\
are you a robot|captcha|cloudflare|just a moment|rate limit|too many requests|\
enable javascript and cookies|security check|suspicious activity|\
your request has been blocked"
}

looks_like_error_page() {
    printf '%s' "$1" | grep -qiE \
        "server not found|unable to connect|the connection (has timed out|was reset)|\
secure connection failed|file not found|problem loading page|\
this site can.t be reached|dns_probe|err_connection|err_name_not_resolved|\
your connection is not private|did not respond"
}

# ---------------------------------------------------------------------------
# FILES
# ---------------------------------------------------------------------------
#: Write via a temp file in the SAME directory, then rename.  A reader never
#: sees a half-written file, and a crash mid-write leaves the old one intact.
write_temp_atomic() {
    local target="$1" content="$2" dir tmp
    dir=$(dirname "$target")
    mkdir -p "$dir" || return 1
    tmp=$(mktemp "$dir/.tmp.XXXXXX") || return 1
    printf '%s' "$content" > "$tmp" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$target" || { rm -f "$tmp"; return 1; }
    return 0
}

#: FACT 2a: the snap cannot write outside $HOME.  Catch that here, with an
#: explanation, rather than letting Ctrl+S appear to succeed and produce no
#: file anybody can find.
require_saveable_path() {
    local path="$1" home_real target_real
    home_real=$(cd "$HOME" 2>/dev/null && pwd -P) || home_real="$HOME"
    target_real=$(cd "$(dirname "$path")" 2>/dev/null && pwd -P) || target_real=$(dirname "$path")
    case "$target_real/" in
        "$home_real"/*) return 0 ;;
    esac
    fail "$EX_USAGE" \
        "save path '$path' is outside \$HOME ($home_real). Firefox here is a \
snap with a private /tmp and a \$HOME-only file interface, so it cannot write \
there. Put Temp_Data under \$HOME."
}

# ---------------------------------------------------------------------------
# FIREFOX LAUNCH ENVIRONMENT  (FACTS 1 and 2b)
# ---------------------------------------------------------------------------
: "${FIREFOX_BIN:=firefox}"
: "${FIREFOX_SNAP_BINARY:=/snap/firefox/current/usr/lib/firefox/firefox}"
# auto | snap | direct
: "${FIREFOX_LAUNCH_MODE:=auto}"

#: An XAUTHORITY the snap can actually read.  The live one is usually
#: /run/user/1000/.mutter-Xwaylandauth.XXXXXX; a copy under $HOME is used
#: when the snap cannot read the original.
firefox_xauthority() {
    local copy="${FIREFOX_XAUTH_COPY:-}"
    [ -n "$copy" ] && [ -r "$copy" ] && { printf '%s' "$copy"; return 0; }
    printf '%s' "${XAUTHORITY:-}"
}

firefox_is_snap() {
    [ "$FIREFOX_LAUNCH_MODE" = "snap" ] && return 0
    [ "$FIREFOX_LAUNCH_MODE" = "direct" ] && return 1
    command -v snap >/dev/null 2>&1 \
        && snap list firefox >/dev/null 2>&1
}

#: The env every Firefox in this project is started with.  Exported into the
#: launching shell, so a `direct` launch inherits exactly what a snap launch
#: is given inside `snap run --shell`.
firefox_x11_env() {
    MOZ_ENABLE_WAYLAND=0
    GDK_BACKEND=x11
    MOZ_NO_REMOTE=1
    export MOZ_ENABLE_WAYLAND GDK_BACKEND MOZ_NO_REMOTE
    unset WAYLAND_DISPLAY
    XAUTHORITY=$(firefox_xauthority)
    export XAUTHORITY DISPLAY
}

# ---------------------------------------------------------------------------
# INPUT GUARD  (required on this desktop -- see FACT 4)
# ---------------------------------------------------------------------------
# FACT 4.  XTEST KEYSTROKES CAN LAND IN SOMEBODY ELSE'S WINDOW.
#
#   On this Wayland session, keyboard delivery is decided by the compositor,
#   not by the X focus.  Measured, and the reason this guard exists: a
#   Ctrl+L/Ctrl+A/Ctrl+C aimed at OUR Firefox returned the text
#   "jsw jetour t2 spy shots" -- content from the USER'S OWN browser.  X
#   reported our window as focused throughout, so no amount of reading
#   _NET_WM_STATE or _NET_ACTIVE_WINDOW would have caught it.
#
#   The only thing that actually proves input is reaching our window is a
#   ROUND TRIP: send a read-only key sequence and check that what comes back
#   is OUR page.  That is what assert_input_lands() does.
#
#   THE RULE THIS BUYS, AND IT IS NOT OPTIONAL:
#
#     * Read-only keys (Ctrl+L, Ctrl+A, Ctrl+C, Escape, F6) may be sent
#       unguarded.  If they land in the wrong window they select and copy;
#       they do not alter anything.
#
#     * ANYTHING THAT TYPES TEXT, PRESSES Return, SAVES, OR CLOSES must be
#       preceded by a successful assert_input_lands().  Typing a job title
#       into the user's email, or pressing Return in their banking tab, is
#       the failure this project must never cause.
#
#   When the guard fails the script STOPS.  It does not retry blindly and it
#   does not "try anyway": there is nowhere safe to send the keystroke.
assert_input_lands() {
    local win="$1" expect="$2"

    # NOTE THE SHAPE, AND WHY.  This used to be called as
    #     URL=$(assert_input_lands "$win" "")
    # and it called fail() on a bad read.  fail() ends with `exit`, and an
    # `exit` inside $( ) ends only the SUBSHELL -- so the script carried on
    # with the error MESSAGE as its url and exited 0.  Observed live: the
    # guard printed "REFUSING to type", and the script then went ahead and
    # clicked anyway.  A guard that does not guard is worse than none.
    #
    # So it sets GUARD_URL and returns a status; the CALLER decides, at top
    # level, where fail() really does end the script:
    #
    #     assert_input_lands "$win" "" || fail "$EX_FOCUS" "..."
    #     URL_BEFORE="$GUARD_URL"
    GUARD_URL=""
    GUARD_REASON=""

    GUARD_URL=$(copy_address_bar_retry "$win" "$CLIPBOARD_TIMEOUT") || GUARD_URL=""

    if [ -z "$GUARD_URL" ]; then
        GUARD_REASON="could not read the address bar after \
${ADDRESS_BAR_ATTEMPTS} attempts, so there is no proof that keystrokes are \
reaching window $win"
        return 1
    fi

    # Every caller of this guard goes on to click or type into the PAGE,
    # and the read above left the suggestion panel covering it.
    dismiss_url_dropdown

    if [ -n "$expect" ]; then
        case "$GUARD_URL" in
            *"$expect"*) : ;;
            *)
                GUARD_REASON="expected the focused page to contain '$expect' \
but the address bar returned '$GUARD_URL'; keystrokes are NOT going to our \
Firefox window"
                return 1 ;;
        esac
    fi
    return 0
}
