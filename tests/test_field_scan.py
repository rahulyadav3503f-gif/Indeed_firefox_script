"""verify_search_fields.sh, driven against a SIMULATED browser.

The static checks in test_regressions.py prove the script mentions the
right things.  These run it -- the real script, the real `_common.sh`, the
real scan loop -- with fake `xdotool`, `xclip` and `xprop` on PATH standing
in for Firefox, and assert on what it actually does.

The fake browser models the one thing that caused the 2026-11-10 failure:

    a click inside a search box    -> typing lands in that box
    a click anywhere else          -> focus stays on the DOCUMENT, where
                                      Ctrl+A selects the whole page and
                                      Ctrl+C copies it

So "the keyword box holds <4KB of Indeed's home page>" is reproducible here
without a browser, and so is the scan that fixes it.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHELL = os.path.join(BASE, "shell_scripts")

#: What a whole-page copy looks like -- taken from the real failure log.
PAGE_TEXT = """ non user content
Start of main content
Keyword : all jobs
Edit location input box label
Welcome, rohan
Photoshop Designers
Delhi"""

FAKE_XDOTOOL = r'''#!/usr/bin/env bash
S="$FAKE_STATE"
case "$1" in
  getwindowname)     echo "Indeed - Job Search" ;;
  getwindowgeometry) echo "WINDOW 1"; echo "X=$WIN_X"; echo "Y=$WIN_Y"
                     echo "WIDTH=1850"; echo "HEIGHT=1053" ;;
  getwindowpid)      echo 4242 ;;
  getactivewindow)   echo 1 ;;
  windowactivate|windowfocus|windowraise|search|getdisplaygeometry) echo 1 ;;
  mousemove)         shift; while [ "${1:0:2}" = "--" ]; do shift; done
                     echo "$1 $2" > "$S.mouse" ;;
  click)
      read -r mx my < "$S.mouse" 2>/dev/null || { mx=0; my=0; }
      focus=body
      if [ "$my" -ge "$BOX_Y" ] && [ "$my" -le "$((BOX_Y + 24))" ]; then
        if   [ "$mx" -ge "$((BOX_X1 - 180))" ] && [ "$mx" -le "$((BOX_X1 + 180))" ]; then focus=what
        elif [ "$mx" -ge "$((BOX_X2 - 180))" ] && [ "$mx" -le "$((BOX_X2 + 180))" ]; then focus=where
        fi
      fi
      echo "$focus" > "$S.focus"
      echo "$mx $my" >> "$S.clicks" ;;
  type)              shift
                     while [ "${1:0:2}" = "--" ] || [ "$1" = "--" ]; do
                       [ "$1" = "--delay" ] && shift; shift; done
                     f=$(cat "$S.focus" 2>/dev/null || echo body)
                     [ "$f" != body ] && [ "$f" != chrome ] && printf '%s' "$*" > "$S.$f" ;;
  key)
      shift; [ "$1" = "--clearmodifiers" ] && shift
      f=$(cat "$S.focus" 2>/dev/null || echo body)
      case "$1" in
        ctrl+l) echo chrome > "$S.focus" ;;
        F6)     echo body   > "$S.focus" ;;
        Delete) [ "$f" != body ] && [ "$f" != chrome ] && : > "$S.$f" ;;
        ctrl+c)
            case "$f" in
              chrome)     printf '%s' "https://in.indeed.com/" > "$S.clip" ;;
              what|where) printf '%s' "$(cat "$S.$f" 2>/dev/null)" > "$S.clip" ;;
              *)          cat "$FAKE_PAGE" > "$S.clip" ;;
            esac ;;
      esac ;;
esac
exit 0
'''

FAKE_XCLIP = r'''#!/usr/bin/env bash
S="$FAKE_STATE"
for a in "$@"; do [ "$a" = "-i" ] && { cat > "$S.clip"; exit 0; }; done
cat "$S.clip" 2>/dev/null
'''


#: Each distinct (box position, guess, flags) is RUN ONCE and shared.
#: Without this the suite spends minutes re-running the same simulation:
#: every probe costs about a second of settles inside _common.sh, which are
#: real timings this file deliberately does not reach into.
_RUNS = {}


def simulate(box_y, guess_y, extra=(), box_x1=770, box_x2=1170,
             win=(70, 27)):
    """Run the real verify_search_fields.sh against the fake browser.

    Returns a dict: exit, results (the RESULT: lines), stderr, clicks
    (every screen position the scan actually clicked).
    """
    key = (box_y, guess_y, tuple(extra), box_x1, box_x2, win)
    if key in _RUNS:
        return _RUNS[key]

    work = tempfile.mkdtemp(prefix="field-scan-")
    binaries = os.path.join(work, "bin")
    os.makedirs(binaries)
    for name, body in (("xdotool", FAKE_XDOTOOL), ("xclip", FAKE_XCLIP),
                       ("xprop", "#!/bin/sh\nexit 0\n")):
        path = os.path.join(binaries, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(path, 0o755)
    page = os.path.join(work, "page.txt")
    with open(page, "w", encoding="utf-8") as handle:
        handle.write(PAGE_TEXT)

    environment = dict(
        os.environ,
        PATH=binaries + os.pathsep + os.environ.get("PATH", ""),
        DISPLAY=":99",
        FAKE_STATE=os.path.join(work, "state"),
        FAKE_PAGE=page,
        WIN_X=str(win[0]), WIN_Y=str(win[1]),
        BOX_Y=str(box_y), BOX_X1=str(box_x1), BOX_X2=str(box_x2),
        # No waiting: the delays are tested in test_delays.py, and at full
        # speed this simulation takes minutes.
        SEARCH_FIELD_DELAY_SECONDS="0", KEY_DELAY_MS="0",
        POLL_INTERVAL="0.01", CLIPBOARD_TIMEOUT="1",
        FIELD_PROBE_PAUSE_SCALE="0",
    )
    done = subprocess.run(
        ["bash", os.path.join(SHELL, "verify_search_fields.sh"),
         "--window", "1",
         "--what-xy", "%d,%d" % (box_x1, guess_y),
         "--where-xy", "%d,%d" % (box_x2, guess_y)] + list(extra),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, timeout=300)

    results = {}
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("RESULT:") and "=" in line:
            name, _, value = line[len("RESULT:"):].partition("=")
            results[name] = value

    clicks = []
    try:
        with open(os.path.join(work, "state.clicks"), encoding="utf-8") as fh:
            clicks = [tuple(int(part) for part in line.split())
                      for line in fh if line.strip()]
    except OSError:
        pass

    boxes = {}
    for which in ("what", "where"):
        path = os.path.join(work, "state.%s" % which)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                boxes[which] = handle.read()

    shutil.rmtree(work, ignore_errors=True)
    _RUNS[key] = {"exit": done.returncode, "results": results,
                  "stderr": done.stderr.decode("utf-8", "replace"),
                  "clicks": clicks, "boxes": boxes}
    return _RUNS[key]


#: The window the simulation places Firefox in -- the position measured on
#: 2026-11-10, when it was asked for +0+34.
WIN_X, WIN_Y = 70, 27

#: A short limit for the "no form on the page" runs. The real default is
#: checked statically in test_regressions.py; running 26 probes six times
#: here would add a minute for nothing.
SHORT = ("--probe-limit", "8")


class FieldScanCase(unittest.TestCase):
    """Convenience wrapper so each test reads as one simulation."""

    def run_verify(self, box_y, guess_y, extra=(), box_x1=770, box_x2=1170):
        run = simulate(box_y, guess_y, tuple(extra), box_x1, box_x2,
                       (WIN_X, WIN_Y))
        return run["exit"], run["results"], run["stderr"]

    WIN_X = WIN_X
    WIN_Y = WIN_Y


class TestItFindsAMovedBox(FieldScanCase):
    """The measured failure: the box was ~30px below where it was clicked."""

    def test_it_finds_the_box_and_reports_where(self):
        code, results, _err = self.run_verify(box_y=263, guess_y=233)
        self.assertEqual(code, 0)
        self.assertEqual(results["verified"], "yes")
        self.assertEqual(results["what_ok"], "yes")
        self.assertEqual(results["where_ok"], "yes")
        learned_y = int(results["learned_what_xy"].split(",")[1])
        self.assertTrue(263 <= learned_y <= 263 + 24,
                        "learned y %d is not inside the box" % learned_y)

    def test_it_takes_only_a_few_probes(self):
        """Nearest-first: a 30px error must not cost a full sweep."""
        _code, results, _err = self.run_verify(box_y=263, guess_y=233)
        self.assertLessEqual(int(results["probes"]), 8)

    def test_the_location_box_is_found_on_the_keyword_boxs_row(self):
        code, results, _err = self.run_verify(box_y=263, guess_y=233)
        self.assertEqual(code, 0)
        self.assertEqual(results["learned_what_xy"].split(",")[1],
                         results["learned_where_xy"].split(",")[1])

    def test_an_already_correct_guess_costs_one_probe_each(self):
        """What the remembered offset buys on every later keyword."""
        _code, results, _err = self.run_verify(box_y=263, guess_y=270)
        self.assertEqual(results["verified"], "yes")
        self.assertEqual(int(results["probes"]), 2)

    def test_it_finds_a_box_that_moved_sideways(self):
        code, results, _err = self.run_verify(box_y=263, guess_y=263,
                                              box_x1=1010, box_x2=1410)
        self.assertEqual(code, 0, "a sideways miss must also be found")
        self.assertEqual(results["verified"], "yes")


class TestItReportsAMissWithoutDumpingThePage(FieldScanCase):
    """The reporting half of the fault: 4KB of Indeed, twice per retry."""

    LIMIT = SHORT

    def test_a_page_with_no_search_form_fails_cleanly(self):
        code, results, err = self.run_verify(box_y=9000, guess_y=233,
                                             extra=SHORT)
        self.assertNotEqual(code, 0)
        self.assertEqual(results["verified"], "no")
        self.assertEqual(results["what_ok"], "no")

    def test_the_probe_count_is_bounded(self):
        """Without a limit, a page with no form scans until the timeout."""
        _code, results, _err = self.run_verify(box_y=9000, guess_y=233,
                                               extra=SHORT)
        self.assertEqual(int(results["probes"]), 8)

    def test_no_result_line_carries_the_page(self):
        """A RESULT line is line-based; a page copy would corrupt the rest.

        This is the invariant that matters: the protocol is "one RESULT per
        line", and a whole-page read-back used to be emitted raw -- 120
        lines sprayed through it, every later RESULT unparseable.
        """
        _code, results, _err = self.run_verify(box_y=9000, guess_y=233,
                                             extra=SHORT)
        self.assertTrue(results, "nothing was emitted at all")
        for key, value in results.items():
            self.assertNotIn("\n", value, key)

    def test_the_read_back_values_are_short(self):
        """The diagnosis may be a long sentence; a read-back may not be.

        Checked separately from the line-based invariant above, because
        RESULT:error= is legitimately a paragraph of explanation -- on one
        line -- and conflating the two hides which is being asserted.
        """
        _code, results, _err = self.run_verify(box_y=9000, guess_y=233,
                                             extra=SHORT)
        for key in ("what_read", "where_read"):
            self.assertLess(len(results[key]), 120,
                            "%s=%s" % (key, results[key][:80]))

    def test_the_read_back_is_named_as_page_text(self):
        _code, results, _err = self.run_verify(box_y=9000, guess_y=233,
                                             extra=SHORT)
        self.assertIn("PAGE TEXT", results["what_read"])

    def test_the_error_does_not_quote_the_page(self):
        _code, _results, err = self.run_verify(box_y=9000, guess_y=233,
                                             extra=SHORT)
        self.assertIn("ERROR", err)
        self.assertNotIn("Photoshop Designers", err,
                         "the page must not be pasted into the error")
        self.assertNotIn("Welcome, rohan", err)
        # One line of diagnosis, not a transcript.
        error_lines = [line for line in err.splitlines() if "ERROR" in line]
        self.assertEqual(len(error_lines), 1)

    def test_it_says_the_click_landed_on_the_body(self):
        _code, _results, err = self.run_verify(box_y=9000, guess_y=233,
                                             extra=SHORT)
        self.assertIn("page body", err)


class TestItNeverProbesFirefoxsChrome(FieldScanCase):
    """A probe in the ADDRESS BAR returns the probe and looks like success.

    The run would then "learn" the address bar as the keyword box, type
    "Product Consultant" into it, and press Return -- navigating to the
    keyword as a url. The floor is a safety property.
    """

    def test_the_floor_sits_below_the_chrome(self):
        _code, results, _err = self.run_verify(box_y=263, guess_y=233)
        self.assertEqual(int(results["scan_floor"]),
                         self.WIN_Y + 120)

    def test_nothing_above_the_floor_is_ever_clicked(self):
        run = simulate(9000, 233, SHORT, 770, 1170, (WIN_X, WIN_Y))
        ys = [y for _x, y in run["clicks"]]
        self.assertTrue(ys, "the scan clicked nothing at all")
        self.assertGreaterEqual(min(ys), WIN_Y + 120,
                                "a probe reached into Firefox's chrome")

    def test_a_box_only_reachable_in_the_chrome_is_not_found(self):
        """Refusing to look is the correct answer here, not finding it."""
        code, results, _err = self.run_verify(box_y=100, guess_y=130,
                                              extra=["--scan-reach", "60"])
        self.assertNotEqual(code, 0)
        self.assertEqual(results["verified"], "no")


class TestItLeavesNothingBehind(FieldScanCase):

    def test_the_probe_is_cleared_out_of_both_boxes(self):
        """A leftover probe would prefix the next real keyword."""
        run = simulate(263, 233, (), 770, 1170, (WIN_X, WIN_Y))
        self.assertEqual(run["exit"], 0)
        for which, content in run["boxes"].items():
            self.assertEqual(content.strip(), "",
                             "the %s box still holds the probe" % which)


if __name__ == "__main__":
    unittest.main(verbosity=2)
