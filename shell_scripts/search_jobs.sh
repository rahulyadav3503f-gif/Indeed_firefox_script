#!/usr/bin/env bash
# Type one keyword + city into Indeed's OWN search fields and submit.
#
# The keyword and the city are ARGUMENTS.  There is no role list and no city
# list in this file, or in any other shell script: Python owns the plan
# (target_audience_roles.build_role_plan and new_mylib.city_by_states), the
# shell owns the keystrokes.  The operator never types either value.
#
# USAGE
#   search_jobs.sh --window WID --keyword "Azure Administrator" --city "Pune"
#                  [--mode form|url] [--base-url https://in.indeed.com]
#                  [--what-xy X,Y] [--where-xy X,Y] [--start N]
#
# TWO MODES
#   form  (DEFAULT)  Click Indeed's "what" box, type the keyword, click the
#                    "where" box, type the city, press Return -- which is
#                    what a person does, and what was asked for.  Each field
#                    is READ BACK before submitting, so a mis-aimed click
#                    is caught before a wrong search is run.
#   url              Put a constructed search url in the address bar. Kept
#                    as a fallback for when the page layout moves, and for
#                    file:// fixtures, which have no search form at all.
#
# ===========================================================================
# WHAT CHANGED, AND WHY  (the listing-page copy is GONE)
# ===========================================================================
# This script used to finish by pressing Ctrl+A then Ctrl+C on the results
# page and requiring the clipboard to change.  In the field that produced:
#
#     [search_jobs] ERROR(8): Ctrl+C did not change the clipboard.
#                             The listing page was NOT copied.
#
# ...and a ~29 second retry, on a search that had in fact loaded perfectly.
#
# The copy existed only to answer two questions -- "did the results page
# load?" and "is this a refusal?" -- and it answered both expensively and
# unreliably.  Both are now answered without the clipboard:
#
#   * LOADED?   The address bar must show the host, /jobs, and the q= and l=
#               we asked for.  Indeed also adds vjk=<job key> once the
#               results pane has populated, which is a far better "ready for
#               card selection" signal than a character count.
#   * REFUSAL?  The WINDOW TITLE says so. Firefox puts the document title
#               there, so a Cloudflare interstitial reads "Just a moment...",
#               a dead host reads "Server not found", and a healthy results
#               page reads "<n> <keyword> jobs in <city> ...".
#
# Nothing is copied here any more.  Clipboard use that is genuinely needed
# elsewhere -- reading the address bar, reading back a search field -- is
# untouched.
# ===========================================================================
#
# STDOUT
#   RESULT:search_url=...            (url mode only)
#   RESULT:typed_keyword=...         (form mode: what the box actually held)
#   RESULT:typed_city=...            (form mode: what the box actually held)
#   RESULT:url=<address bar after the search>
#   RESULT:title=<window title after the search>
#   RESULT:results_ready=yes|no
#   RESULT:preselected_key=<vjk value Indeed auto-selected, if any>
#   RESULT:verified=yes|no
#   RESULT:access_denied=yes|no

SCRIPT_NAME="search_jobs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
KEYWORD=""
CITY=""
BASE_URL="https://in.indeed.com"
MODE="${SEARCH_MODE:-form}"
START_AT=""

# Where Indeed's two search boxes are, in SCREEN coordinates, for the
# normal window this project opens.  Measured from the supplied screenshot
# (1845x1046 window at +0+34): the "what" box is at about (700, 240) and
# the "where" box at about (1100, 240).  Arguments, not constants.
: "${SEARCH_WHAT_X:=700}"
: "${SEARCH_WHAT_Y:=240}"
: "${SEARCH_WHERE_X:=1100}"
: "${SEARCH_WHERE_Y:=240}"

while [ $# -gt 0 ]; do
    case "$1" in
        --window)    WINDOW_ID="$2"; shift 2 ;;
        --keyword)   KEYWORD="$2";   shift 2 ;;
        --city)      CITY="$2";      shift 2 ;;
        --base-url)  BASE_URL="$2";  shift 2 ;;
        --mode)      MODE="$2";      shift 2 ;;
        --start)     START_AT="$2";  shift 2 ;;
        --what-xy)   SEARCH_WHAT_X="${2%%,*}";  SEARCH_WHAT_Y="${2##*,}";  shift 2 ;;
        --where-xy)  SEARCH_WHERE_X="${2%%,*}"; SEARCH_WHERE_Y="${2##*,}"; shift 2 ;;
        # Accepted and ignored: the listing-page copy this used to do is gone.
        --temp-file) shift 2 ;;
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

require_window_ready "$WINDOW_ID"

HOST_PART="${BASE_URL#*://}"; HOST_PART="${HOST_PART%%/*}"

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

# ---------------------------------------------------------------------------
# INPUT GUARD -- before a single character is typed
# ---------------------------------------------------------------------------
assert_input_lands "$WINDOW_ID" "" \
    || fail "$EX_FOCUS" "input guard: $GUARD_REASON. REFUSING to type -- on \
this desktop the keys could land in one of your own windows (see FACT 4)."
BEFORE_URL="$GUARD_URL"
note "input guard passed; address bar reads: $BEFORE_URL"

# ---------------------------------------------------------------------------
# TYPE THE SEARCH
# ---------------------------------------------------------------------------
#: Click a text box, select whatever is in it, type ours, read it back.
#: The read-back is a FIELD copy (Ctrl+A/Ctrl+C inside one input), not a
#: page copy -- that is the operation the change request keeps.
type_into_field() {
    local x="$1" y="$2" value="$3" label="$4" seen=""
    # The address-bar panel covers the page and would swallow this click --
    # see dismiss_url_dropdown() in _common.sh for what that cost.
    dismiss_url_dropdown
    note "clicking the $label box at ${x},${y}"
    xdotool mousemove --sync "$x" "$y" >/dev/null 2>&1
    sleep 0.3
    xdotool click 1 >/dev/null 2>&1
    sleep 0.6

    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; sleep 0.25
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$value"
    sleep 0.6
    # Close the suggestion dropdown so it cannot swallow the next click or
    # the Return.  Escape here is safe: no page load is in flight.
    xdotool key --clearmodifiers Escape >/dev/null 2>&1
    sleep 0.3

    seen=$(_copy_with_nonce "$WINDOW_ID" 6 ctrl+a ctrl+c) || seen=""
    printf '%s' "$seen"
}

case "$MODE" in
form)
    # LET THE PAGE SETTLE BEFORE TOUCHING ITS SEARCH BOXES.
    # Indeed's home page keeps laying out after it reports loaded, and the
    # two boxes move while it does. Clicking into them too early is how a
    # run ends up typing into nothing.
    note "waiting ${SEARCH_FIELD_DELAY_SECONDS}s for the page to settle before typing"
    sleep "$SEARCH_FIELD_DELAY_SECONDS"

    note "form search: '$KEYWORD' in '$CITY'"

    TYPED_KEYWORD=$(type_into_field "$SEARCH_WHAT_X" "$SEARCH_WHAT_Y" \
                                    "$KEYWORD" "keyword")
    emit "typed_keyword=$TYPED_KEYWORD"

    TYPED_CITY=$(type_into_field "$SEARCH_WHERE_X" "$SEARCH_WHERE_Y" \
                                 "$CITY" "city")
    emit "typed_city=$TYPED_CITY"

    # CONFIRM BEFORE SUBMITTING.  A click that landed on the page background
    # instead of the input types the keyword into nothing, and submitting
    # then runs the PREVIOUS search again -- which would be recorded against
    # this keyword.  Refusing here is much cheaper than detecting it later.
    if [ -n "$TYPED_KEYWORD" ] && [ "$TYPED_KEYWORD" != "$KEYWORD" ]; then
        fail "$EX_NAVIGATION" \
            "the keyword box holds '$TYPED_KEYWORD', not '$KEYWORD'. The \
click at ${SEARCH_WHAT_X},${SEARCH_WHAT_Y} did not land in the search field. \
Nothing was submitted. Adjust --what-xy for this window size."
    fi
    if [ -n "$TYPED_CITY" ] && [ "$TYPED_CITY" != "$CITY" ]; then
        fail "$EX_NAVIGATION" \
            "the city box holds '$TYPED_CITY', not '$CITY'. The click at \
${SEARCH_WHERE_X},${SEARCH_WHERE_Y} did not land in the location field. \
Nothing was submitted. Adjust --where-xy for this window size."
    fi
    # AN EMPTY READ-BACK IS A FAILURE, NOT A WARNING.
    #
    # This used to warn and submit anyway, and it cost a live run: both
    # read-backs came back empty -- which means Ctrl+A/Ctrl+C produced
    # nothing, i.e. the keystrokes never reached our window at all -- and
    # the Return that followed was delivered to a focused address bar with
    # a suggestion dropdown open. Firefox navigated to a top-site shortcut
    # (youtube.com) and the run ended up reading job cards from... YouTube.
    #
    # If the box cannot be read back, there is no evidence the keyword ever
    # landed, and pressing Return is a keystroke aimed at an unknown target.
    # Stop instead.
    if [ -z "$TYPED_KEYWORD" ] || [ -z "$TYPED_CITY" ]; then
        fail "$EX_FOCUS" \
            "could not read the search boxes back (keyword='$TYPED_KEYWORD', \
city='$TYPED_CITY'). That means the keystrokes are not reaching our Firefox \
window, so there is no evidence the search was typed. REFUSING to press \
Return -- on this desktop it would be delivered to whatever currently has \
focus (see FACT 4 in _common.sh). Nothing was submitted."
    fi

    # And re-prove focus immediately before the Return, because the gap
    # between typing and submitting is long enough for focus to move.
    assert_input_lands "$WINDOW_ID" "" \
        || fail "$EX_FOCUS" "input guard before submit: $GUARD_REASON. \
Nothing was submitted."

    note "both fields confirmed; submitting"
    xdotool key --clearmodifiers Return >/dev/null 2>&1
    ;;
url)
    SEARCH_URL="${BASE_URL%/}/jobs?q=$(urlencode "$KEYWORD")&l=$(urlencode "$CITY")"
    [ -n "$START_AT" ] && [ "$START_AT" != "0" ] && SEARCH_URL+="&start=$START_AT"
    emit "search_url=$SEARCH_URL"
    note "address-bar search: $SEARCH_URL"
    xdotool key --clearmodifiers Escape >/dev/null 2>&1; sleep 0.2
    xdotool key --clearmodifiers ctrl+l >/dev/null 2>&1; sleep 0.5
    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; sleep 0.2
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$SEARCH_URL"
    sleep 0.5
    xdotool key --clearmodifiers Return >/dev/null 2>&1
    ;;
*)
    fail "$EX_USAGE" "--mode must be 'form' or 'url', got '$MODE'" ;;
esac

# ---------------------------------------------------------------------------
# VERIFY -- WITHOUT COPYING THE PAGE
# ---------------------------------------------------------------------------
sleep "$PAGE_SETTLE_SECONDS"
require_window_ready "$WINDOW_ID"

# 1. A refusal or a dead page announces itself in the title.
PAGE_TITLE=$(wait_for_title_to_settle "$WINDOW_ID" 20)
emit "title=$PAGE_TITLE"
note "window title: ${PAGE_TITLE:-<none>}"

if title_says_access_denied "$PAGE_TITLE"; then
    emit "access_denied=yes"
    emit "verified=no"
    fail "$EX_ACCESS_DENIED" \
        "the results page is an access refusal (title: '$PAGE_TITLE'). \
Stopping this search. No retry, no identity change, no session cycling."
fi
emit "access_denied=no"

if title_says_error_page "$PAGE_TITLE"; then
    emit "verified=no"
    fail "$EX_NAVIGATION" \
        "the browser is showing an error page (title: '$PAGE_TITLE'), not a listing."
fi

# 2. The address bar must show OUR search.  Indeed percent-encodes spaces as
#    '+' in the query it builds from the form, so both encodings are
#    accepted; everything else must match exactly.
KEYWORD_PATTERN=$(printf '%s' "$KEYWORD" | sed 's/[][\.*^$(){}?+|/]/\\&/g; s/ /[+%%]/g')
CITY_PATTERN=$(printf '%s' "$CITY" | sed 's/[][\.*^$(){}?+|/]/\\&/g; s/ /[+%%]/g')
URL_PATTERN="$HOST_PART.*[?&]q=${KEYWORD_PATTERN}.*[&]l=${CITY_PATTERN}"

ACTUAL_URL=$(wait_for_url_match "$WINDOW_ID" "$URL_PATTERN" 25) || ACTUAL_URL="$ACTUAL_URL"
emit "url=$ACTUAL_URL"
note "address bar after search: ${ACTUAL_URL:-<unreadable>}"

VERIFIED="no"
case "$ACTUAL_URL" in
    file://*) VERIFIED="yes" ;;                      # fixture runs
    *)
        if printf '%s' "$ACTUAL_URL" | grep -qE "$URL_PATTERN"; then
            VERIFIED="yes"
        fi ;;
esac
emit "verified=$VERIFIED"

if [ "$VERIFIED" != "yes" ]; then
    fail "$EX_NAVIGATION" \
        "the search was submitted but the results url does not match the \
keyword and city asked for. Wanted something matching '$URL_PATTERN', the \
address bar says '${ACTUAL_URL:-<unreadable>}'. Refusing to read job cards \
from a page that is not this search."
fi

# 3. READY FOR CARD SELECTION?
#    Indeed appends vjk=<job key> once the results pane has populated with
#    its automatically-selected first job.  Its presence means the cards are
#    rendered -- a far better readiness test than a character count, and it
#    hands the first job's identity straight to select_job_card.sh.
PRESELECTED=""
READY_URL=$(wait_for_url_match "$WINDOW_ID" "[?&]vjk=[A-Za-z0-9]" 20) \
    && PRESELECTED="${READY_URL##*vjk=}" && PRESELECTED="${PRESELECTED%%&*}"

if [ -n "$PRESELECTED" ]; then
    emit "preselected_key=$PRESELECTED"
    emit "results_ready=yes"
    emit "url=$READY_URL"
    note "results ready; Indeed pre-selected job $PRESELECTED"
else
    # Not fatal: a search with no results, or a layout without the pane,
    # still leaves a verified results page. Python decides what to do.
    emit "results_ready=no"
    note "no vjk= appeared within 20s -- either no results, or no detail pane"
fi

note "search ready: $KEYWORD @ $CITY"
exit "$EX_OK"
