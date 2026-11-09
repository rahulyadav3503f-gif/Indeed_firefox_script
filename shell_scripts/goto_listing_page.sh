#!/usr/bin/env bash
# Go to a results page by url -- how the collector turns the page.
#
# USAGE
#   goto_listing_page.sh --window WID --url URL [--expect-start N]
#
# STDOUT
#   RESULT:url=<address bar after loading>
#   RESULT:title=<window title>
#   RESULT:start=<the start= value actually in the url, "" for page 1>
#   RESULT:access_denied=yes|no
#   RESULT:preselected_key=<vjk Indeed opened on the new page, if any>
#
# WHY A URL AND NOT A CLICK ON "Next"
# -----------------------------------
# The "Next" control moves as the page's footer changes and is often below
# the fold, so clicking it means scrolling to something whose position is
# not knowable in advance. The url is exact: Indeed pages with start= in
# multiples of ten, and page 1's url carries everything that defines the
# search (q, l, radius, from). listing_page_url() in indeed_controller.py
# derives page N from it by dropping vjk= and setting start=.
#
# WHY NOT REBUILD THE URL FROM THE KEYWORD AND CITY
# -------------------------------------------------
# Because that quietly drops the parameters the search form added --
# radius= above all -- and a different radius is a different result set.
# Page 2 has to be page 1's url, edited.

SCRIPT_NAME="goto_listing_page"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
TARGET_URL=""
EXPECT_START=""

while [ $# -gt 0 ]; do
    case "$1" in
        --window)       WINDOW_ID="$2";    shift 2 ;;
        --url)          TARGET_URL="$2";   shift 2 ;;
        --expect-start) EXPECT_START="$2"; shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ]  || fail "$EX_USAGE" "--window is required"
[ -n "$TARGET_URL" ] || fail "$EX_USAGE" "--url is required"
case "$TARGET_URL" in
    http://*|https://*) : ;;
    *) fail "$EX_USAGE" "--url must be absolute, got '$TARGET_URL'" ;;
esac

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" "window $WINDOW_ID no longer exists"
require_window_ready "$WINDOW_ID"

# Typing a url is an ACTION: prove the keystrokes reach our window first,
# or they land in whatever else has focus (see FACT 4 in _common.sh).
assert_input_lands "$WINDOW_ID" "" \
    || fail "$EX_FOCUS" "input guard: $GUARD_REASON. REFUSING to type a url."

note "going to: $TARGET_URL"
xdotool key --clearmodifiers ctrl+l >/dev/null 2>&1
sleep 0.6
xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1
sleep 0.3
xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$TARGET_URL"
sleep 0.6
xdotool key --clearmodifiers Return >/dev/null 2>&1

note "waiting ${SEARCH_RESULTS_WAIT_SECONDS}s for the page to load"
sleep "$SEARCH_RESULTS_WAIT_SECONDS"
require_window_ready "$WINDOW_ID"

# A refusal still stops the run; everything else is reported, not enforced.
PAGE_TITLE=$(window_name "$WINDOW_ID")
emit "title=$PAGE_TITLE"
note "window title: ${PAGE_TITLE:-<none>}"
if title_says_access_denied "$PAGE_TITLE"; then
    emit "access_denied=yes"
    fail "$EX_ACCESS_DENIED" \
        "the results page is an access refusal (title: '$PAGE_TITLE'). \
Stopping. No retry, no identity change, no session cycling."
fi
emit "access_denied=no"

ACTUAL_URL=$(copy_address_bar_retry "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || ACTUAL_URL=""
emit "url=$ACTUAL_URL"
note "address bar: ${ACTUAL_URL:-<unreadable>}"

ACTUAL_START=""
case "$ACTUAL_URL" in
    *start=*) ACTUAL_START="${ACTUAL_URL##*start=}"; ACTUAL_START="${ACTUAL_START%%&*}" ;;
esac
emit "start=$ACTUAL_START"

# THE ONE THING WORTH ENFORCING: that we actually turned the page.
# Asking for start=10 and landing on start= (page 1) would collect page 1
# again under page 2's name, and every job on it would be a duplicate.
if [ -n "$EXPECT_START" ] && [ -n "$ACTUAL_URL" ]; then
    if [ "$ACTUAL_START" != "$EXPECT_START" ]; then
        fail "$EX_NAVIGATION" \
            "asked for start=$EXPECT_START but the address bar says \
start='${ACTUAL_START:-<none>}'. The page did not turn; refusing to read \
cards from it as though it had."
    fi
    note "page turn confirmed: start=$ACTUAL_START"
fi

# Indeed opens a job in the detail pane on the new page too; hand its key
# over so card 0 can be taken without a click, exactly as after a search.
PRESELECTED=""
case "$ACTUAL_URL" in
    *vjk=*) PRESELECTED="${ACTUAL_URL##*vjk=}"; PRESELECTED="${PRESELECTED%%&*}" ;;
esac
if [ -n "$PRESELECTED" ]; then
    emit "preselected_key=$PRESELECTED"
    note "Indeed pre-selected job $PRESELECTED on this page"
fi

exit "$EX_OK"
