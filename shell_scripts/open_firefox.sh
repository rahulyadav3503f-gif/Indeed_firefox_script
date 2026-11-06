#!/usr/bin/env bash
# Start OUR Firefox, identify its window, size it, open a page, verify.
#
# NORMAL WINDOW MODE.  This script no longer puts Firefox into fullscreen:
# the requirement was withdrawn so the operator can watch the run in an
# ordinary decorated window.  Size and position default to the supplied
# screenshot (1845x1046 at +0+34 on a 1920x1080 screen) and are arguments,
# not constants.
#
# The four things it must not do, and how it does not:
#
#   "Do not depend only on a fixed delay."
#       Every wait is a bounded POLL on an observable condition: the process
#       is alive, a window of OUR pid exists, it is focused, it is
#       fullscreen, the address bar reads the host we asked for.
#
#   "Do not assume the newest desktop window belongs to the intended
#    instance."
#       Firefox is started with --new-instance and its own --profile, so it
#       is a new PROCESS.  Only windows whose owning process is that one
#       (confirmed through /proc/PID/exe, not through a cmdline substring)
#       are ever considered.
#
#   "Do not accidentally close or control another user's browser window."
#       Windows that existed before this script ran are recorded and refused.
#       The user's own Firefox is never adopted, focused, typed into or
#       closed, and this script never calls a bare `firefox URL`, which
#       would open a tab inside it (see FACT 3 in _common.sh).
#
#   "Firefox must NOT run in fullscreen mode."
#       No F11 is sent, no fullscreen window-manager request is made, and a
#       window that somehow arrives fullscreen is taken OUT of it.  What is
#       still checked is that the window is focused and big enough for the
#       results column to be on screen -- without that, every card
#       coordinate is meaningless. See require_window_ready().
#
# USAGE
#   open_firefox.sh --profile DIR --url URL [--state-file FILE]
#                   [--expect-host HOST] [--download-dir DIR]
#                   [--window-size WxH] [--window-pos X,Y]
#
# STDOUT
#   RESULT:firefox_pid=NNNN
#   RESULT:window_id=NNNNNNN
#   RESULT:window_geometry=WIDTHxHEIGHT+X+Y
#   RESULT:fullscreen=no
#   RESULT:url=<what the address bar actually says>
#   RESULT:verified=yes|no
#   RESULT:access_denied=yes|no

SCRIPT_NAME="open_firefox"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

PROFILE_DIR=""
TARGET_URL=""
STATE_FILE=""
EXPECT_HOST=""
DOWNLOAD_DIR=""
# Defaults read off the supplied screenshot: a normal window occupying the
# screen below the GNOME top bar, title bar visible.
: "${WINDOW_WIDTH:=1845}"
: "${WINDOW_HEIGHT:=1046}"
: "${WINDOW_X:=0}"
: "${WINDOW_Y:=34}"

while [ $# -gt 0 ]; do
    case "$1" in
        --profile)       PROFILE_DIR="$2";  shift 2 ;;
        --url)           TARGET_URL="$2";   shift 2 ;;
        --state-file)    STATE_FILE="$2";   shift 2 ;;
        --expect-host)   EXPECT_HOST="$2";  shift 2 ;;
        --download-dir)  DOWNLOAD_DIR="$2"; shift 2 ;;
        --firefox)       FIREFOX_BIN="$2";  shift 2 ;;
        --window-size)   WINDOW_WIDTH="${2%%x*}"; WINDOW_HEIGHT="${2##*x}"; shift 2 ;;
        --window-pos)    WINDOW_X="${2%%,*}";     WINDOW_Y="${2##*,}";      shift 2 ;;
        *) fail "$EX_USAGE" "unknown argument: $1" ;;
    esac
done

[ -n "$PROFILE_DIR" ] || fail "$EX_USAGE" "--profile is required"
[ -n "$TARGET_URL" ]  || fail "$EX_USAGE" "--url is required"

require_tools xdotool xclip xprop
require_display
require_saveable_path "$PROFILE_DIR/placeholder"

mkdir -p "$PROFILE_DIR" || fail "$EX_LAUNCH" "cannot create profile dir $PROFILE_DIR"
[ -n "$DOWNLOAD_DIR" ] && mkdir -p "$DOWNLOAD_DIR"

# ---------------------------------------------------------------------------
# 1. PROFILE PREFERENCES
# ---------------------------------------------------------------------------
# Written every start, so a hand-edited profile cannot quietly change how
# saving behaves.  Nothing here disguises the browser: no user-agent
# override, no automation or stealth flag, no fingerprint change.  These
# prefs only remove first-run furniture and make Ctrl+S predictable.
#
# browser.download.save_converter_index=1 is "Web Page, HTML only".  At 0
# ("complete") Ctrl+S also writes a <name>_files/ directory beside every
# saved page, which this project never reads and which would fill the disk.
cat > "$PROFILE_DIR/user.js" <<'PREFS'
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("app.update.auto", false);
user_pref("app.update.enabled", false);
user_pref("browser.download.useDownloadDir", true);
user_pref("browser.download.folderList", 2);
user_pref("browser.download.save_converter_index", 1);
user_pref("browser.download.manager.addToRecentDocs", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.warnOnCloseOtherTabs", false);
user_pref("browser.warnOnQuit", false);
user_pref("view_source.wrap_long_lines", false);
PREFS
if [ -n "$DOWNLOAD_DIR" ]; then
    printf 'user_pref("browser.download.dir", "%s");\n' "$DOWNLOAD_DIR" \
        >> "$PROFILE_DIR/user.js"
fi

# ---------------------------------------------------------------------------
# 2. RECORD WHAT ALREADY EXISTS -- so it is left strictly alone
# ---------------------------------------------------------------------------
PRE_EXISTING=$(xdotool search --onlyvisible --class firefox 2>/dev/null | tr '\n' ' ')
note "pre-existing Firefox windows (never touched): ${PRE_EXISTING:-none}"
emit "pre_existing_windows=${PRE_EXISTING// /,}"

# ---------------------------------------------------------------------------
# 3. START OUR OWN FIREFOX  (FACTS 1, 2b and 3)
# ---------------------------------------------------------------------------
LOG_FILE="${FIREFOX_LOG:-$PROFILE_DIR/firefox.log}"
PID_FILE="$PROFILE_DIR/firefox.pid"
rm -f "$PID_FILE"

firefox_x11_env
XAUTH_IN_USE=$(firefox_xauthority)
note "display=$DISPLAY xauthority=${XAUTH_IN_USE:-unset}"

if firefox_is_snap; then
    note "launch mode: snap (inner binary inside 'snap run --shell')"
    [ -x "$FIREFOX_SNAP_BINARY" ] \
        || fail "$EX_LAUNCH" "snap Firefox binary not found at $FIREFOX_SNAP_BINARY"
    # Built as a string because it runs inside the snap's own shell.  Every
    # interpolated value is single-quoted; paths with spaces survive.
    INNER=$(printf '%s' "
        export MOZ_ENABLE_WAYLAND=0 GDK_BACKEND=x11 MOZ_NO_REMOTE=1
        unset WAYLAND_DISPLAY
        export DISPLAY='$DISPLAY'
        export XAUTHORITY='$XAUTH_IN_USE'
        '$FIREFOX_SNAP_BINARY' --new-instance --profile '$PROFILE_DIR' '$TARGET_URL' >>'$LOG_FILE' 2>&1 &
        echo \$! > '$PID_FILE'
    ")
    snap run --shell firefox -c "$INNER" >>"$LOG_FILE" 2>&1
else
    note "launch mode: direct ($FIREFOX_BIN)"
    "$FIREFOX_BIN" --new-instance --profile "$PROFILE_DIR" "$TARGET_URL" \
        >>"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
fi

sleep 1
FIREFOX_PID=$(cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]')
[ -n "$FIREFOX_PID" ] || fail "$EX_LAUNCH" \
    "Firefox was started but no pid was recorded. See $LOG_FILE"

# ---------------------------------------------------------------------------
# 4. CONFIRM THE PID IS REALLY OUR FIREFOX
# ---------------------------------------------------------------------------
# /proc/PID/exe, not a cmdline substring.  A cmdline match would also match
# THIS script (its own arguments contain the profile path), which is exactly
# how an automation script ends up killing itself.
pid_is_firefox() {
    local pid="$1" exe
    exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null) || return 1
    case "$exe" in *firefox*) return 0 ;; esac
    return 1
}

if ! kill -0 "$FIREFOX_PID" 2>/dev/null; then
    fail "$EX_LAUNCH" "Firefox (pid $FIREFOX_PID) exited immediately. Log: $(tail -3 "$LOG_FILE" 2>/dev/null | tr '\n' ' ')"
fi
pid_is_firefox "$FIREFOX_PID" || warn \
    "pid $FIREFOX_PID does not look like firefox ($(readlink -f /proc/$FIREFOX_PID/exe 2>/dev/null)) -- continuing, the window search will decide"

note "firefox pid=$FIREFOX_PID"

# ---------------------------------------------------------------------------
# 5. FIND OUR WINDOW -- by pid, never by recency
# ---------------------------------------------------------------------------
WINDOW_ID=$(wait_for_window_of_pid "$FIREFOX_PID" "$WINDOW_TIMEOUT")
[ -n "$WINDOW_ID" ] || fail "$EX_NO_WINDOW" \
    "Firefox (pid $FIREFOX_PID) started but no window of its own appeared \
within ${WINDOW_TIMEOUT}s. On a Wayland desktop this usually means it did \
not take the X11 backend -- see FACT 1 in _common.sh. Log: $(tail -3 "$LOG_FILE" 2>/dev/null | tr '\n' ' ')"

# Refuse a window that existed before we started.
case " $PRE_EXISTING " in
    *" $WINDOW_ID "*)
        fail "$EX_NO_WINDOW" "window $WINDOW_ID existed before this script started -- refusing to drive somebody else's browser." ;;
esac

# A SECOND INSTANCE ON THE SAME PROFILE DOES NOT GIVE A BROWSER WINDOW.
# Firefox shows a "Close Firefox" / "profile is already in use" dialog
# instead, and that dialog IS a window of our pid -- so the window search
# finds it and everything downstream fails with a baffling "the address bar
# does not contain indeed". Measured live. Name it here instead.
WINDOW_TITLE=$(window_name "$WINDOW_ID")
case "$WINDOW_TITLE" in
    "Close Firefox"*|*"already in use"*|*"Profile Missing"*)
        fail "$EX_LAUNCH" \
            "Firefox opened the '$WINDOW_TITLE' dialog instead of a browser \
window: another Firefox is already using the profile $PROFILE_DIR. Close \
that instance first, or reuse its window instead of launching a new one." ;;
esac

note "window_id=$WINDOW_ID name=$WINDOW_TITLE"
emit "firefox_pid=$FIREFOX_PID"
emit "window_id=$WINDOW_ID"
emit "profile_dir=$PROFILE_DIR"

# ---------------------------------------------------------------------------
# 6. FOCUS AND FULLSCREEN, BOTH VERIFIED
# ---------------------------------------------------------------------------
require_focus "$WINDOW_ID"

# NORMAL WINDOW, NOT FULLSCREEN.
# A profile that was last used fullscreen reopens fullscreen, so leaving it
# is done explicitly rather than assumed.
exit_fullscreen_if_set "$WINDOW_ID"
set_window_geometry "$WINDOW_ID" "$WINDOW_X" "$WINDOW_Y" \
                    "$WINDOW_WIDTH" "$WINDOW_HEIGHT"
require_window_ready "$WINDOW_ID"

GEOMETRY=$(window_geometry "$WINDOW_ID")
emit "window_geometry=$GEOMETRY"
emit "fullscreen=no"
note "normal window: $GEOMETRY (asked for ${WINDOW_WIDTH}x${WINDOW_HEIGHT}+${WINDOW_X}+${WINDOW_Y})"

# ---------------------------------------------------------------------------
# 7. VERIFY THE EXPECTED PAGE IS ACTUALLY THERE
# ---------------------------------------------------------------------------
sleep "$PAGE_SETTLE_SECONDS"
ACTUAL_URL=$(copy_address_bar "$WINDOW_ID" "$CLIPBOARD_TIMEOUT") || ACTUAL_URL=""
emit "url=$ACTUAL_URL"
note "address bar: ${ACTUAL_URL:-<unreadable>}"

VERIFIED="no"
if [ -n "$ACTUAL_URL" ]; then
    if [ -n "$EXPECT_HOST" ]; then
        case "$ACTUAL_URL" in *"$EXPECT_HOST"*) VERIFIED="yes" ;; esac
    else
        VERIFIED="yes"
    fi
fi
emit "verified=$VERIFIED"

# Refusal detection from the WINDOW TITLE, not from a Ctrl+A/Ctrl+C copy of
# the page.  The title is free, instant, and cannot fail the way the
# clipboard did in the field ("Ctrl+C did not change the clipboard").
PAGE_TITLE=$(wait_for_title_to_settle "$WINDOW_ID" 10)
emit "title=$PAGE_TITLE"
if title_says_access_denied "$PAGE_TITLE"; then
    emit "access_denied=yes"
    fail "$EX_ACCESS_DENIED" \
        "the first page is an access refusal (title: '$PAGE_TITLE'). Stopping: no retry, no identity change."
fi
emit "access_denied=no"

# ---------------------------------------------------------------------------
# 8. HAND THE IDS TO PYTHON
# ---------------------------------------------------------------------------
if [ -n "$STATE_FILE" ]; then
    write_temp_atomic "$STATE_FILE" "$(printf '{\n  "firefox_pid": %s,\n  "window_id": "%s",\n  "profile_dir": "%s",\n  "download_dir": "%s",\n  "url": "%s",\n  "verified": "%s",\n  "fullscreen": "no",\n  "display": "%s",\n  "xauthority": "%s",\n  "started_at": "%s"\n}\n' \
        "$FIREFOX_PID" "$WINDOW_ID" "$PROFILE_DIR" "$DOWNLOAD_DIR" "$ACTUAL_URL" \
        "$VERIFIED" "$DISPLAY" "$XAUTH_IN_USE" "$(date -Is)")" \
        || warn "could not write state file $STATE_FILE"
fi

if [ "$VERIFIED" != "yes" ]; then
    fail "$EX_NAVIGATION" "Firefox is up in a normal window, but the address bar does not contain '${EXPECT_HOST}'. Got: ${ACTUAL_URL:-<unreadable>}"
fi

note "ready"
exit "$EX_OK"
