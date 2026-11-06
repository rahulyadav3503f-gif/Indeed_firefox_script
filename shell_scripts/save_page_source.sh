#!/usr/bin/env bash
# Ctrl+U, then Ctrl+S, then prove a real file arrived where Python expects it.
#
# USAGE
#   save_page_source.sh --window WID --out /abs/path/under/HOME/file.html
#                       [--expect-url SUBSTRING] [--keep-tab]
#
# STDOUT
#   RESULT:page_url=<the page the source was taken from>
#   RESULT:source_url=view-source:...
#   RESULT:source_tab=yes
#   RESULT:saved_file=/abs/path            <- what Python opens
#   RESULT:saved_bytes=N
#   RESULT:renamed_from=/abs/path          (only when Firefox chose another name)
#
# ===========================================================================
# WHAT Ctrl+S ON A view-source: TAB ACTUALLY WRITES -- MEASURED
# ===========================================================================
# It does NOT write the page's original HTML.  It writes Firefox's RENDERED
# view-source document: the syntax-highlighted version, wrapped in
# <body id="viewsource"> with every original tag escaped (&lt;html&gt;) and
# every line boxed in <span id="lineN">.  A 1,440-byte fixture came back as
# a 7,715-byte file.
#
# That is not a problem, but it IS a fact the reader has to know, because
# grepping the saved file for "<title>" finds nothing.  The original source
# is recovered EXACTLY -- byte for byte, verified -- by taking the text
# content of that body and unescaping it.  source_file/indeed_source.py does
# that, and tests/test_source_recovery.py proves the round trip.
#
# TWO MORE MEASURED QUIRKS, BOTH HANDLED BELOW
#   1. Firefox appends its own extension: asking for "job_1.html" produced
#      "job_1.html.html".  So the file is located by GLOB and then renamed
#      to the path Python was promised.
#   2. With "Web Page, complete" selected, Ctrl+S also creates a
#      "<name>_files/" directory next to the file.  open_firefox.sh sets
#      browser.download.save_converter_index=1 ("HTML only") to stop that;
#      any that still appears is removed here, because nothing reads it and
#      the disk is not free.
# ===========================================================================

SCRIPT_NAME="save_page_source"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

WINDOW_ID=""
OUT_FILE=""
EXPECT_URL=""
KEEP_TAB="no"

while [ $# -gt 0 ]; do
    case "$1" in
        --window)      WINDOW_ID="$2";  shift 2 ;;
        --out)         OUT_FILE="$2";   shift 2 ;;
        --expect-url)  EXPECT_URL="$2"; shift 2 ;;
        --keep-tab)    KEEP_TAB="yes";  shift ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$WINDOW_ID" ] || fail "$EX_USAGE" "--window is required"
[ -n "$OUT_FILE" ]  || fail "$EX_USAGE" "--out is required"
case "$OUT_FILE" in
    /*) : ;;
    *) fail "$EX_USAGE" "--out must be an absolute path, got '$OUT_FILE'" ;;
esac

require_tools xdotool xclip xprop
require_display
require_saveable_path "$OUT_FILE"
window_exists "$WINDOW_ID" || fail "$EX_NO_WINDOW" "window $WINDOW_ID no longer exists"

OUT_DIR=$(dirname "$OUT_FILE")
OUT_BASE=$(basename "$OUT_FILE")
mkdir -p "$OUT_DIR" || fail "$EX_SAVE_FILE" "cannot create $OUT_DIR"

# Refuse to be confused by a previous run's leftovers.
rm -rf "$OUT_FILE" "$OUT_DIR/$OUT_BASE".* "$OUT_DIR/${OUT_BASE%.*}"_files 2>/dev/null

require_window_ready "$WINDOW_ID"

# ---------------------------------------------------------------------------
# 1. WHICH PAGE ARE WE ABOUT TO TAKE THE SOURCE OF?
# ---------------------------------------------------------------------------
PAGE_URL=$(copy_address_bar_retry "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || PAGE_URL=""
[ -n "$PAGE_URL" ] || fail "$EX_NAVIGATION" \
    "could not read the address bar, so there is no way to know which page \
the source would belong to. Refusing to save an unidentified page."
emit "page_url=$PAGE_URL"
note "source will be taken from: $PAGE_URL"

# The caller may insist this is a particular job.  A source file saved under
# the wrong job's name is the worst outcome this script can produce, so the
# check is a hard failure, not a warning.
if [ -n "$EXPECT_URL" ]; then
    case "$PAGE_URL" in
        *"$EXPECT_URL"*) note "page identity confirmed against --expect-url" ;;
        *) fail "$EX_IDENTITY" \
            "the page in the window is not the one asked for. expected to \
contain '$EXPECT_URL', address bar says '$PAGE_URL'." ;;
    esac
fi

case "$PAGE_URL" in
    view-source:*)
        fail "$EX_SOURCE_TAB" \
            "the window is ALREADY showing a view-source tab ($PAGE_URL). \
Ctrl+U here would open the source of the source. Close the tab first." ;;
esac

# ---------------------------------------------------------------------------
# 2. Ctrl+U, AND CONFIRM THE SOURCE TAB IS REALLY THERE
# ---------------------------------------------------------------------------
# Confirmation is read from the ADDRESS BAR, not from the window title: a
# view-source tab's title is just the url, which is indistinguishable from
# an ordinary page whose <title> is missing.  "view-source:" in the address
# bar cannot be anything else.
note "pressing Ctrl+U"
focus_page_content "$WINDOW_ID"
xdotool key --clearmodifiers ctrl+u >/dev/null 2>&1

# MEASURED, AND THE REASON THIS LOOP IS STRICT: a freshly opened
# view-source tab reports "view-source:about:blank" for a moment before it
# resolves to the real document.  Accepting any string beginning
# "view-source:" therefore accepts a BLANK tab -- which is exactly what
# happened on the first run of this script: Ctrl+S then saved about:blank
# and no file ever appeared.
#
# So the loop waits for the one url that is both a source tab AND the
# source of the page we measured in step 1.  This is the "confirm the
# source tab opened" check and the "confirm the intended job" check at the
# same time, and it cannot pass for the wrong document.
WANT_SOURCE_URL="view-source:$PAGE_URL"
SOURCE_URL=""
CURRENT=""
waited=0
while [ "$(printf '%.0f' "$waited")" -lt "$SOURCE_TAB_TIMEOUT" ]; do
    sleep 1
    waited=$(awk "BEGIN{print $waited + 1}")
    CURRENT=$(copy_address_bar_quiet "$WINDOW_ID" 4) || CURRENT=""
    if [ "$CURRENT" = "$WANT_SOURCE_URL" ]; then
        SOURCE_URL="$CURRENT"
        break
    fi
done

[ -n "$SOURCE_URL" ] || fail "$EX_SOURCE_TAB" \
    "Ctrl+U did not produce the view-source tab for this page within \
${SOURCE_TAB_TIMEOUT}s. Wanted '$WANT_SOURCE_URL', address bar reads \
'${CURRENT:-<unreadable>}'. Nothing was saved."

emit "source_url=$SOURCE_URL"
emit "source_tab=yes"
emit "source_url_matches_page=yes"
note "view-source tab confirmed: $SOURCE_URL"

# ---------------------------------------------------------------------------
# 3. Ctrl+S, AND DRIVE THE SAVE DIALOG
# ---------------------------------------------------------------------------
note "pressing Ctrl+S"
xdotool key --clearmodifiers ctrl+s >/dev/null 2>&1

# The dialog is its own X11 window and does NOT belong to the Firefox pid
# (it comes from the desktop portal), so it is found by NAME across the
# display rather than by pid.
DIALOG=""
waited=0
while [ "$(printf '%.0f' "$waited")" -lt "$SAVE_DIALOG_TIMEOUT" ]; do
    DIALOG=$(xdotool search --name "^Save As" 2>/dev/null | tail -1)
    [ -z "$DIALOG" ] && DIALOG=$(xdotool search --name "Save Page As" 2>/dev/null | tail -1)
    [ -n "$DIALOG" ] && break
    sleep "$POLL_INTERVAL"
    waited=$(awk "BEGIN{print $waited + $POLL_INTERVAL}")
done

[ -n "$DIALOG" ] || fail "$EX_SAVE_DIALOG" \
    "the Save As dialog did not appear within ${SAVE_DIALOG_TIMEOUT}s after Ctrl+S."

note "save dialog window=$DIALOG name='$(window_name "$DIALOG")'"

#: Type the destination into the chooser and accept it.
#: The GTK file chooser's name field takes a full absolute path: typing one
#: switches it to location mode and Return accepts it.
drive_save_dialog() {
    xdotool windowactivate --sync "$DIALOG" >/dev/null 2>&1
    # A freshly mapped GTK chooser is not ready for keystrokes immediately;
    # typing into it too early produced "Ctrl+S ran but no file appeared".
    sleep 1.5
    xdotool key --clearmodifiers ctrl+a >/dev/null 2>&1
    sleep 0.4
    xdotool type --clearmodifiers --delay "$KEY_DELAY_MS" -- "$OUT_FILE"
    sleep 1.2
    xdotool key --clearmodifiers Return >/dev/null 2>&1
}

drive_save_dialog

# ---------------------------------------------------------------------------
# 4. PROVE A FILE ARRIVED  (quirk 1: Firefox renames)
# ---------------------------------------------------------------------------
find_saved() {
    local candidate
    if [ -s "$OUT_FILE" ]; then printf '%s' "$OUT_FILE"; return 0; fi
    # Newest non-empty file whose name starts with the one we asked for.
    candidate=$(find "$OUT_DIR" -maxdepth 1 -type f -size +0c \
                     -name "$OUT_BASE*" -printf '%T@ %p\n' 2>/dev/null \
                | sort -rn | head -1 | cut -d' ' -f2-)
    [ -n "$candidate" ] && { printf '%s' "$candidate"; return 0; }
    return 1
}

wait_for_saved_file() {
    local waited=0 found=""
    while [ "$(printf '%.0f' "$waited")" -lt "$SAVE_FILE_TIMEOUT" ]; do
        found=$(find_saved) && [ -n "$found" ] && { printf '%s' "$found"; return 0; }
        sleep "$POLL_INTERVAL"
        waited=$(awk "BEGIN{print $waited + $POLL_INTERVAL}")
    done
    return 1
}

SAVED=$(wait_for_saved_file) || SAVED=""

# ONE RETRY, and only while the dialog is demonstrably still open.
#
# Measured: on a run of eight cards, one card's Ctrl+S left the dialog up
# with nothing typed into it and no file ever arrived. Re-driving a dialog
# that is still on screen is safe -- it is the same dialog, for the same
# file -- and it turns a lost job into a one-attempt delay. If the dialog
# has gone, something else happened and this does NOT guess: it fails.
if [ -z "$SAVED" ] && window_exists "$DIALOG"; then
    warn "no file appeared and the save dialog is still open -- re-entering the path once"
    drive_save_dialog
    SAVED=$(wait_for_saved_file) || SAVED=""
fi

if [ -z "$SAVED" ]; then
    # Leave the dialog alone if it is somehow still up -- a half-driven
    # dialog is the caller's to see, not something to dismiss silently.
    window_exists "$DIALOG" && warn "the save dialog is still open"
    fail "$EX_SAVE_FILE" \
        "Ctrl+S ran but no file matching '$OUT_BASE*' appeared in $OUT_DIR \
within ${SAVE_FILE_TIMEOUT}s."
fi

# A download can still be in flight; wait for the size to stop changing.
PREV=-1
SIZE=$(stat -c%s "$SAVED" 2>/dev/null || echo 0)
waited=0
while [ "$SIZE" != "$PREV" ] && [ "$(printf '%.0f' "$waited")" -lt 10 ]; do
    PREV="$SIZE"
    sleep 0.5
    waited=$(awk "BEGIN{print $waited + 0.5}")
    SIZE=$(stat -c%s "$SAVED" 2>/dev/null || echo 0)
done

# Quirk 1: give Python the path it was promised.
if [ "$SAVED" != "$OUT_FILE" ]; then
    note "Firefox saved as '$(basename "$SAVED")'; renaming to '$OUT_BASE'"
    emit "renamed_from=$SAVED"
    mv -f "$SAVED" "$OUT_FILE" \
        || fail "$EX_SAVE_FILE" "could not rename $SAVED to $OUT_FILE"
    SAVED="$OUT_FILE"
fi

# Quirk 2: the "complete" sidecar directory, if the pref did not take.
for sidecar in "$OUT_DIR/${OUT_BASE%.*}"_files "$OUT_FILE"_files; do
    [ -d "$sidecar" ] && { note "removing unused sidecar $(basename "$sidecar")"; rm -rf "$sidecar"; }
done

SIZE=$(stat -c%s "$SAVED" 2>/dev/null || echo 0)
[ "$SIZE" -ge "$MIN_SOURCE_BYTES" ] || fail "$EX_SAVE_FILE" \
    "the saved source is only ${SIZE} bytes (minimum ${MIN_SOURCE_BYTES}). \
That is not a job page; refusing to hand Python a stub to parse."

emit "saved_file=$SAVED"
emit "saved_bytes=$SIZE"
note "saved ${SIZE} bytes to $SAVED"

# ---------------------------------------------------------------------------
# 5. LEAVE THE SOURCE TAB FOR close_source_tab.sh
# ---------------------------------------------------------------------------
# It is NOT closed here on purpose.  The workflow requires the first
# 10-second delay to happen after Python has processed and saved the job and
# BEFORE the tab is closed, so closing is a separate, separately-timed step.
if [ "$KEEP_TAB" = "yes" ]; then
    note "leaving the view-source tab open (--keep-tab)"
fi

exit "$EX_OK"
