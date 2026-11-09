#!/usr/bin/env bash
# Prove Indeed's two search boxes are there and reachable -- WITHOUT searching.
#
# USAGE
#   verify_search_fields.sh --window WID [--what-xy X,Y] [--where-xy X,Y]
#                           [--probe TEXT]
#
# STDOUT
#   RESULT:what_ok=yes|no
#   RESULT:where_ok=yes|no
#   RESULT:what_read=<what the keyword box held after typing the probe>
#   RESULT:where_read=<what the location box held after typing the probe>
#   RESULT:url=<address bar>
#   RESULT:title=<window title>
#   RESULT:verified=yes|no
#
# WHY THIS EXISTS
# ---------------
# The collector restarts Firefox between keywords, and a restart can land
# somewhere other than a working home page: a session expired, a consent
# wall, a page that loaded but has not laid out yet.  The next thing the
# run does is CLICK where the search boxes should be and type a keyword, and
# on this desktop a click that misses an input types into nothing -- after
# which Return submits whatever the page had before.  That exact sequence
# once sent a run to youtube.com.
#
# So: before trusting the page, type a throwaway string into each box and
# read it back.  A box that gives the probe back is a real input, in the
# place we think it is, receiving our keystrokes.
#
# WHAT IT DOES NOT DO
# -------------------
# It never presses Return and it never leaves the probe behind: each box is
# cleared after it is read.  Nothing is searched, nothing is submitted, and
# the page is left as it was found.  The probe is deliberately not a job
# keyword -- nothing it types could be mistaken for a real search.

SCRIPT_NAME="verify_search_fields"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
PROBE="zz"

# The same measured defaults search_jobs.sh uses, and overridable the same
# way: the caller owns the geometry, this script owns the keystrokes.
: "${SEARCH_WHAT_X:=700}"
: "${SEARCH_WHAT_Y:=240}"
: "${SEARCH_WHERE_X:=1100}"
: "${SEARCH_WHERE_Y:=240}"

while [ $# -gt 0 ]; do
    case "$1" in
        --window)    WINDOW_ID="$2"; shift 2 ;;
        --probe)     PROBE="$2";     shift 2 ;;
        --what-xy)   SEARCH_WHAT_X="${2%%,*}";  SEARCH_WHAT_Y="${2##*,}";  shift 2 ;;
        --where-xy)  SEARCH_WHERE_X="${2%%,*}"; SEARCH_WHERE_Y="${2##*,}"; shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"
[ -n "$PROBE" ]     || fail "$EX_USAGE" "--probe must not be empty"

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" \
    "window $WINDOW_ID no longer exists -- Firefox may have been closed."
require_window_ready "$WINDOW_ID"

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

#: Type the probe into one box, read it back, then clear the box.
#: Prints what the box held.  Leaves the box empty either way.
probe_field() {
    local x="$1" y="$2" label="$3" seen=""
    dismiss_url_dropdown
    note "probing the $label box at ${x},${y}"
    xdotool mousemove --sync "$x" "$y" >/dev/null 2>&1
    sleep 0.3
    xdotool click 1 >/dev/null 2>&1
    sleep 0.6

    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; sleep 0.25
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$PROBE"
    sleep 0.5
    # Shut the suggestion dropdown: it would cover the other box's click.
    xdotool key --clearmodifiers Escape >/dev/null 2>&1
    sleep 0.3

    seen=$(_copy_with_nonce "$WINDOW_ID" 6 ctrl+a ctrl+c) || seen=""

    # LEAVE NOTHING BEHIND. Whatever happened above, this box must not still
    # hold the probe when the real search types into it.
    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1; sleep 0.2
    xdotool key --clearmodifiers Delete  >/dev/null 2>&1; sleep 0.2
    xdotool key --clearmodifiers Escape  >/dev/null 2>&1; sleep 0.2

    printf '%s' "$seen"
}

WHAT_READ=$(probe_field "$SEARCH_WHAT_X" "$SEARCH_WHAT_Y" "keyword")
emit "what_read=$WHAT_READ"
WHERE_READ=$(probe_field "$SEARCH_WHERE_X" "$SEARCH_WHERE_Y" "location")
emit "where_read=$WHERE_READ"

WHAT_OK=no;  [ "$WHAT_READ"  = "$PROBE" ] && WHAT_OK=yes
WHERE_OK=no; [ "$WHERE_READ" = "$PROBE" ] && WHERE_OK=yes
emit "what_ok=$WHAT_OK"
emit "where_ok=$WHERE_OK"

if [ "$WHAT_OK" = yes ] && [ "$WHERE_OK" = yes ]; then
    emit "verified=yes"
    note "both search boxes accepted and returned the probe"
    exit "$EX_OK"
fi

emit "verified=no"
# An empty read-back and a wrong one are different faults, and the message
# has to say which: empty means the keystrokes never arrived, wrong means
# the click missed the input.
fail "$EX_NAVIGATION" \
    "the search boxes did not verify: keyword box returned \
'${WHAT_READ:-<nothing>}', location box returned '${WHERE_READ:-<nothing>}', \
probe was '$PROBE'. $([ -z "$WHAT_READ$WHERE_READ" ] \
&& printf 'Nothing read back at all -- the keystrokes are not reaching our \
Firefox, or the page has not laid out yet.' \
|| printf 'A click landed outside the input -- check --what-xy/--where-xy \
for this window size.') Nothing was searched."
