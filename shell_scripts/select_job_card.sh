#!/usr/bin/env bash
# Select one job card and PROVE which job is now showing.
#
# USAGE
#   select_job_card.sh --window WID --index N
#                      [--preselected-key KEY] [--seen-keys k1,k2,...]
#                      [--card-x PX] [--start-y PX] [--max-y PX]
#                      [--probe-step PX] [--probe-limit N]
#                      [--marker vjk=] [--listing-pattern REGEX]
#
# STDOUT
#   RESULT:index=N
#   RESULT:selected_url=...
#   RESULT:selected_key=<vjk value>
#   RESULT:selection_method=preselected|click
#   RESULT:clicked_at=X,Y            (click method only)
#   RESULT:learned_card_y=PX         (the y that worked -- Python learns from it)
#   RESULT:probes=N
#   RESULT:scrolls=N                 (how many times the list was scrolled)
#   RESULT:scrolled=yes|no           (caller must reset its start-y if yes)
#   RESULT:no_more_cards=yes         (nothing selectable below --start-y)
#
# ===========================================================================
# WHY THIS WAS REWRITTEN -- THREE CONFIRMED FAULTS FROM A REAL RUN
# ===========================================================================
# The first live run produced:
#
#     card 1 -> click (430,448) -> vjk unchanged -> ERROR "SAME job"
#     card 2 -> click (430,596) -> vjk unchanged -> ERROR "SAME job"
#     card 3 -> click (430,744) -> vjk CHANGED    -> accepted
#
# Measured against the operator's screenshot of that exact page, the three
# faults were:
#
# FAULT 1.  INDEED PRE-SELECTS THE FIRST JOB.
#     A freshly loaded results page ALREADY carries vjk=<first job> in its
#     url, and the first card is drawn highlighted. There is nothing to
#     click to "select" it -- it is selected. The old script clicked at it,
#     saw an unchanged vjk, and reported the SAME-job error. The first job
#     of every search was therefore never collected, and the search was
#     abandoned. That is what --preselected-key fixes: index 0 is accepted
#     WITHOUT a click when Indeed has already selected it.
#
# FAULT 2.  CARD HEIGHTS ARE NOT CONSTANT, SO CARD_PITCH CANNOT EXIST.
#     On that page the card tops were 410, 645 and 835 -- pitches of 259 and
#     191, not the configured 148. The selected card is taller still,
#     because it expands to show "View similar jobs with this employer", and
#     cards with an "Easily apply" badge or a salary line are taller than
#     ones without. Clicks at 448 and 596 both landed inside card 1 for
#     exactly this reason. So this script no longer multiplies an index by a
#     pitch: it PROBES downward and lets the page tell it where the next
#     card is, reporting the y that worked so Python can learn the spacing.
#
# FAULT 3.  "UNCHANGED vjk" WAS TREATED AS A FATAL IDENTITY ERROR.
#     An unchanged vjk means "that click did not land on a new card" -- a
#     miss worth retrying a little lower, not a reason to abandon the
#     keyword. It is now a probe miss.
#
# ONE MORE HAZARD, HANDLED: a card can contain links that NAVIGATE AWAY
# ("View similar jobs with this employer"). After every click the url is
# checked against the listing pattern, and a navigation is undone with Back
# before probing continues -- otherwise the next Ctrl+U would save a page
# that is not a job at all.
# ===========================================================================

SCRIPT_NAME="select_job_card"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
INDEX=""
PRESELECTED_KEY=""
SEEN_KEYS=""
MARKER="${CARD_MARKER:-vjk=}"
LISTING_PATTERN="${LISTING_PATTERN:-/jobs\?|/jobs$|[?&]q=}"

: "${CARD_X:=430}"
: "${START_Y:=440}"          # first card's clickable area, from the screenshot
: "${CARD_MAX_Y:=1000}"
: "${PROBE_STEP:=55}"        # smaller than the shortest card seen (~170px)
: "${PROBE_LIMIT:=12}"
# When the probe window reaches the bottom of the results column, SCROLL
# and keep looking instead of declaring the page finished. Without this the
# run stops after the three or four cards that happen to fit on screen.
: "${SCROLL_ROUNDS:=6}"       # how many times to scroll before giving up
: "${SCROLL_STEPS:=3}"        # wheel clicks per scroll
: "${AFTER_SCROLL_Y:=320}"    # where the card area starts after scrolling

while [ $# -gt 0 ]; do
    case "$1" in
        --window)           WINDOW_ID="$2";       shift 2 ;;
        --index)            INDEX="$2";           shift 2 ;;
        --preselected-key)  PRESELECTED_KEY="$2"; shift 2 ;;
        --seen-keys)        SEEN_KEYS="$2";       shift 2 ;;
        --card-x)           CARD_X="$2";          shift 2 ;;
        --start-y)          START_Y="$2";         shift 2 ;;
        --max-y)            CARD_MAX_Y="$2";      shift 2 ;;
        --probe-step)       PROBE_STEP="$2";      shift 2 ;;
        --probe-limit)      PROBE_LIMIT="$2";     shift 2 ;;
        --scroll-rounds)    SCROLL_ROUNDS="$2";   shift 2 ;;
        --scroll-steps)     SCROLL_STEPS="$2";    shift 2 ;;
        --after-scroll-y)   AFTER_SCROLL_Y="$2";  shift 2 ;;
        --marker)           MARKER="$2";          shift 2 ;;
        --listing-pattern)  LISTING_PATTERN="$2"; shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"
[ -n "$INDEX" ]     || fail "$EX_USAGE" "--index is required"
case "$INDEX" in ''|*[!0-9]*) fail "$EX_USAGE" "--index must be a number, got '$INDEX'" ;; esac

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" "window $WINDOW_ID no longer exists"
require_window_ready "$WINDOW_ID"

emit "index=$INDEX"

key_of_url() {
    local url="$1" key=""
    case "$url" in
        *"$MARKER"*) key="${url##*$MARKER}"; key="${key%%&*}" ;;
    esac
    printf '%s' "$key"
}

key_already_seen() {
    local key="$1"
    [ -z "$key" ] && return 1
    case ",$SEEN_KEYS," in
        *",$key,"*) return 0 ;;
    esac
    return 1
}

url_is_listing() {
    printf '%s' "$1" | grep -qE "$LISTING_PATTERN"
}

# ---------------------------------------------------------------------------
# 1. WHERE ARE WE?  (also the input guard -- a click is an action)
# ---------------------------------------------------------------------------
assert_input_lands "$WINDOW_ID" "" \
    || fail "$EX_FOCUS" "input guard: $GUARD_REASON. REFUSING to click -- on \
this desktop the click could land in one of your own windows (see FACT 4)."
URL_BEFORE="$GUARD_URL"
KEY_BEFORE=$(key_of_url "$URL_BEFORE")
emit "url_before=$URL_BEFORE"
note "before selection: key='${KEY_BEFORE:-none}'"

# ---------------------------------------------------------------------------
# 2. FAULT 1: IS IT ALREADY SELECTED?
# ---------------------------------------------------------------------------
# Indeed selects the first job for us. Clicking at it would change nothing,
# which is precisely the "failure" the old script reported. If the job in
# the url is one we have not handled yet, it IS the selection -- take it.
if [ -n "$KEY_BEFORE" ] && ! key_already_seen "$KEY_BEFORE"; then
    if [ -z "$PRESELECTED_KEY" ] || [ "$PRESELECTED_KEY" = "$KEY_BEFORE" ]; then
        note "job $KEY_BEFORE is already selected by Indeed -- taking it without clicking"
        emit "selected_url=$URL_BEFORE"
        emit "selected_key=$KEY_BEFORE"
        emit "selection_method=preselected"
        emit "probes=0"
        exit "$EX_OK"
    fi
fi

# ---------------------------------------------------------------------------
# 3. FAULT 2: PROBE DOWNWARD INSTEAD OF MULTIPLYING BY A PITCH
# ---------------------------------------------------------------------------
PROBES=0
Y="$START_Y"
SELECTED_URL=""
SELECTED_KEY=""
LANDED_Y=""
SCROLLS=0

#: Scroll the RESULTS COLUMN, not the page: the wheel acts on whatever is
#: under the pointer, so the pointer is parked in the card column first.
#: The dropdown is dismissed here too -- a wheel event over an open
#: suggestion panel scrolls the panel, not the jobs.
scroll_results_column() {
    local step
    dismiss_url_dropdown
    xdotool mousemove --sync "$CARD_X" "$SCROLL_AT_Y" >/dev/null 2>&1
    sleep 0.2
    for (( step = 0; step < SCROLL_STEPS; step++ )); do
        xdotool click --clearmodifiers 5 >/dev/null 2>&1    # wheel down
        sleep 0.25
    done
    sleep 1.2
}
SCROLL_AT_Y=$(( (START_Y + CARD_MAX_Y) / 2 ))

# PROBE_LIMIT is PER SCROLL ROUND, not for the whole search.
#
# It used to bound the total, which quietly defeated scrolling: twelve
# probes were spent walking the first screenful, so only ONE scroll ever
# happened no matter what SCROLL_ROUNDS said, and the page was declared
# exhausted while most of its cards were still below the fold.
PROBES_THIS_ROUND=0
while :; do
    # OUT OF SCREEN? SCROLL, DON'T GIVE UP.
    #
    # The results column holds three or four cards at a time. Probing only
    # between --start-y and --max-y therefore finds three or four jobs and
    # then reports "no more cards", and the caller moves on to the next
    # search -- which is exactly the "it cannot scroll down" symptom. When
    # the window is exhausted the list is scrolled and probing restarts at
    # the top of the card area; --seen-keys stops the cards that scrolled
    # up from being collected twice.
    if [ "$Y" -gt "$CARD_MAX_Y" ] || [ "$PROBES_THIS_ROUND" -ge "$PROBE_LIMIT" ]; then
        if [ "$SCROLLS" -ge "$SCROLL_ROUNDS" ]; then
            break
        fi
        SCROLLS=$((SCROLLS + 1))
        note "nothing new above y=$Y -- scrolling the results list (round $SCROLLS/$SCROLL_ROUNDS)"
        scroll_results_column
        Y="$AFTER_SCROLL_Y"
        PROBES_THIS_ROUND=0
    fi

    PROBES=$((PROBES + 1))
    PROBES_THIS_ROUND=$((PROBES_THIS_ROUND + 1))

    # CLOSE THE ADDRESS-BAR PANEL BEFORE EVERY CLICK.
    #
    # This loop reads the url after each probe to see whether the selection
    # changed, and that read uses Ctrl+L -- which does not merely focus the
    # address bar, it opens the SUGGESTION DROPDOWN over the top of the
    # page. The next probe then clicks at the next y... which is now a row
    # in that dropdown, not a job card. Firefox follows the suggestion and
    # the run lands on a site that has nothing to do with Indeed.
    #
    # Measured twice before this guard existed: runs ended up on
    # youtube.com and on wikipedia.org, having "selected" nothing.
    dismiss_url_dropdown

    note "probe $PROBES: clicking ${CARD_X},${Y}"
    xdotool mousemove --sync "$CARD_X" "$Y" >/dev/null 2>&1
    sleep 0.25
    xdotool click 1 >/dev/null 2>&1
    sleep "$PAGE_SETTLE_SECONDS"

    URL_AFTER=$(copy_address_bar_retry "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || URL_AFTER=""

    # HAZARD: a card can hold links that leave the results page entirely.
    if [ -n "$URL_AFTER" ] && ! url_is_listing "$URL_AFTER"; then
        warn "the click navigated away from the listing ($URL_AFTER); going Back"
        dismiss_url_dropdown
        xdotool key --clearmodifiers alt+Left >/dev/null 2>&1
        sleep "$PAGE_SETTLE_SECONDS"
        URL_AFTER=$(copy_address_bar_retry "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || URL_AFTER=""

        # Having gone Back, refuse to carry on probing unless we really are
        # on the listing again: clicking blind on an unknown page is how one
        # wrong click becomes several.
        if [ -n "$URL_AFTER" ] && ! url_is_listing "$URL_AFTER"; then
            fail "$EX_NAVIGATION" \
                "a probe click left the listing and Back did not return to \
it (now at '$URL_AFTER'). Refusing to keep clicking on a page that is not \
the job list."
        fi
        Y=$((Y + PROBE_STEP))
        continue
    fi

    KEY_AFTER=$(key_of_url "$URL_AFTER")

    if [ -n "$KEY_AFTER" ] && [ "$KEY_AFTER" != "$KEY_BEFORE" ] \
       && ! key_already_seen "$KEY_AFTER"; then
        SELECTED_URL="$URL_AFTER"
        SELECTED_KEY="$KEY_AFTER"
        LANDED_Y="$Y"
        break
    fi

    # FAULT 3: an unchanged key is a MISS, not a fatal error.
    if [ "$KEY_AFTER" = "$KEY_BEFORE" ]; then
        note "   same job still selected -- the click was inside the current card"
    elif key_already_seen "$KEY_AFTER"; then
        note "   job $KEY_AFTER has already been handled -- probing past it"
        KEY_BEFORE="$KEY_AFTER"
    fi
    Y=$((Y + PROBE_STEP))
done

emit "probes=$PROBES"
emit "scrolls=$SCROLLS"
[ "$SCROLLS" -gt 0 ] && emit "scrolled=yes" || emit "scrolled=no"

if [ -z "$SELECTED_KEY" ]; then
    # Only NOW is the page really finished: the probe window was exhausted
    # and the list was scrolled $SCROLL_ROUNDS times with nothing new
    # appearing. The caller reads this as the end of the page's cards.
    emit "no_more_cards=yes"
    fail "$EX_IDENTITY" \
        "no new job card found: $PROBES probe(s) and $SCROLLS scroll(s) \
found nothing that had not already been handled. The page's cards are \
exhausted."
fi

emit "selected_url=$SELECTED_URL"
emit "selected_key=$SELECTED_KEY"
emit "selection_method=click"
emit "clicked_at=${CARD_X},${LANDED_Y}"
emit "learned_card_y=$LANDED_Y"
note "card index $INDEX selected: job $SELECTED_KEY at y=$LANDED_Y after \
$PROBES probe(s) and $SCROLLS scroll(s)"

exit "$EX_OK"
