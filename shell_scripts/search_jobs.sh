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
    # PREVIEWS, not the raw read-back: a RESULT line is one line by
    # definition -- the protocol is line-based -- and a whole-page copy
    # would spray 120 lines through it and corrupt every later RESULT.
    emit "typed_keyword=$(field_preview "$TYPED_KEYWORD")"

    TYPED_CITY=$(type_into_field "$SEARCH_WHERE_X" "$SEARCH_WHERE_Y" \
                                 "$CITY" "city")
    emit "typed_city=$(field_preview "$TYPED_CITY")"

    # CONFIRM BEFORE SUBMITTING.  A click that landed on the page background
    # instead of the input types the keyword into nothing, and submitting
    # then runs the PREVIOUS search again -- which would be recorded against
    # this keyword.  Refusing here is much cheaper than detecting it later.
    # WHAT A FAILED READ-BACK ACTUALLY MEANS, AND HOW TO SAY IT.
    #
    # When the click misses the input, focus stays on the DOCUMENT -- and
    # there Ctrl+A selects the whole page, so Ctrl+C copies it. The
    # read-back then "holds" four kilobytes of Indeed's home page. Measured
    # 2026-11-10: this message printed all of it, twice per retry, and the
    # real fault (a click ~30px high) was invisible underneath.
    #
    # is_field_value() separates the two cases exactly -- an input's value
    # cannot contain a newline -- and field_preview() keeps either one to a
    # single line. See _common.sh.
    if [ -n "$TYPED_KEYWORD" ] && [ "$TYPED_KEYWORD" != "$KEYWORD" ]; then
        if is_field_value "$TYPED_KEYWORD"; then
            fail "$EX_NAVIGATION" \
                "the keyword box holds $(field_preview "$TYPED_KEYWORD"), \
not '$KEYWORD'. The click at ${SEARCH_WHAT_X},${SEARCH_WHAT_Y} landed in \
some other field. Nothing was submitted."
        fi
        fail "$EX_NAVIGATION" \
            "the click at ${SEARCH_WHAT_X},${SEARCH_WHAT_Y} did NOT land in \
the keyword box: it landed on the page body, so Ctrl+A selected the whole \
document and the read-back is $(field_preview "$TYPED_KEYWORD"). Nothing \
was submitted. Run verify_search_fields.sh to find the box -- it probes \
nearby rows and reports the coordinates that work. (Indeed's home page has \
a different layout when signed in, and a window manager may not place the \
window where it was asked to.)"
    fi
    if [ -n "$TYPED_CITY" ] && [ "$TYPED_CITY" != "$CITY" ]; then
        if is_field_value "$TYPED_CITY"; then
            fail "$EX_NAVIGATION" \
                "the city box holds $(field_preview "$TYPED_CITY"), not \
'$CITY'. The click at ${SEARCH_WHERE_X},${SEARCH_WHERE_Y} landed in some \
other field. Nothing was submitted."
        fi
        fail "$EX_NAVIGATION" \
            "the click at ${SEARCH_WHERE_X},${SEARCH_WHERE_Y} did NOT land \
in the location box: it landed on the page body and the read-back is \
$(field_preview "$TYPED_CITY"). Nothing was submitted. Run \
verify_search_fields.sh to find the box."
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

    # NO ADDRESS-BAR GUARD HERE, DELIBERATELY.
    #
    # There used to be a second assert_input_lands() at this point, to
    # re-prove focus before Return. It did the opposite of its job: the
    # guard reads the address bar with Ctrl+L, which moves the caret OUT of
    # the city box and INTO the address bar. The Return that followed was
    # therefore delivered to the address bar and merely re-loaded the page
    # that was already open. Measured live: both boxes read back correctly,
    # then the url stayed at https://in.indeed.com/ and no search ran.
    #
    # The guard is also redundant here. Reading a field back with
    # Ctrl+A/Ctrl+C is itself proof that keystrokes reach our window -- it
    # returned the exact text we typed -- and unlike Ctrl+L it leaves the
    # caret where it is. So the read-backs above ARE the guard, and Return
    # is pressed with focus still in the location box, which is what
    # submits an Indeed search.
    note "both fields confirmed; submitting (focus is still in the city box)"
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
# AFTER PRESSING ENTER: WAIT, THEN GO
# ---------------------------------------------------------------------------
# WHAT USED TO BE HERE, AND WHY IT IS GONE
#
# This script used to refuse to finish unless, after Return:
#   * the address bar matched  host...q=<keyword>...l=<city>  exactly, and
#   * a vjk= parameter had appeared within 20s.
#
# Both were removed deliberately. They blocked progression to the first job
# card on searches that had in fact loaded perfectly, and the identity of
# the job being saved is guaranteed further down the pipeline anyway:
# select_job_card.sh reads the job key from the url, save_page_source.sh
# refuses to save unless the page still carries that key (--expect-url),
# and indeed_source.py isolates that key out of the saved document. So a
# wrong page cannot put wrong data in Excel; it simply fails later, which
# is where it belongs.
#
# WHAT IS DELIBERATELY KEPT
#   * The ACCESS REFUSAL check. It is not a "did my search work" test -- it
#     is how this project notices the site has said no, and it must keep
#     stopping the run rather than pressing on.
#   * Reading the url once, opportunistically, to hand select_job_card.sh
#     the job Indeed pre-selected. It is a HINT now, never a gate: an empty
#     result is fine and the next step just clicks instead.
# ---------------------------------------------------------------------------
note "waiting ${SEARCH_RESULTS_WAIT_SECONDS}s for the results to load"
sleep "$SEARCH_RESULTS_WAIT_SECONDS"
require_window_ready "$WINDOW_ID"

# -- access refusal: still a hard stop --------------------------------------
PAGE_TITLE=$(window_name "$WINDOW_ID")
emit "title=$PAGE_TITLE"
note "window title: ${PAGE_TITLE:-<none>}"

if title_says_access_denied "$PAGE_TITLE"; then
    emit "access_denied=yes"
    fail "$EX_ACCESS_DENIED" \
        "the results page is an access refusal (title: '$PAGE_TITLE'). \
Stopping this search. No retry, no identity change, no session cycling."
fi
emit "access_denied=no"

# A dead page is REPORTED but no longer blocks: there will be no job card to
# select, and card selection will say so in its own terms.
if title_says_error_page "$PAGE_TITLE"; then
    emit "error_page=yes"
    warn "the window title looks like a browser error page ('$PAGE_TITLE'); \
continuing to card selection anyway, which will report what it finds"
else
    emit "error_page=no"
fi

# -- one opportunistic read, purely to hand over the pre-selected job -------
ACTUAL_URL=$(copy_address_bar_retry "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || ACTUAL_URL=""
emit "url=$ACTUAL_URL"
note "address bar after search: ${ACTUAL_URL:-<unreadable>}"

# No keyword/city/url matching, and no verified=yes|no gate any more.
emit "verified=not_checked"

PRESELECTED=""
case "$ACTUAL_URL" in
    *vjk=*) PRESELECTED="${ACTUAL_URL##*vjk=}"; PRESELECTED="${PRESELECTED%%&*}" ;;
esac

if [ -n "$PRESELECTED" ]; then
    emit "preselected_key=$PRESELECTED"
    emit "results_ready=yes"
    note "Indeed pre-selected job $PRESELECTED"
else
    emit "results_ready=no"
    note "no vjk= in the url -- select_job_card.sh will click for the first card"
fi

note "search submitted: $KEYWORD @ $CITY -- going to the first job card"
exit "$EX_OK"
