#!/usr/bin/env bash
# Close the view-source tab and confirm we are back on the listing.
#
# USAGE
#   close_source_tab.sh --window WID [--expect-listing SUBSTRING] [--force]
#
# STDOUT
#   RESULT:closed=yes|no_tab
#   RESULT:url=<the address bar after closing>
#   RESULT:back_on_listing=yes|no
#
# WHY IT VERIFIES INSTEAD OF JUST PRESSING Ctrl+W
# -----------------------------------------------
# Ctrl+W closes whatever tab is in front.  If the view-source tab had
# already gone -- a crash, a stray click, a previous run -- then a blind
# Ctrl+W closes THE LISTING instead, and the next job card selection runs
# against whatever is behind it.  So the tab is identified before it is
# closed, and the listing is identified after.

SCRIPT_NAME="close_source_tab"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
EXPECT_LISTING=""
FORCE="no"

while [ $# -gt 0 ]; do
    case "$1" in
        --window)          WINDOW_ID="$2";      shift 2 ;;
        --expect-listing)  EXPECT_LISTING="$2"; shift 2 ;;
        --force)           FORCE="yes";         shift ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"

require_tools xdotool xclip xprop
require_display
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" "window $WINDOW_ID no longer exists"

require_focus "$WINDOW_ID"
require_fullscreen "$WINDOW_ID"

BEFORE=$(copy_address_bar "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || BEFORE=""
note "address bar before closing: ${BEFORE:-<unreadable>}"

case "$BEFORE" in
    view-source:*) : ;;
    *)
        if [ "$FORCE" != "yes" ]; then
            # Not an error: the caller may simply have nothing to close.
            # Refusing is the safe move -- see the header.
            warn "the front tab is not a view-source tab ('${BEFORE:-unreadable}'); \
NOT pressing Ctrl+W, because that would close the listing."
            emit "closed=no_tab"
            emit "url=$BEFORE"
            emit "back_on_listing=unknown"
            exit "$EX_OK"
        fi
        warn "--force given: closing '${BEFORE:-unreadable}' even though it is not a source tab"
        ;;
esac

note "closing the view-source tab"
focus_page_content "$WINDOW_ID"
xdotool key --clearmodifiers ctrl+w >/dev/null 2>&1

AFTER=""
waited=0
while [ "$(printf '%.0f' "$waited")" -lt "$SOURCE_TAB_TIMEOUT" ]; do
    sleep 1
    waited=$(awk "BEGIN{print $waited + 1}")
    AFTER=$(copy_address_bar_quiet "$WINDOW_ID" 4) || AFTER=""
    case "$AFTER" in
        view-source:*) : ;;          # still on the source tab, keep waiting
        "")            : ;;
        *)             break ;;
    esac
done

case "$AFTER" in
    view-source:*|"")
        fail "$EX_NAVIGATION" \
            "the view-source tab is still in front after Ctrl+W \
(address bar reads '${AFTER:-<unreadable>}')." ;;
esac

emit "closed=yes"
emit "url=$AFTER"
note "back on: $AFTER"

BACK="yes"
if [ -n "$EXPECT_LISTING" ]; then
    case "$AFTER" in
        *"$EXPECT_LISTING"*) BACK="yes" ;;
        *) BACK="no" ;;
    esac
fi
emit "back_on_listing=$BACK"

if [ "$BACK" != "yes" ]; then
    fail "$EX_NAVIGATION" \
        "the source tab closed but the page underneath is not the listing. \
Expected it to contain '$EXPECT_LISTING', got '$AFTER'."
fi

exit "$EX_OK"
