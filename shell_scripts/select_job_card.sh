#!/usr/bin/env bash
# Select one job card on the results page with the mouse, then PROVE which
# job is now showing.
#
# USAGE
#   select_job_card.sh --window WID --index N
#                      [--card-x PX] [--first-card-y PX] [--card-pitch PX]
#                      [--expect-title TEXT] [--marker vjk=]
#                      [--temp-file PATH]
#
# STDOUT
#   RESULT:index=N
#   RESULT:clicked_at=X,Y
#   RESULT:url_before=...
#   RESULT:selected_url=...
#   RESULT:selected_key=<the vjk/jk value, when the url carries one>
#   RESULT:selection_changed=yes|no
#   RESULT:title_confirmed=yes|no|not_checked
#   RESULT:detail_text_file=PATH       (when --temp-file was given)
#
# WHY A CLICK AND NOT Tab-Tab-Return
# ----------------------------------
# Tab order on a results page runs through the header, the filter chips and
# every card's "save" and "apply" control before it reaches the next card,
# and it changes whenever the page's furniture changes.  Counting tabs is
# therefore a guess that fails silently on the wrong element.  A click at a
# position in the results column is a guess too -- but it is a guess that
# can be CHECKED afterwards, because selecting a card changes the url, and
# that is what the rest of this script does.
#
# THE CHECK IS THE POINT.  A card that was not really selected means the
# next Ctrl+U saves the PREVIOUS job's source under the new job's name, and
# one job's details are written under another job's identity.  That is the
# worst thing this project can do, so a selection that cannot be confirmed
# is a hard failure, never a warning.

SCRIPT_NAME="select_job_card"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
INDEX=""
EXPECT_TITLE=""
TEMP_FILE=""
MARKER="${CARD_MARKER:-vjk=}"

# Geometry of the results column.  These are the one set of numbers in this
# project that depend on how the page happens to be laid out, so they are
# arguments with overridable defaults rather than constants, and the script
# reports exactly where it clicked so a wrong value is visible immediately.
: "${CARD_X:=430}"
: "${FIRST_CARD_Y:=300}"
: "${CARD_PITCH:=148}"
: "${CARD_MAX_Y:=980}"

while [ $# -gt 0 ]; do
    case "$1" in
        --window)        WINDOW_ID="$2";    shift 2 ;;
        --index)         INDEX="$2";        shift 2 ;;
        --card-x)        CARD_X="$2";       shift 2 ;;
        --first-card-y)  FIRST_CARD_Y="$2"; shift 2 ;;
        --card-pitch)    CARD_PITCH="$2";   shift 2 ;;
        --max-y)         CARD_MAX_Y="$2";   shift 2 ;;
        --expect-title)  EXPECT_TITLE="$2"; shift 2 ;;
        --marker)        MARKER="$2";       shift 2 ;;
        --temp-file)     TEMP_FILE="$2";    shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"
[ -n "$INDEX" ]     || fail "$EX_USAGE" "--index is required"
case "$INDEX" in ''|*[!0-9]*) fail "$EX_USAGE" "--index must be a number, got '$INDEX'" ;; esac

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" "window $WINDOW_ID no longer exists"

require_focus "$WINDOW_ID"
require_fullscreen "$WINDOW_ID"

emit "index=$INDEX"

# ---------------------------------------------------------------------------
# 1. WHERE ARE WE NOW?  (also the input guard -- a click is an action)
# ---------------------------------------------------------------------------
URL_BEFORE=$(assert_input_lands "$WINDOW_ID" "")
emit "url_before=$URL_BEFORE"
note "before selection: $URL_BEFORE"

KEY_BEFORE=""
case "$URL_BEFORE" in
    *"$MARKER"*) KEY_BEFORE="${URL_BEFORE##*$MARKER}"; KEY_BEFORE="${KEY_BEFORE%%&*}" ;;
esac

# ---------------------------------------------------------------------------
# 2. CLICK THE CARD
# ---------------------------------------------------------------------------
TARGET_Y=$(( FIRST_CARD_Y + INDEX * CARD_PITCH ))

if [ "$TARGET_Y" -gt "$CARD_MAX_Y" ]; then
    fail "$EX_USAGE" \
        "card $INDEX would be at y=$TARGET_Y, past the bottom of the results \
column (max $CARD_MAX_Y). Scroll the list with scroll_jobs.sh and select \
with a smaller index, rather than clicking off-screen."
fi

note "clicking card $INDEX at ${CARD_X},${TARGET_Y}"
emit "clicked_at=${CARD_X},${TARGET_Y}"
xdotool mousemove --sync "$CARD_X" "$TARGET_Y" >/dev/null 2>&1
sleep 0.3
xdotool click 1 >/dev/null 2>&1
sleep "$PAGE_SETTLE_SECONDS"

# ---------------------------------------------------------------------------
# 3. PROVE SOMETHING WAS SELECTED
# ---------------------------------------------------------------------------
URL_AFTER=$(copy_address_bar "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || URL_AFTER=""
[ -n "$URL_AFTER" ] || fail "$EX_IDENTITY" \
    "could not read the address bar after clicking, so there is no proof of \
which job is selected. Refusing to continue."
emit "selected_url=$URL_AFTER"
note "after selection: $URL_AFTER"

KEY_AFTER=""
case "$URL_AFTER" in
    *"$MARKER"*) KEY_AFTER="${URL_AFTER##*$MARKER}"; KEY_AFTER="${KEY_AFTER%%&*}" ;;
esac
emit "selected_key=$KEY_AFTER"

CHANGED="no"
[ "$URL_BEFORE" != "$URL_AFTER" ] && CHANGED="yes"
emit "selection_changed=$CHANGED"

if [ -z "$KEY_AFTER" ] && [ "$CHANGED" != "yes" ]; then
    fail "$EX_IDENTITY" \
        "the click at ${CARD_X},${TARGET_Y} changed nothing: the url is still \
'$URL_AFTER' and carries no '$MARKER'. Either the click missed the card \
column (adjust --card-x / --first-card-y / --card-pitch) or there is no \
card $INDEX on this page."
fi

if [ -n "$KEY_BEFORE" ] && [ "$KEY_BEFORE" = "$KEY_AFTER" ]; then
    fail "$EX_IDENTITY" \
        "card $INDEX resolves to the SAME job as the previous selection \
($MARKER$KEY_AFTER). Saving its source now would write one job's details \
twice. Check --card-pitch: the click probably landed on the same card."
fi

# ---------------------------------------------------------------------------
# 4. CONFIRM THE JOB'S IDENTITY ON THE PAGE
# ---------------------------------------------------------------------------
TITLE_CONFIRMED="not_checked"
if [ -n "$EXPECT_TITLE" ] || [ -n "$TEMP_FILE" ]; then
    DETAIL_TEXT=$(copy_page_text "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || DETAIL_TEXT=""

    if [ -n "$DETAIL_TEXT" ] && looks_like_access_denied "$DETAIL_TEXT"; then
        emit "access_denied=yes"
        fail "$EX_ACCESS_DENIED" \
            "the job detail pane is an access refusal. Stopping; no retry, no identity change."
    fi

    if [ -n "$TEMP_FILE" ] && [ -n "$DETAIL_TEXT" ]; then
        write_temp_atomic "$TEMP_FILE" "$DETAIL_TEXT" \
            && emit "detail_text_file=$TEMP_FILE"
    fi

    if [ -n "$EXPECT_TITLE" ]; then
        if printf '%s' "$DETAIL_TEXT" | grep -qiF -- "$EXPECT_TITLE"; then
            TITLE_CONFIRMED="yes"
        else
            TITLE_CONFIRMED="no"
        fi
    fi
fi
emit "title_confirmed=$TITLE_CONFIRMED"

if [ "$TITLE_CONFIRMED" = "no" ]; then
    fail "$EX_IDENTITY" \
        "the selected job's page does not contain the expected title \
'$EXPECT_TITLE'. The wrong card is open; refusing to save its source under \
that job's name."
fi

note "card $INDEX selected and confirmed"
exit "$EX_OK"
