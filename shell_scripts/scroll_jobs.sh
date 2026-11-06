#!/usr/bin/env bash
# Scroll the job-LISTING panel, and report whether there is more to read.
# Brief section 20.
#
# WHAT MAKES THIS DIFFERENT FROM THE COLLEGE SCRIPT
# -------------------------------------------------
#   college:  while [ $count -lt 1000 ]; do xdotool key Down; done
#             -- 1000 presses, 200 ms apart: three and a half minutes of
#             keystrokes whether the page is one screen long or fifty, with
#             no idea whether anything moved.
#
#   here:     one bounded step at a time, and after each step the page text
#             is re-copied and compared.  When the text stops changing the
#             page is at its end, and the script says so and stops.  It also
#             reports how many job-card markers it can see, which is what
#             Python uses to decide whether another page is worth asking for.
#
# "Distinguish the job-listing panel from the job-description panel."
#   Indeed's results page is two panels: a scrollable list on the left and a
#   preview on the right.  Which one the mouse wheel moves depends on where
#   the pointer is, which is unknowable without coordinates.  So this script
#   scrolls with the KEYBOARD (Page_Down on the focused document), and
#   --target controls what gets focused first:
#       list     (default) focus the page body from the top, so Page_Down
#                moves the document -- the list -- and not the preview.
#       pointer  move the pointer to an explicit --x/--y first, for the
#                case where a panel only responds to the wheel.  No default
#                coordinate: it must be supplied.
#
# USAGE
#   scroll_jobs.sh --window WID [--steps 6] [--target list|pointer]
#                  [--x N --y N] [--out-text PATH] [--card-marker REGEX]
#
# STDOUT
#   RESULT:steps_taken=N
#   RESULT:reached_end=yes|no
#   RESULT:chars=N
#   RESULT:card_markers=N
#   RESULT:text_file=PATH

SCRIPT_NAME="scroll_jobs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
STEPS="6"
TARGET="list"
POINTER_X=""
POINTER_Y=""
OUT_TEXT=""
CARD_MARKER='^[[:space:]]*(Easily apply|Apply now|[0-9]+ days? ago|Just posted|Active [0-9]+ days? ago)[[:space:]]*$'

while [ $# -gt 0 ]; do
    case "$1" in
        --window)      WINDOW_ID="$2";  shift 2 ;;
        --steps)       STEPS="$2";      shift 2 ;;
        --target)      TARGET="$2";     shift 2 ;;
        --x)           POINTER_X="$2";  shift 2 ;;
        --y)           POINTER_Y="$2";  shift 2 ;;
        --out-text)    OUT_TEXT="$2";   shift 2 ;;
        --card-marker) CARD_MARKER="$2"; shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" "window $WINDOW_ID is gone"

require_focus "$WINDOW_ID"
require_window_ready "$WINDOW_ID"

case "$TARGET" in
list)
    xdotool key --clearmodifiers Escape >/dev/null 2>&1; sleep 0.2
    xdotool key --clearmodifiers F6 >/dev/null 2>&1; sleep 0.25
    note "scrolling the focused document with Page_Down (the listing panel)"
    ;;
pointer)
    [ -n "$POINTER_X" ] && [ -n "$POINTER_Y" ] \
        || fail "$EX_USAGE" "--target pointer needs --x and --y; no coordinate is defaulted"
    xdotool mousemove --window "$WINDOW_ID" "$POINTER_X" "$POINTER_Y" >/dev/null 2>&1
    note "scrolling under the pointer at ($POINTER_X,$POINTER_Y)"
    ;;
*)
    fail "$EX_USAGE" "--target must be 'list' or 'pointer'" ;;
esac

fingerprint_of() {
    # A cheap, order-sensitive signature of the copied text.  cksum rather
    # than a hash tool so there is no extra dependency.
    printf '%s' "$1" | cksum | tr -d ' '
}

PREVIOUS=""
TAKEN=0
REACHED_END="no"
TEXT=""

for ((s = 0; s < STEPS; s++)); do
    if [ "$TARGET" = "pointer" ]; then
        xdotool click --clearmodifiers 5 >/dev/null 2>&1   # wheel down
        xdotool click --clearmodifiers 5 >/dev/null 2>&1
    else
        xdotool key --clearmodifiers Page_Down >/dev/null 2>&1
    fi
    TAKEN=$((TAKEN + 1))
    sleep 0.6

    TEXT=$(copy_page_text "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || TEXT=""
    if [ -z "$TEXT" ]; then
        warn "step $TAKEN: the page copied as empty -- stopping the scroll"
        break
    fi
    CURRENT=$(fingerprint_of "$TEXT")
    if [ "$CURRENT" = "$PREVIOUS" ]; then
        # The whole-document copy stopped changing: nothing more is loading.
        REACHED_END="yes"
        note "step $TAKEN: the page text stopped changing -- end of this results page"
        break
    fi
    PREVIOUS="$CURRENT"
done

emit "steps_taken=$TAKEN"
emit "reached_end=$REACHED_END"
emit "chars=${#TEXT}"

MARKERS=0
if [ -n "$TEXT" ]; then
    MARKERS=$(printf '%s\n' "$TEXT" | grep -ciE -- "$CARD_MARKER" || true)
fi
emit "card_markers=$MARKERS"
note "visible job-card markers: $MARKERS"

if [ -n "$OUT_TEXT" ] && [ -n "$TEXT" ]; then
    write_temp_atomic "$OUT_TEXT" "$TEXT" || warn "could not write $OUT_TEXT"
    emit "text_file=$OUT_TEXT"
fi

# Leave the document back at the top so the next Tab traversal starts from a
# known place.  Without this, card N after a scroll is not card N before it.
xdotool key --clearmodifiers ctrl+Home >/dev/null 2>&1
sleep 0.3

exit "$EX_OK"
