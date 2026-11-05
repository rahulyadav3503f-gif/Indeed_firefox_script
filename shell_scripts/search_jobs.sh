#!/usr/bin/env bash
# Run one keyword + city search in an already-verified Firefox window.
#
# The keyword and the city are ARGUMENTS.  There is no role list and no city
# list in this file, or in any other shell script in this project: Python
# owns the plan (target_audience_roles.build_role_plan and
# new_mylib.city_by_states), the shell owns the keystrokes.  The user never
# types either value.
#
# USAGE
#   search_jobs.sh --window WID --keyword "Azure Administrator" --city "Pune"
#                  [--base-url https://in.indeed.com] [--mode url|form]
#                  [--temp-file PATH] [--start N]
#
# TWO MODES
#   url   (default) Put the search into the address bar.  q= and l= are the
#                   exact parameters Indeed's own form submits, so this is
#                   the same search, reached through the browser, without
#                   guessing where the two boxes sit on the page today.
#   form            Drive the on-page form: focus the keyword box, type,
#                   Tab to the location box, type, Return.  Kept because the
#                   brief asks for it and because it is what a person does.
#                   It depends on the page's tab order, which is why it is
#                   not the default.
#
# BOTH MODES TYPE.  So both are preceded by the input guard: if keystrokes
# are not provably reaching our window, nothing is typed at all.
#
# STDOUT
#   RESULT:search_url=...
#   RESULT:url=<address bar after the search>
#   RESULT:verified=yes|no
#   RESULT:access_denied=yes|no
#   RESULT:listing_text_file=PATH      (when --temp-file was given)
#   RESULT:listing_chars=N

SCRIPT_NAME="search_jobs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
KEYWORD=""
CITY=""
BASE_URL="https://in.indeed.com"
TEMP_FILE=""
MODE="url"
START_AT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --window)    WINDOW_ID="$2"; shift 2 ;;
        --keyword)   KEYWORD="$2";   shift 2 ;;
        --city)      CITY="$2";      shift 2 ;;
        --base-url)  BASE_URL="$2";  shift 2 ;;
        --temp-file) TEMP_FILE="$2"; shift 2 ;;
        --mode)      MODE="$2";      shift 2 ;;
        --start)     START_AT="$2";  shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"
[ -n "$KEYWORD" ]   || fail "$EX_USAGE" "--keyword is required (Python owns the role plan)"
[ -n "$CITY" ]      || fail "$EX_USAGE" "--city is required (Python owns the city list)"

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" \
    "window $WINDOW_ID no longer exists -- Firefox may have been closed."

# Fullscreen is re-verified at the start of every search: it is required for
# the WHOLE workflow, not just at launch.
require_focus "$WINDOW_ID"
require_fullscreen "$WINDOW_ID"

# ---------------------------------------------------------------------------
# percent-encode for the query string
# ---------------------------------------------------------------------------
urlencode() {
    local text="$1" out="" i char
    for ((i = 0; i < ${#text}; i++)); do
        char="${text:i:1}"
        case "$char" in
            [a-zA-Z0-9.~_-]) out+="$char" ;;
            ' ')             out+="%20" ;;
            *)               out+=$(printf '%%%02X' "'$char") ;;
        esac
    done
    printf '%s' "$out"
}

SEARCH_URL="${BASE_URL%/}/jobs?q=$(urlencode "$KEYWORD")&l=$(urlencode "$CITY")"
[ -n "$START_AT" ] && [ "$START_AT" != "0" ] && SEARCH_URL+="&start=$START_AT"
emit "search_url=$SEARCH_URL"

# ---------------------------------------------------------------------------
# INPUT GUARD -- before a single character is typed
# ---------------------------------------------------------------------------
# Everything below this line types.  See FACT 4 in _common.sh: on this
# desktop a keystroke can be delivered to one of the user's own windows, and
# typing a job title into somebody's email is not an acceptable failure.
HOST_PART="${BASE_URL#*://}"; HOST_PART="${HOST_PART%%/*}"
BEFORE_URL=$(assert_input_lands "$WINDOW_ID" "")
note "input guard passed; address bar currently reads: $BEFORE_URL"

case "$MODE" in
url)
    note "address-bar search: $SEARCH_URL"
    xdotool key --clearmodifiers Escape >/dev/null 2>&1; sleep 0.2
    xdotool key --clearmodifiers ctrl+l >/dev/null 2>&1; sleep 0.5
    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; sleep 0.2
    # --clearmodifiers so a held Shift from an earlier key cannot corrupt it.
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$SEARCH_URL"
    sleep 0.5
    xdotool key --clearmodifiers Return >/dev/null 2>&1
    ;;
form)
    # Indeed's keyword box is the first text input in the search form and
    # the location box is the next focusable field.  KEYWORD_FIELD_TABS is
    # configurable because the number of focusable items before the keyword
    # box is a property of the page, not a constant we may assume.
    : "${KEYWORD_FIELD_TABS:=0}"
    note "on-page form search (keyword_field_tabs=$KEYWORD_FIELD_TABS)"
    focus_page_content "$WINDOW_ID"
    xdotool key --clearmodifiers ctrl+Home >/dev/null 2>&1; sleep 0.3
    for ((t = 0; t < KEYWORD_FIELD_TABS; t++)); do
        xdotool key --clearmodifiers Tab >/dev/null 2>&1; sleep 0.1
    done
    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; sleep 0.2
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$KEYWORD"
    sleep 0.4
    # Escape closes the suggestion dropdown, which would otherwise swallow Tab.
    xdotool key --clearmodifiers Escape >/dev/null 2>&1; sleep 0.2
    xdotool key --clearmodifiers Tab >/dev/null 2>&1; sleep 0.3
    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; sleep 0.2
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$CITY"
    sleep 0.4
    xdotool key --clearmodifiers Escape >/dev/null 2>&1; sleep 0.2
    xdotool key --clearmodifiers Return >/dev/null 2>&1
    ;;
*)
    fail "$EX_USAGE" "--mode must be 'url' or 'form', got '$MODE'" ;;
esac

# ---------------------------------------------------------------------------
# VERIFY the results page is really there
# ---------------------------------------------------------------------------
sleep "$PAGE_SETTLE_SECONDS"
require_fullscreen "$WINDOW_ID"

ACTUAL_URL=$(copy_address_bar "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || ACTUAL_URL=""
emit "url=$ACTUAL_URL"
note "address bar after search: ${ACTUAL_URL:-<unreadable>}"

PAGE_TEXT=$(copy_page_text "$WINDOW_ID" "$CLIPBOARD_TIMEOUT")
COPY_STATUS=$?
if [ $COPY_STATUS -ne 0 ]; then
    emit "listing_chars=0"
    case $COPY_STATUS in
        "$EX_CLIPBOARD_STALE")
            fail "$EX_CLIPBOARD_STALE" "Ctrl+C did not change the clipboard -- the listing page was NOT copied." ;;
        *)
            fail "$EX_CLIPBOARD_EMPTY" "the listing page copied as empty text." ;;
    esac
fi

if looks_like_access_denied "$PAGE_TEXT"; then
    emit "access_denied=yes"
    emit "verified=no"
    [ -n "$TEMP_FILE" ] && write_temp_atomic "$TEMP_FILE" "$PAGE_TEXT"
    fail "$EX_ACCESS_DENIED" \
        "the results page is an access refusal. Stopping this search. No \
retry, no identity change, no session cycling -- the brief forbids working \
around a refusal and so does ordinary decency toward the site."
fi
emit "access_denied=no"

if looks_like_error_page "$PAGE_TEXT"; then
    emit "verified=no"
    fail "$EX_NAVIGATION" \
        "the results page looks like a browser error page (${#PAGE_TEXT} chars copied), not a listing."
fi

if [ -n "$TEMP_FILE" ]; then
    write_temp_atomic "$TEMP_FILE" "$PAGE_TEXT" \
        || fail "$EX_NAVIGATION" "could not write $TEMP_FILE"
    emit "listing_text_file=$TEMP_FILE"
fi
emit "listing_chars=${#PAGE_TEXT}"

# "verified" means: the address bar shows the host we asked for AND the page
# carries enough text to be a listing.  Python decides what to do with "no".
VERIFIED="no"
case "$ACTUAL_URL" in
    *"$HOST_PART"*|file://*) [ "${#PAGE_TEXT}" -ge 200 ] && VERIFIED="yes" ;;
esac
emit "verified=$VERIFIED"

[ "$VERIFIED" = "yes" ] || fail "$EX_NAVIGATION" \
    "search submitted but the results page was not confirmed (url='${ACTUAL_URL}', ${#PAGE_TEXT} chars)."

note "search ready: $KEYWORD @ $CITY"
exit "$EX_OK"
