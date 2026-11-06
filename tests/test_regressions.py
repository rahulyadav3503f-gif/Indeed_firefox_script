"""Guards for the faults found in the first live run.

Each test here exists because something actually went wrong on 2026-11-05,
and each one fails if that specific fault comes back.  They are deliberately
cheap -- static checks on the shell scripts and recorded calls against the
controller -- so they run without a browser.
"""

import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from source_file import indeed_controller as ctrl             # noqa: E402

SHELL = os.path.join(BASE, "shell_scripts")


def script(name):
    with open(os.path.join(SHELL, name), encoding="utf-8") as handle:
        return handle.read()


def code_of(text):
    """The script with comment lines removed, so prose cannot satisfy a test."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


# ===========================================================================
# PROBLEM 1 -- the mandatory listing-page Ctrl+A/Ctrl+C is gone
# ===========================================================================

class TestNoListingPageCopy(unittest.TestCase):
    """ERROR(8): "Ctrl+C did not change the clipboard" must be impossible
    on the search path, because the search path no longer copies the page."""

    def test_search_jobs_never_copies_the_whole_page(self):
        body = code_of(script("search_jobs.sh"))
        self.assertNotIn("copy_page_text", body)

    def test_search_jobs_cannot_fail_on_a_stale_clipboard(self):
        body = code_of(script("search_jobs.sh"))
        self.assertNotIn("EX_CLIPBOARD_STALE", body)
        self.assertNotIn("EX_CLIPBOARD_EMPTY", body)

    def test_search_jobs_does_not_write_listing_data(self):
        body = code_of(script("search_jobs.sh"))
        self.assertNotIn("listing_text_file", body)
        self.assertNotIn("listing_chars", body)

    def test_the_controller_no_longer_asks_for_a_listing_file(self):
        source = open(os.path.join(BASE, "source_file",
                                   "indeed_controller.py"),
                      encoding="utf-8").read()
        search = source.split("def search(")[1].split("\n    def ")[0]
        # Look at the CODE, not the docstring -- which explains at length
        # what --temp-file used to do and must stay free to say so.
        body = search.split('"""')[2]
        self.assertNotIn("--temp-file", body)
        self.assertNotIn("listing_data.txt", body)

    def test_an_access_refusal_is_still_detected_from_the_title(self):
        """The listing copy is gone, but refusal handling is NOT."""
        body = code_of(script("search_jobs.sh"))
        self.assertIn("title_says_access_denied", body)

    def test_a_still_needed_clipboard_read_survives(self):
        """Field read-back and address-bar reads must NOT have been removed."""
        body = code_of(script("search_jobs.sh"))
        self.assertIn("_copy_with_nonce", body)      # reads a search field
        self.assertIn("assert_input_lands", body)    # reads the address bar


# ===========================================================================
# PROBLEM 2 -- job-card selection
# ===========================================================================

class TestCardSelection(unittest.TestCase):

    def test_there_is_no_card_pitch_anywhere(self):
        """A fixed pitch cannot describe Indeed's variable-height cards."""
        body = code_of(script("select_job_card.sh"))
        self.assertNotIn("CARD_PITCH", body)
        self.assertNotIn("card_pitch", body)
        config = open(os.path.join(BASE, "source_file",
                                   "indeed_controller.py"),
                      encoding="utf-8").read()
        self.assertNotIn("self.card_pitch", config)

    def test_the_script_probes_rather_than_multiplying_an_index(self):
        body = code_of(script("select_job_card.sh"))
        self.assertIn("PROBE_STEP", body)
        self.assertIn("learned_card_y", body)
        self.assertNotIn("INDEX * ", body.upper().replace("INDEX*", "INDEX * "))

    def test_a_preselected_job_is_accepted_without_clicking(self):
        body = code_of(script("select_job_card.sh"))
        self.assertIn("selection_method=preselected", body)
        self.assertIn("--preselected-key", script("select_job_card.sh"))

    def test_an_unchanged_key_is_a_miss_not_a_fatal_error(self):
        """The old script raised "SAME job" and abandoned the keyword."""
        body = code_of(script("select_job_card.sh"))
        self.assertNotIn("resolves to the SAME job", body)

    def test_navigating_away_from_the_listing_is_undone(self):
        body = code_of(script("select_job_card.sh"))
        self.assertIn("alt+Left", body)

    def test_the_main_loop_is_zero_based(self):
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        self.assertIn("for card_index in range(0, MAX_CARDS_PER_PAGE)", source)
        self.assertNotIn("for card_index in range(1, MAX_CARDS_PER_PAGE + 1)",
                         source)


class TestCardSelectionCalls(unittest.TestCase):
    """What the controller actually passes to the shell."""

    class Recorder(ctrl.IndeedController):
        def __init__(self, config, results):
            super(TestCardSelectionCalls.Recorder, self).__init__(config)
            self.listing_window = "999"
            self.calls = []
            self._results = results

        def run_script(self, name, args, timeout=None, allow_codes=()):
            self.calls.append((name, list(args)))
            return 0, self._results, ""

        def log(self, message):
            pass

    def make(self, results):
        config = ctrl.ControllerConfig(project_dir=BASE, verbose=False)
        return self.Recorder(config, results)

    def test_the_preselected_key_is_passed_for_card_zero(self):
        controller = self.make({"selected_url": "x?vjk=aaa",
                                "selected_key": "aaa",
                                "selection_method": "preselected"})
        controller.preselected_key = "aaa"
        controller.select_job_card(0)
        args = controller.calls[0][1]
        self.assertIn("--preselected-key", args)
        self.assertEqual(args[args.index("--preselected-key") + 1], "aaa")

    def test_the_preselected_key_is_not_passed_for_later_cards(self):
        controller = self.make({"selected_url": "x?vjk=bbb",
                                "selected_key": "bbb"})
        controller.preselected_key = "aaa"
        controller.select_job_card(3)
        self.assertNotIn("--preselected-key", controller.calls[0][1])

    def test_card_zero_without_a_preselected_key_still_works(self):
        """Now that the search no longer WAITS for vjk=, it may be absent.

        The controller must simply not pass --preselected-key, and the
        shell then falls back to the key in the url, or to clicking.
        """
        controller = self.make({"selected_url": "x?vjk=zzz",
                                "selected_key": "zzz",
                                "selection_method": "click",
                                "learned_card_y": "455"})
        controller.preselected_key = ""          # search found none
        window = controller.select_job_card(0)
        self.assertNotIn("--preselected-key", controller.calls[0][1])
        self.assertEqual(window.job_key, "zzz")
        self.assertEqual(window.selection_method, "click")

    def test_seen_keys_are_passed_so_a_probe_cannot_recollect(self):
        controller = self.make({"selected_url": "x?vjk=ccc",
                                "selected_key": "ccc"})
        controller.select_job_card(2, seen_keys=["aaa", "bbb"])
        args = controller.calls[0][1]
        self.assertIn("--seen-keys", args)
        self.assertEqual(args[args.index("--seen-keys") + 1], "aaa,bbb")

    def test_the_learned_y_comes_back_for_the_next_probe(self):
        controller = self.make({"selected_url": "x?vjk=ddd",
                                "selected_key": "ddd",
                                "learned_card_y": "712",
                                "selection_method": "click"})
        window = controller.select_job_card(1, start_y=600)
        self.assertEqual(window.learned_card_y, 712)
        self.assertEqual(window.selection_method, "click")
        args = controller.calls[0][1]
        self.assertEqual(args[args.index("--start-y") + 1], "600")


# ===========================================================================
# PROBLEM 13 -- normal window, never fullscreen
# ===========================================================================

class TestNoFullscreen(unittest.TestCase):

    def test_no_script_requires_fullscreen(self):
        for name in os.listdir(SHELL):
            if not name.endswith(".sh"):
                continue
            with self.subTest(script=name):
                self.assertNotIn("require_fullscreen", code_of(script(name)))

    def test_no_script_presses_f11_to_enter_fullscreen(self):
        """Only exit_fullscreen_if_set() may send F11, and only to LEAVE."""
        for name in os.listdir(SHELL):
            if name == "_common.sh" or not name.endswith(".sh"):
                continue
            with self.subTest(script=name):
                self.assertNotIn("F11", code_of(script(name)))

    def test_open_firefox_sizes_a_normal_window(self):
        body = code_of(script("open_firefox.sh"))
        self.assertIn("exit_fullscreen_if_set", body)
        self.assertIn("set_window_geometry", body)
        self.assertIn("require_window_ready", body)
        self.assertIn('emit "fullscreen=no"', body)

    def test_the_window_defaults_match_the_screenshot(self):
        config = ctrl.ControllerConfig(project_dir=BASE)
        self.assertEqual(config.window_size, (1845, 1046))
        self.assertEqual(config.window_pos, (0, 34))

    def test_a_too_small_window_is_refused_rather_than_clicked_into(self):
        body = code_of(script("_common.sh"))
        self.assertIn("MIN_WINDOW_WIDTH", body)
        self.assertIn("EX_WINDOW_GEOMETRY", body)


# ===========================================================================
# PROBLEM 4 -- the search uses the real fields
# ===========================================================================

class TestFormSearch(unittest.TestCase):

    def test_form_is_the_default_mode(self):
        config = ctrl.ControllerConfig(project_dir=BASE)
        self.assertEqual(config.search_mode, "form")

    def test_the_fields_are_read_back_before_submitting(self):
        body = code_of(script("search_jobs.sh"))
        self.assertIn("typed_keyword", body)
        self.assertIn("typed_city", body)
        # and a mismatch must stop the search
        self.assertIn("Nothing was submitted", script("search_jobs.sh"))

    def test_the_url_dropdown_is_dismissed_before_clicking_the_page(self):
        """Ctrl+L opens a panel that COVERS the page.

        Measured: with it open, the click aimed at Indeed's keyword box
        landed on the "YouTube - youtube.com" row of the dropdown and the
        browser navigated there.  Three live runs died this way.
        """
        common = script("_common.sh")
        self.assertIn("dismiss_url_dropdown", common)
        guard = common.split("assert_input_lands() {")[1]
        self.assertIn("dismiss_url_dropdown", guard.split("return 0")[0])
        field = script("search_jobs.sh").split("type_into_field() {")[1]
        self.assertIn("dismiss_url_dropdown", field.split("note ")[0])

    def test_the_page_is_given_time_to_settle_before_typing(self):
        """Indeed keeps laying out after 'loaded'; the boxes move while it does."""
        body = code_of(script("search_jobs.sh"))
        form = body.split("case \"$MODE\" in")[1].split("url)")[0]
        self.assertIn("SEARCH_FIELD_DELAY_SECONDS", form)
        self.assertIn("sleep", form.split("type_into_field")[0])

    def test_the_settle_defaults_to_seven_seconds(self):
        common = script("_common.sh")
        self.assertIn('SEARCH_FIELD_DELAY_SECONDS:=7', common)
        config = ctrl.ControllerConfig(project_dir=BASE)
        self.assertEqual(config.search_field_delay_seconds, 7.0)
        self.assertEqual(config.environment()["SEARCH_FIELD_DELAY_SECONDS"],
                         "7.0")

    def test_an_unreadable_search_box_stops_the_search(self):
        """It used to warn and submit anyway; that navigated to YouTube.

        An empty read-back means the keystrokes never reached our window,
        so the Return that followed went to whatever had focus.
        """
        body = code_of(script("search_jobs.sh"))
        guard = body.split("TYPED_CITY=$(type_into_field")[1]
        self.assertIn("fail", guard.split("submitting")[0])
        self.assertNotIn("submitting anyway", body)

    def test_no_address_bar_read_between_typing_and_return(self):
        """Ctrl+L moves the caret OUT of the city box.

        A guard there made Return re-load the current page instead of
        submitting the search -- measured live: both boxes read back
        correctly and the url never changed. The field read-backs are the
        proof that keystrokes land; they do not move the caret.
        """
        body = code_of(script("search_jobs.sh"))
        typing_to_return = body.split("TYPED_CITY=$(type_into_field")[1]
        typing_to_return = typing_to_return.split("Return")[0]
        self.assertNotIn("assert_input_lands", typing_to_return)
        self.assertNotIn("ctrl+l", typing_to_return)

    def test_the_url_is_no_longer_matched_against_keyword_and_city(self):
        """Removed on request: it blocked searches that had loaded fine."""
        body = code_of(script("search_jobs.sh"))
        self.assertNotIn("KEYWORD_PATTERN", body)
        self.assertNotIn("CITY_PATTERN", body)


# ===========================================================================
# THE Ctrl+U FAILURE -- focus, measured live on 2026-11-06
# ===========================================================================

class TestFocusHandling(unittest.TestCase):
    """ERROR(12) "Ctrl+U did not produce the view-source tab ... <unreadable>".

    Root cause, measured in the real browser: F6 TOGGLES between the address
    bar and the page, and Escape does not leave the address bar.  So
    `Escape; F6` from page focus landed in the ADDRESS BAR, where Ctrl+U is
    the text-field shortcut "delete to start of line" -- it wiped the
    address bar instead of opening view-source.
    """

    def body(self):
        text = script("_common.sh")
        start = text.index("focus_page_content() {")
        return text[start:text.index("\n}", start)]

    def test_focus_starts_from_a_known_state(self):
        """Ctrl+L first: it ALWAYS lands in the address bar."""
        self.assertIn("ctrl+l", self.body())

    def test_focus_does_not_use_escape(self):
        """Escape means STOP LOADING, and it does not move focus anyway."""
        self.assertNotIn("Escape", self.body())

    def test_f6_is_pressed_exactly_once(self):
        """F6 toggles, so a second press would go straight back."""
        self.assertEqual(self.body().count("F6"), 1)

    def test_the_guard_cannot_be_called_in_a_subshell(self):
        """fail() inside $( ) exits only the subshell -- measured.

        The guard used to be `URL=$(assert_input_lands ...)`, so its fail()
        ended the SUBSHELL and the script carried on and clicked anyway.
        It must now be called as a statement and set GUARD_URL.
        """
        common = script("_common.sh")
        self.assertIn("GUARD_URL", common)
        self.assertIn("GUARD_REASON", common)
        for name in ("select_job_card.sh", "search_jobs.sh"):
            with self.subTest(script=name):
                body = code_of(script(name))
                self.assertNotIn("$(assert_input_lands", body)
                self.assertIn("|| fail", body)

    def test_address_bar_reads_are_retried(self):
        common = script("_common.sh")
        self.assertIn("copy_address_bar_retry", common)
        self.assertIn("ADDRESS_BAR_ATTEMPTS", common)


# ===========================================================================
# SIMPLIFIED SEARCH -- no post-Return verification
# ===========================================================================

class TestNoPostSearchVerification(unittest.TestCase):
    """After Return the script waits and goes straight to the first card.

    What was removed: the url had to match q=<keyword> and l=<city>, and a
    vjk= had to appear within 20s, or the search was declared failed. Both
    blocked progression on searches that had in fact loaded.
    """

    def body(self):
        return code_of(script("search_jobs.sh"))

    def test_no_verified_gate_remains(self):
        body = self.body()
        self.assertNotIn('VERIFIED="no"', body)
        self.assertNotIn('[ "$VERIFIED" != "yes" ]', body)

    def test_the_search_does_not_wait_for_a_matching_url(self):
        self.assertNotIn("wait_for_url_match", self.body())

    def test_vjk_is_a_hint_not_a_gate(self):
        """preselected_key must still be emitted -- card 0 uses it."""
        self.assertIn("preselected_key=", self.body())

    def test_the_only_stop_after_return_is_an_access_refusal(self):
        """Everything else must fall through to card selection.

        Counted rather than described: exactly one fail() may survive
        after the results wait, and it must be the EX_ACCESS_DENIED one.
        """
        after_return = self.body().split("SEARCH_RESULTS_WAIT_SECONDS")[-1]
        fails = [line for line in after_return.splitlines()
                 if "fail " in line]
        self.assertEqual(len(fails), 1, "unexpected fail()s: %r" % fails)
        self.assertIn("EX_ACCESS_DENIED", fails[0])

    def test_an_error_page_no_longer_blocks(self):
        body = self.body()
        self.assertIn("title_says_error_page", body)   # still reported
        error_branch = body.split("title_says_error_page")[1].split("fi")[0]
        self.assertIn("warn", error_branch)
        self.assertNotIn("fail", error_branch)

    def test_the_results_wait_is_configurable_and_ten_seconds(self):
        self.assertIn("SEARCH_RESULTS_WAIT_SECONDS", self.body())
        self.assertIn('SEARCH_RESULTS_WAIT_SECONDS:=10', script("_common.sh"))
        config = ctrl.ControllerConfig(project_dir=BASE)
        self.assertEqual(config.search_results_wait_seconds, 10.0)
        self.assertEqual(
            config.environment()["SEARCH_RESULTS_WAIT_SECONDS"], "10.0")

    def test_the_identity_safeguards_downstream_are_untouched(self):
        """Removing the search checks must not let wrong data into Excel."""
        self.assertIn("--expect-url", script("save_page_source.sh"))
        self.assertIn("EX_IDENTITY", code_of(script("save_page_source.sh")))
        self.assertIn("selected_key", code_of(script("select_job_card.sh")))
        source = open(os.path.join(BASE, "source_file", "indeed_source.py"),
                      encoding="utf-8").read()
        self.assertIn("job_card_for_key", source)

    def test_the_input_guard_before_typing_is_untouched(self):
        """Wrong-window protection is NOT part of what was removed."""
        body = self.body()
        self.assertIn("assert_input_lands", body)
        self.assertIn("REFUSING to type", body)


# ===========================================================================
# PROBLEMS 5, 6, 7 -- what the terminal says
# ===========================================================================

class TestBanner(unittest.TestCase):

    def setUp(self):
        self.source = open(os.path.join(BASE, "find_indeed_job.py"),
                           encoding="utf-8").read()

    def test_the_browser_is_named_firefox(self):
        self.assertIn("NEW INDEED COLLECTOR -- Firefox / xdotool / xclip",
                      self.source)
        self.assertNotIn("COLLECTOR -- Opera", self.source)

    def test_the_keyword_label_no_longer_calls_track_b_other_it(self):
        """1,064 fresher keywords across 116 departments are not "other IT"."""
        self.assertNotIn("other IT", self.source)
        self.assertIn("fresher/other", self.source)

    def test_the_counts_are_not_hardcoded(self):
        banner = self.source.split("def show_banner(")[1].split("\ndef ")[0]
        for number in ("1264", "200", "1064"):
            self.assertNotIn(number, banner)

    def test_provenance_separates_local_roles_from_the_imported_schema(self):
        import upstream
        described = upstream.describe()
        self.assertIn("vendor/", described)
        self.assertIn("row builder", described)


if __name__ == "__main__":
    unittest.main(verbosity=2)
