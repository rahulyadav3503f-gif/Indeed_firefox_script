#!/usr/bin/env bash
# LIVE CAPTURE: the first N job cards of one keyword + city.
#
#   capture_cards.sh "Social Media Designer" "Delhi" 5
#
# It drives the project's own scripts in the approved order and keeps the
# two mandated delays:
#
#   select card -> Ctrl+U/Ctrl+S -> (Python would extract here)
#               -> sleep 10 -> close source tab -> sleep 10 -> next card
#
# It does NOT write Excel and does NOT touch the checkpoint: extraction is
# done afterwards, offline, from the saved files.  That keeps the live part
# as short as possible and makes the extraction step repeatable without a
# browser.
#
# Everything it learns goes to Temp_Data/rank_1/capture_log.tsv so the
# extraction step knows which saved file belongs to which job key.

set -u
KEYWORD="${1:?usage: capture_cards.sh KEYWORD CITY [COUNT]}"
CITY="${2:?usage: capture_cards.sh KEYWORD CITY [COUNT]}"
COUNT="${3:-5}"

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_DIR="$BASE/shell_scripts"
TEMP="$BASE/Temp_Data/rank_1"
PROFILE="$BASE/config/firefox_profile/rank_1"
LOG="$TEMP/capture_log.tsv"

export DISPLAY="${DISPLAY:-:0}"
export FIREFOX_XAUTH_COPY="$BASE/config/xauth_xwayland"

: "${PRE_CLOSE_DELAY:=10}"
: "${POST_CLOSE_DELAY:=10}"

mkdir -p "$TEMP"
: > "$LOG"
printf 'index\tjob_key\tmethod\tsaved_file\tbytes\tpage_url\n' >> "$LOG"

say() { printf '\n=== %s ===\n' "$*"; }

#: Pull one RESULT:key=value out of a script's stdout.
value_of() { printf '%s\n' "$1" | sed -n "s/^RESULT:$2=//p" | tail -1; }

# ---------------------------------------------------------------------------
# 1. BROWSER
# ---------------------------------------------------------------------------
#: A Firefox already running on OUR profile, or empty.  Identified through
#: /proc/PID/exe so this script's own command line (which contains the
#: profile path) cannot match itself.
running_on_profile() {
    local pid exe
    for pid in $(pgrep -f -- "--profile $PROFILE" 2>/dev/null); do
        exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null) || continue
        case "$exe" in *firefox*) printf '%s' "$pid"; return 0 ;; esac
    done
    return 1
}

# REUSE AN EXISTING BROWSER RATHER THAN LAUNCHING A SECOND ONE.
# Launching a second instance on the same profile does not give a browser
# window -- Firefox shows a "Close Firefox" dialog, the window search finds
# THAT, and the run dies confusingly. Measured.
EXISTING_PID=$(running_on_profile || true)
if [ -n "$EXISTING_PID" ]; then
    WINDOW=$(xdotool search --onlyvisible --pid "$EXISTING_PID" 2>/dev/null | head -1)
    TITLE=$(xdotool getwindowname "$WINDOW" 2>/dev/null)
    case "$TITLE" in
        "Close Firefox"*|"") WINDOW="" ;;
    esac
fi

if [ -n "${WINDOW:-}" ]; then
    say "reusing the Firefox already open on this profile (pid $EXISTING_PID, window $WINDOW)"
    GEOMETRY=$(xdotool getwindowgeometry --shell "$WINDOW" | \
        awk -F= '/WIDTH/{w=$2} /HEIGHT/{h=$2} /^X=/{x=$2} /^Y=/{y=$2} END{printf "%dx%d+%d+%d", w,h,x,y}')
    echo "window geometry: $GEOMETRY"
    # Make sure it is on Indeed's home page before typing a search.
    # This sleep is the page LOAD wait; search_jobs.sh then adds its own
    # SEARCH_FIELD_DELAY_SECONDS settle before it clicks the boxes.
    timeout 60 bash -c '
        export DISPLAY="'"$DISPLAY"'"
        xdotool windowactivate --sync '"$WINDOW"'; sleep 1
        xdotool key --clearmodifiers ctrl+l; sleep 0.6
        xdotool key --clearmodifiers ctrl+a; sleep 0.3
        xdotool type --clearmodifiers --delay 14 -- "https://in.indeed.com/"; sleep 0.5
        xdotool key --clearmodifiers Return'
    sleep 6
else

say "opening Firefox (normal window) on Indeed"
OPEN_OUT=$(timeout 240 bash "$SHELL_DIR/open_firefox.sh" \
    --profile "$PROFILE" \
    --url "https://in.indeed.com/" \
    --state-file "$TEMP/browser_window.json" \
    --download-dir "$TEMP" \
    --expect-host indeed 2>&1) || { printf '%s\n' "$OPEN_OUT"; exit 3; }
printf '%s\n' "$OPEN_OUT" | grep -E "RESULT:(window_id|window_geometry|url|verified)"

WINDOW=$(value_of "$OPEN_OUT" window_id)
GEOMETRY=$(value_of "$OPEN_OUT" window_geometry)
[ -n "$WINDOW" ] || { echo "no window id"; exit 3; }
fi

# Search-box positions are WINDOW-RELATIVE offsets measured on this layout
# (a 1850-wide normal window): the "what" box centre sits at +698+214 and
# the "where" box at +1076+214.  They are turned into screen coordinates
# from the window's ACTUAL position, so the run survives the window manager
# placing the window wherever it likes.
WIN_X="${GEOMETRY##*+}"; WIN_X="${GEOMETRY#*+}"; WIN_X="${WIN_X%%+*}"
WIN_Y="${GEOMETRY##*+}"
: "${WHAT_DX:=698}" ; : "${WHAT_DY:=214}"
: "${WHERE_DX:=1076}"; : "${WHERE_DY:=214}"
WHAT_XY="$((WIN_X + WHAT_DX)),$((WIN_Y + WHAT_DY))"
WHERE_XY="$((WIN_X + WHERE_DX)),$((WIN_Y + WHERE_DY))"
echo "window at +${WIN_X}+${WIN_Y}; what=$WHAT_XY where=$WHERE_XY"

# ---------------------------------------------------------------------------
# 2. SEARCH  (typed into Indeed's own boxes)
# ---------------------------------------------------------------------------
say "searching: '$KEYWORD' in '$CITY'"
SEARCH_OUT=$(timeout 240 bash "$SHELL_DIR/search_jobs.sh" \
    --window "$WINDOW" \
    --keyword "$KEYWORD" \
    --city "$CITY" \
    --mode form \
    --what-xy "$WHAT_XY" \
    --where-xy "$WHERE_XY" 2>&1) || { printf '%s\n' "$SEARCH_OUT"; exit 7; }
printf '%s\n' "$SEARCH_OUT" | grep -E "RESULT:(typed_|url|title|results_ready|preselected_key)"

PRESELECTED=$(value_of "$SEARCH_OUT" preselected_key)
LISTING_URL=$(value_of "$SEARCH_OUT" url)

# ---------------------------------------------------------------------------
# 3. THE CARDS
# ---------------------------------------------------------------------------
SEEN=""
START_Y=440
SAVED=0

for (( i = 0; i < COUNT; i++ )); do
    say "card $i"

    SELECT_ARGS=(--window "$WINDOW" --index "$i" --start-y "$START_Y")
    [ -n "$SEEN" ] && SELECT_ARGS+=(--seen-keys "$SEEN")
    [ "$i" -eq 0 ] && [ -n "$PRESELECTED" ] && SELECT_ARGS+=(--preselected-key "$PRESELECTED")

    SEL_OUT=$(timeout 200 bash "$SHELL_DIR/select_job_card.sh" "${SELECT_ARGS[@]}" 2>&1)
    SEL_RC=$?
    printf '%s\n' "$SEL_OUT" | grep -E "RESULT:(selected_key|selection_method|learned_card_y|probes|no_more_cards)|ERROR"
    if [ $SEL_RC -ne 0 ]; then
        echo "card $i could not be selected -- stopping"
        break
    fi

    KEY=$(value_of "$SEL_OUT" selected_key)
    METHOD=$(value_of "$SEL_OUT" selection_method)
    LANDED=$(value_of "$SEL_OUT" learned_card_y)
    [ -n "$LANDED" ] && START_Y=$((LANDED + 60))
    SEEN="${SEEN:+$SEEN,}$KEY"

    OUT_FILE="$TEMP/job_1_$(printf '%04d' "$i").html"
    SAVE_OUT=$(timeout 240 bash "$SHELL_DIR/save_page_source.sh" \
        --window "$WINDOW" --out "$OUT_FILE" --expect-url "vjk=$KEY" 2>&1)
    SAVE_RC=$?
    printf '%s\n' "$SAVE_OUT" | grep -E "RESULT:(source_url|saved_file|saved_bytes)|ERROR"
    if [ $SAVE_RC -ne 0 ]; then
        echo "card $i source was not saved -- closing the tab and continuing"
        timeout 90 bash "$SHELL_DIR/close_source_tab.sh" --window "$WINDOW" >/dev/null 2>&1
        continue
    fi

    BYTES=$(value_of "$SAVE_OUT" saved_bytes)
    PAGE_URL=$(value_of "$SAVE_OUT" page_url)

    # EXTRACT ALL 32 FIELDS NOW, from the file just saved, BEFORE the source
    # tab is closed and before the next card is selected. This mirrors what
    # find_indeed_job.py does inline; doing it here too means the live run
    # shows the same thing the collector would log.
    echo "  --- reading all 32 fields out of $(basename "$OUT_FILE") ---"
    python3 "$BASE/tools/show_fields.py" "$OUT_FILE" "$KEY" "$PAGE_URL" || true
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$i" "$KEY" "$METHOD" "$OUT_FILE" "$BYTES" "$PAGE_URL" >> "$LOG"
    SAVED=$((SAVED + 1))

    # FIRST mandated delay: after the job is processed, BEFORE the tab closes.
    echo "  sleeping ${PRE_CLOSE_DELAY}s (first delay)"
    sleep "$PRE_CLOSE_DELAY"

    timeout 120 bash "$SHELL_DIR/close_source_tab.sh" --window "$WINDOW" 2>&1 \
        | grep -E "RESULT:(closed|back_on_listing)|ERROR"

    # SECOND mandated delay: after the tab closed, BEFORE the next card.
    echo "  sleeping ${POST_CLOSE_DELAY}s (second delay)"
    sleep "$POST_CLOSE_DELAY"
done

say "done: $SAVED source file(s) saved"
cat "$LOG"
