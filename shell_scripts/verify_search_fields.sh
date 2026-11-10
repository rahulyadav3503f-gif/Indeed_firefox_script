#!/usr/bin/env bash
# FIND Indeed's two search boxes and prove they work -- WITHOUT searching.
#
# USAGE
#   verify_search_fields.sh --window WID [--what-xy X,Y] [--where-xy X,Y]
#                           [--probe TEXT] [--no-scan]
#                           [--scan-step N] [--scan-reach N]
#                           [--probe-limit N]
#
# STDOUT
#   RESULT:what_ok=yes|no
#   RESULT:where_ok=yes|no
#   RESULT:learned_what_xy=X,Y      <- USE THESE for the real search
#   RESULT:learned_where_xy=X,Y
#   RESULT:what_read=<preview, never raw page text>
#   RESULT:where_read=<preview>
#   RESULT:probes=N
#   RESULT:scan_floor=Y
#   RESULT:url=<address bar>
#   RESULT:title=<window title>
#   RESULT:verified=yes|no
#
# WHY THIS EXISTS, AND WHY IT NOW SEARCHES FOR THE BOXES
# ------------------------------------------------------
# The collector restarts Firefox between keywords. The next thing it does is
# click where the search boxes should be and type a real keyword. A click
# that misses the input types the keyword into nothing, and the Return that
# follows is delivered to whatever has focus -- which once sent a run to
# youtube.com.
#
# A FIXED COORDINATE CANNOT CARRY THAT WEIGHT. Measured on 2026-11-10,
# three things moved it independently:
#
#   * The window manager placed the window at +70+27 when it was asked for
#     +0+34, and the geometry it reports is the FRAME, so the page content
#     starts a title-bar lower than the arithmetic assumes.
#   * Indeed's home page is a DIFFERENT PAGE when signed in: "Welcome,
#     rohan", a "Jobs for you" feed and an open job pane, with the search
#     row in a different place from the signed-out hero layout the
#     coordinates were measured on.
#   * The hero area keeps laying out after the page reports loaded.
#
# The result was a click 30-odd pixels high, into the header strip above
# the box -- and search_jobs.sh reporting "the keyword box holds <4KB of
# Indeed's home page>", twice, forever.
#
# So this script does what select_job_card.sh already does for job cards:
# it PROBES and it LEARNS. The given coordinates are tried first, then
# nearby rows, nearest first. What worked is reported, and the caller uses
# those numbers for the real search. The same idiom, for the same reason:
# a measured position beats a remembered one.
#
# WHAT IT DOES NOT DO
# -------------------
# It never presses Return, and it never leaves the probe behind: every box
# it touches is cleared. Nothing is searched and nothing is submitted. The
# probe is deliberately not a job keyword -- nothing it types could be
# mistaken for a real search.

SCRIPT_NAME="verify_search_fields"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
PROBE="zz"
SCAN=yes

# How far from the given row to look, and in what increments.  The measured
# error was ~30px; a reach of 120 covers four times that.
: "${FIELD_SCAN_STEP:=20}"
: "${FIELD_SCAN_REACH:=120}"
#: Sideways candidates, used only if every row failed at the given x.
: "${FIELD_SCAN_X_OFFSETS:=0 -80 80 -160 160}"
#: Total probes allowed, so a page with no search form cannot scan forever.
: "${FIELD_PROBE_LIMIT:=26}"

# Every settle in a probe goes through pause(), scaled by this. It exists
# for ONE reason: tests/test_field_scan.py runs this script for real against
# a simulated browser, and at full speed a 26-probe scan takes a minute.
# Live runs leave it at 1 and nothing about the timing changes.
: "${FIELD_PROBE_PAUSE_SCALE:=1}"

pause() {
    local seconds
    seconds=$(awk "BEGIN{printf \"%.3f\", $1 * $FIELD_PROBE_PAUSE_SCALE}")
    case "$seconds" in 0.000) return 0 ;; esac
    sleep "$seconds"
}

# NEVER PROBE INTO FIREFOX'S OWN CHROME.
#
# This is a safety floor, not a tuning knob. A probe that lands in the
# ADDRESS BAR types the probe, reads the probe back, and looks exactly like
# success -- so the script would "learn" the address bar as the keyword box.
# The real search would then type "Product Consultant" into the address bar
# and press Return, navigating to it as a url. The floor keeps every probe
# below the tab strip and address bar, where only page content lives.
: "${MIN_PAGE_Y_OFFSET:=120}"

: "${SEARCH_WHAT_X:=700}"
: "${SEARCH_WHAT_Y:=240}"
: "${SEARCH_WHERE_X:=1100}"
: "${SEARCH_WHERE_Y:=240}"

while [ $# -gt 0 ]; do
    case "$1" in
        --window)      WINDOW_ID="$2"; shift 2 ;;
        --probe)       PROBE="$2";     shift 2 ;;
        --no-scan)     SCAN=no;        shift ;;
        --scan-step)   FIELD_SCAN_STEP="$2";  shift 2 ;;
        --scan-reach)  FIELD_SCAN_REACH="$2"; shift 2 ;;
        --probe-limit) FIELD_PROBE_LIMIT="$2"; shift 2 ;;
        --what-xy)   SEARCH_WHAT_X="${2%%,*}";  SEARCH_WHAT_Y="${2##*,}";  shift 2 ;;
        --where-xy)  SEARCH_WHERE_X="${2%%,*}"; SEARCH_WHERE_Y="${2##*,}"; shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"
[ -n "$PROBE" ]     || fail "$EX_USAGE" "--probe must not be empty"
case "$PROBE" in
    *" "*|*"
"*) fail "$EX_USAGE" "--probe must be a single word: it is compared against \
a field read-back, and whitespace would make that comparison unreliable" ;;
esac

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" \
    "window $WINDOW_ID no longer exists -- Firefox may have been closed."
require_window_ready "$WINDOW_ID"

# ---------------------------------------------------------------------------
# WHERE IS THE WINDOW, REALLY
# ---------------------------------------------------------------------------
# Asked from the window itself rather than taken from the caller: the whole
# failure this script exists to fix came from arithmetic about where the
# window was supposed to be.
WIN_GEOM=$(xdotool getwindowgeometry --shell "$WINDOW_ID" 2>/dev/null)
WIN_X=$(printf '%s\n' "$WIN_GEOM" | sed -n 's/^X=//p' | tail -1)
WIN_Y=$(printf '%s\n' "$WIN_GEOM" | sed -n 's/^Y=//p' | tail -1)
WIN_H=$(printf '%s\n' "$WIN_GEOM" | sed -n 's/^HEIGHT=//p' | tail -1)
: "${WIN_X:=0}"; : "${WIN_Y:=0}"; : "${WIN_H:=1000}"

SCAN_FLOOR=$((WIN_Y + MIN_PAGE_Y_OFFSET))
SCAN_CEIL=$((WIN_Y + WIN_H - 40))
emit "scan_floor=$SCAN_FLOOR"
note "window at +${WIN_X}+${WIN_Y} ${WIN_H}px tall; probes stay between \
y=$SCAN_FLOOR and y=$SCAN_CEIL (never in Firefox's own chrome)"

# The same guard every typing action in this project runs first: on Wayland
# the compositor decides who gets the keys (FACT 4 in _common.sh).
assert_input_lands "$WINDOW_ID" "" \
    || fail "$EX_FOCUS" "input guard: $GUARD_REASON. REFUSING to type."
emit "url=$GUARD_URL"
note "input guard passed; address bar reads: $GUARD_URL"

PAGE_TITLE=$(window_name "$WINDOW_ID")
emit "title=$PAGE_TITLE"
if title_says_access_denied "$PAGE_TITLE"; then
    fail "$EX_ACCESS_DENIED" \
        "the page is an access refusal (title: '$PAGE_TITLE'). Stopping. \
No retry, no identity change, no session cycling."
fi

note "waiting ${SEARCH_FIELD_DELAY_SECONDS}s for the page to settle"
sleep "$SEARCH_FIELD_DELAY_SECONDS"

# ---------------------------------------------------------------------------
# ONE PROBE
# ---------------------------------------------------------------------------
PROBES=0
PROBE_READ=""

#: probe_at X Y LABEL -- type the probe there, read it back, clear up.
#: Sets PROBE_READ.  Returns 0 only when the box gave the probe back.
probe_at() {
    local x="$1" y="$2" label="$3"
    PROBE_READ=""

    if [ "$y" -lt "$SCAN_FLOOR" ] || [ "$y" -gt "$SCAN_CEIL" ]; then
        note "refusing to probe at ${x},${y}: outside the page area"
        return 1
    fi
    if [ "$PROBES" -ge "$FIELD_PROBE_LIMIT" ]; then
        return 1
    fi
    PROBES=$((PROBES + 1))

    # The address-bar panel covers the page and would swallow the click --
    # see dismiss_url_dropdown() in _common.sh for what that once cost.
    dismiss_url_dropdown
    xdotool mousemove --sync "$x" "$y" >/dev/null 2>&1
    pause 0.3
    xdotool click 1 >/dev/null 2>&1
    pause 0.5

    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; pause 0.2
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$PROBE"
    pause 0.4
    # Shut the suggestion dropdown so it cannot swallow the next click.
    xdotool key --clearmodifiers Escape >/dev/null 2>&1
    pause 0.25

    PROBE_READ=$(_copy_with_nonce "$WINDOW_ID" 6 ctrl+a ctrl+c) || PROBE_READ=""

    # LEAVE NOTHING BEHIND.  Whatever this click hit, it must not still hold
    # the probe when the real keyword is typed.  Only clear when we are in a
    # field: Ctrl+A/Delete with focus on the DOCUMENT does nothing useful
    # and Delete there is a page shortcut, not an edit.
    if is_field_value "$PROBE_READ" && [ -n "$PROBE_READ" ]; then
        xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; pause 0.15
        xdotool key --clearmodifiers Delete  >/dev/null 2>&1; pause 0.15
    fi
    xdotool key --clearmodifiers Escape >/dev/null 2>&1; pause 0.15

    if [ "$PROBE_READ" = "$PROBE" ]; then
        note "  probe $PROBES at ${x},${y}: the $label box answered"
        return 0
    fi
    note "  probe $PROBES at ${x},${y}: not the $label box ($(field_preview "$PROBE_READ" 40))"
    return 1
}

# ---------------------------------------------------------------------------
# FIND ONE FIELD
# ---------------------------------------------------------------------------
FOUND_X=0
FOUND_Y=0
LAST_READ=""

#: The rows to try, NEAREST FIRST: the given y, then +-step, +-2*step ...
#: Nearest-first matters: the common case is a small offset, and it is then
#: resolved in two or three probes rather than a full sweep.
scan_rows() {
    local y="$1" step="$2" reach="$3" delta=0
    printf '%s\n' "$y"
    while [ "$delta" -lt "$reach" ]; do
        delta=$((delta + step))
        printf '%s\n%s\n' "$((y - delta))" "$((y + delta))"
    done
}

#: find_field LABEL X Y -- sets FOUND_X/FOUND_Y.  Returns 0 when found.
find_field() {
    local label="$1" x="$2" y="$3" row="" dx=""

    if probe_at "$x" "$y" "$label"; then
        FOUND_X="$x"; FOUND_Y="$y"; LAST_READ="$PROBE_READ"; return 0
    fi
    LAST_READ="$PROBE_READ"
    if [ "$SCAN" != yes ]; then
        return 1
    fi

    note "scanning for the $label box around ${x},${y} (+-${FIELD_SCAN_REACH}px)"
    for row in $(scan_rows "$y" "$FIELD_SCAN_STEP" "$FIELD_SCAN_REACH"); do
        [ "$row" = "$y" ] && continue                 # already tried
        if probe_at "$x" "$row" "$label"; then
            FOUND_X="$x"; FOUND_Y="$row"; LAST_READ="$PROBE_READ"; return 0
        fi
    done

    # Every row failed at this x, so the error may be sideways instead.
    for dx in $FIELD_SCAN_X_OFFSETS; do
        [ "$dx" = "0" ] && continue
        if probe_at "$((x + dx))" "$y" "$label"; then
            FOUND_X="$((x + dx))"; FOUND_Y="$y"; LAST_READ="$PROBE_READ"
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# THE KEYWORD BOX, THEN THE LOCATION BOX
# ---------------------------------------------------------------------------
WHAT_OK=no; WHERE_OK=no
WHAT_READ=""; WHERE_READ=""
LEARNED_WHAT=""; LEARNED_WHERE=""

if find_field "keyword" "$SEARCH_WHAT_X" "$SEARCH_WHAT_Y"; then
    WHAT_OK=yes
    LEARNED_WHAT="$FOUND_X,$FOUND_Y"
    WHAT_READ="$PROBE"
else
    WHAT_READ="$LAST_READ"
fi
emit "what_ok=$WHAT_OK"
emit "what_read=$(field_preview "$WHAT_READ" 50)"
[ -n "$LEARNED_WHAT" ] && emit "learned_what_xy=$LEARNED_WHAT"

# The two boxes sit on ONE ROW, so the keyword box's learned y is the best
# first guess for the location box -- which usually makes this a single probe.
WHERE_Y_GUESS="$SEARCH_WHERE_Y"
if [ "$WHAT_OK" = yes ]; then
    WHERE_Y_GUESS="$FOUND_Y"
fi
if find_field "location" "$SEARCH_WHERE_X" "$WHERE_Y_GUESS"; then
    WHERE_OK=yes
    LEARNED_WHERE="$FOUND_X,$FOUND_Y"
    WHERE_READ="$PROBE"
else
    WHERE_READ="$LAST_READ"
fi
emit "where_ok=$WHERE_OK"
emit "where_read=$(field_preview "$WHERE_READ" 50)"
[ -n "$LEARNED_WHERE" ] && emit "learned_where_xy=$LEARNED_WHERE"
emit "probes=$PROBES"

if [ "$WHAT_OK" = yes ] && [ "$WHERE_OK" = yes ]; then
    emit "verified=yes"
    note "both search boxes found and answered: keyword at $LEARNED_WHAT, \
location at $LEARNED_WHERE (after $PROBES probe(s))"
    exit "$EX_OK"
fi

emit "verified=no"
# THREE DIFFERENT FAULTS, AND THE MESSAGE HAS TO SAY WHICH.
#
#   nothing read back  -> the keystrokes are not reaching our window at all
#   page text read back-> the click landed on the document, not an input
#   something else     -> it landed in some other field
#
# What it must NOT do is paste the page into the log. field_preview() keeps
# that to one line; the old message printed four kilobytes of Indeed, twice.
DIAGNOSIS="the boxes could not be found within ${FIELD_SCAN_REACH}px of the \
coordinates given, after $PROBES probe(s)"
if [ -z "$WHAT_READ$WHERE_READ" ]; then
    DIAGNOSIS="nothing was read back at all -- the keystrokes are not \
reaching our Firefox window, or the page has not laid out yet"
elif ! is_field_value "$WHAT_READ" || ! is_field_value "$WHERE_READ"; then
    DIAGNOSIS="every click landed on the page body rather than an input \
(a body copy returns the whole page), so the search row is not within \
${FIELD_SCAN_REACH}px of ${SEARCH_WHAT_X},${SEARCH_WHAT_Y} -- note that \
Indeed's home page has a DIFFERENT layout when signed in"
fi
fail "$EX_NAVIGATION" \
    "search fields NOT verified: keyword box $([ "$WHAT_OK" = yes ] \
&& printf 'found at %s' "$LEARNED_WHAT" || printf 'not found, returned %s' \
"$(field_preview "$WHAT_READ" 50)"), location box $([ "$WHERE_OK" = yes ] \
&& printf 'found at %s' "$LEARNED_WHERE" || printf 'not found, returned %s' \
"$(field_preview "$WHERE_READ" 50)"). $DIAGNOSIS. Nothing was searched."
