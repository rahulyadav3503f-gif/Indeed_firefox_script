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

    def test_the_url_dropdown_is_closed_before_every_probe_click(self):
        """The read that checks the selection is what re-opens the panel.

        Each probe reads the url with Ctrl+L to see whether the selection
        changed; Ctrl+L opens the suggestion dropdown OVER the page. The
        next probe then clicks a dropdown row instead of a job card and
        Firefox follows the suggestion -- measured, twice, landing on
        youtube.com and wikipedia.org.
        """
        body = code_of(script("select_job_card.sh"))
        loop = body.split("PROBES_THIS_ROUND=0\nwhile :;")[1].split("\ndone")[0]
        dismiss_at = loop.index("dismiss_url_dropdown")
        click_at = loop.index("xdotool click 1")
        self.assertLess(dismiss_at, click_at,
                        "the dropdown must be dismissed BEFORE the click")

    def test_probing_stops_if_back_does_not_return_to_the_listing(self):
        """One wrong click must not become several."""
        body = code_of(script("select_job_card.sh"))
        recovery = body.split("alt+Left")[1].split("continue")[0]
        self.assertIn("url_is_listing", recovery)
        self.assertIn("fail", recovery)

    def test_the_list_is_scrolled_instead_of_giving_up(self):
        """The column shows 3-4 cards; without scrolling the run stops there.

        Symptom: three cards were collected, then "no more cards", then the
        loop moved on and searched again -- never reaching the rest of the
        page.
        """
        body = code_of(script("select_job_card.sh"))
        self.assertIn("scroll_results_column", body)
        self.assertIn("SCROLL_ROUNDS", body)
        # and the give-up must come AFTER scrolling is exhausted
        giveup = body.split('no_more_cards=yes')[0]
        self.assertIn("SCROLLS -ge", giveup.replace('"', ''))

    def test_the_probe_budget_is_per_scroll_round(self):
        """A total budget defeats scrolling.

        Measured: PROBE_LIMIT=12 was spent on the first screenful, so only
        ONE scroll ever happened and the page was called exhausted with
        most of its cards still below the fold.
        """
        body = code_of(script("select_job_card.sh"))
        self.assertIn("PROBES_THIS_ROUND", body)
        self.assertIn("PROBES_THIS_ROUND=0", body)
        self.assertNotIn('while [ "$PROBES" -lt "$PROBE_LIMIT" ]', body)

    def test_scrolling_uses_the_wheel_over_the_card_column(self):
        body = code_of(script("select_job_card.sh"))
        fn = body.split("scroll_results_column() {")[1].split("\n}")[0]
        self.assertIn("mousemove", fn)
        self.assertIn("click --clearmodifiers 5", fn)   # wheel down
        self.assertIn("dismiss_url_dropdown", fn)

    def test_a_scroll_resets_the_callers_probe_start(self):
        """A y learned before a scroll describes a view that is gone."""
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        self.assertIn('getattr(window, "scrolled", False)', source)
        block = source.split('getattr(window, "scrolled", False)')[1][:300]
        self.assertIn("FIRST_CARD_Y", block)

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


class TestSaveDialogRetry(unittest.TestCase):
    """One card in eight left the dialog open with nothing typed in it."""

    def test_the_dialog_is_re_driven_once_if_no_file_arrives(self):
        body = code_of(script("save_page_source.sh"))
        self.assertIn("drive_save_dialog", body)
        self.assertEqual(body.count("drive_save_dialog\n"), 2,
                         "expected the initial drive plus exactly one retry")

    def test_the_retry_only_happens_while_the_dialog_is_still_open(self):
        """If the dialog has gone, something else happened -- do not guess."""
        body = code_of(script("save_page_source.sh"))
        retry = body.split("SAVED=$(wait_for_saved_file) || SAVED=\"\"")[1]
        self.assertIn("window_exists \"$DIALOG\"", retry)


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
# PER-CARD EXTRACTION -- all 32 fields, from THIS job's own saved file
# ===========================================================================

class TestInlineExtraction(unittest.TestCase):
    """A real run produced, for a job that was none of these things:

        Job Title: Keyword : all jobs
        Company:   Edit location input box label

    Those are the page's accessibility labels. The cause was that
    find_indeed_job.py called build_row_from_file() WITHOUT job_key, so the
    selected job was never isolated out of a 16-job document and the
    visible-text fallback read the furniture.
    """

    def setUp(self):
        self.source = open(os.path.join(BASE, "find_indeed_job.py"),
                           encoding="utf-8").read()

    def test_the_job_key_is_passed_to_the_extractor(self):
        call = self.source.split("build_row_from_file(")[1].split(")")[0]
        self.assertIn("job_key=", call)

    def test_extraction_happens_before_the_tab_closes(self):
        """'...before going to the next job card.'

        Compared against the NORMAL close (controller.close_source_tab,
        the one with the two delays). The force_close_source_tab() calls
        that appear earlier are error paths which abandon the card before
        there is anything to extract.
        """
        card = self.source.split("def process_one_card(")[1].split("\ndef ")[0]
        extract_at = card.index("build_row_from_file(")
        report_at = card.index("log_field_report(")
        save_at = card.index("append_row(")
        close_at = card.index("controller.close_source_tab(")
        self.assertLess(extract_at, report_at)
        self.assertLess(report_at, save_at)
        self.assertLess(save_at, close_at)

    def test_every_column_is_reported_for_every_card(self):
        self.assertIn("def log_field_report(", self.source)
        report = self.source.split("def log_field_report(")[1].split("\ndef ")[0]
        self.assertIn("for column in DETAIL_COLUMNS", report)
        self.assertIn("(blank -- not stated in the saved page)", report)

    def test_a_row_that_could_not_be_isolated_is_refused(self):
        """Better no row than another job's row."""
        card = self.source.split("def process_one_card(")[1]
        self.assertIn('report.isolation == "NONE"', card)
        guard = card.split('report.isolation == "NONE"')[1][:400]
        self.assertIn("CardOutcome.FAILED", guard)

    def test_the_pane_is_preferred_over_the_card_list(self):
        """The pane describes ONE job; the card list describes sixteen."""
        source = open(os.path.join(BASE, "source_file", "indeed_source.py"),
                      encoding="utf-8").read()
        block = source.split("if card is not None:")[1].split("isolation =")[0]
        self.assertLess(block.index("fields_from_job_header"),
                        block.index("fields_from_job_card"))

    def test_the_pane_is_only_used_for_the_job_we_selected(self):
        source = open(os.path.join(BASE, "source_file", "indeed_source.py"),
                      encoding="utf-8").read()
        for function in ("selected_job_header", "selected_job_description"):
            body = source.split("def %s(" % function)[1].split("\ndef ")[0]
            self.assertIn("autoOpenJobAttributes", body)
            self.assertIn("opened == job_key", body)


class TestExcelDependencies(unittest.TestCase):
    """saved_jobs stayed 0 while every job logged
       "Excel Save: FAILED (ModuleNotFoundError: No module named 'openpyxl')"

    Cause: a venv with include-system-site-packages=false that had pandas
    but not openpyxl. pandas imports fine, so nothing complained until
    to_excel ran -- once per job, after all the work was already done.
    """

    def test_the_check_exists_and_names_both_requirements(self):
        import find_indeed_job as collector
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        body = source.split("def check_excel_dependencies(")[1].split("\ndef ")[0]
        self.assertIn("pandas", body)
        self.assertIn("openpyxl", body)

    def test_it_reports_nothing_missing_when_both_are_present(self):
        import find_indeed_job as collector
        self.assertEqual(collector.check_excel_dependencies(), [])

    def test_the_run_stops_before_opening_a_browser(self):
        """Fail fast: no point driving Firefox if nothing can be saved."""
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        run = source.split("check_excel_dependencies()")[2]
        stop_at = run.index("[STOP] Excel cannot be written")
        browser_at = run.index("build_controller_config(")
        self.assertLess(stop_at, browser_at)

    def test_the_message_names_the_interpreter_to_fix(self):
        """A venv problem is invisible unless the message says which python."""
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        block = source.split("[STOP] Excel cannot be written")[1][:600]
        self.assertIn("sys.executable", block)
        self.assertIn("pip install", block)


class TestApplyAndSourceUrl(unittest.TestCase):
    """apply_url is the job's permalink; source_url is the site constant."""

    def setUp(self):
        from source_file import indeed_extractor as ex
        self.ex = ex
        self.card = ("https://in.indeed.com/jobs?q=full+stack+developer"
                     "&l=Delhi&from=searchOnHP%2Cwhatautocomplete"
                     "&vjk=cba10d8415b155ab")

    def test_the_card_vjk_becomes_a_viewjob_jk_url(self):
        self.assertEqual(self.ex.canonical_job_url(self.card),
                         "https://in.indeed.com/viewjob?jk=cba10d8415b155ab")

    def test_a_bare_job_key_also_works(self):
        self.assertEqual(self.ex.canonical_job_url("d23d5a42e76c50dd"),
                         "https://in.indeed.com/viewjob?jk=d23d5a42e76c50dd")

    def test_nothing_is_invented_without_a_job_key(self):
        self.assertEqual(self.ex.canonical_job_url("https://in.indeed.com/"), "")
        self.assertEqual(self.ex.canonical_job_url(""), "")

    def test_the_row_gets_both_values(self):
        row = {"apply_url": "old", "source_url": "old"}
        out = self.ex.apply_the_window_url(row, self.card)
        self.assertEqual(out["apply_url"],
                         "https://in.indeed.com/viewjob?jk=cba10d8415b155ab")
        self.assertEqual(out["source_url"], "https://in.indeed.com/")

    def test_a_card_url_without_a_key_leaves_the_row_alone(self):
        row = {"apply_url": "kept", "source_url": "kept"}
        out = self.ex.apply_the_window_url(row, "https://in.indeed.com/")
        self.assertEqual(out["apply_url"], "kept")
        self.assertEqual(out["source_url"], "kept")


class TestConstantSourceUrlDoesNotBreakDedup(unittest.TestCase):
    """source_url is the SAME on every row now.

    Both duplicate checks used to compare it, so every job after the first
    collided with it: identity_keys() produced url:https://in.indeed.com/
    for everything, and _already_in_frame() matched the source_url column.
    Measured on ten real captures with ten distinct job keys -- one row was
    written and nine were refused as duplicates of it.
    """

    def rows(self):
        from source_file.indeed_extractor import DETAIL_COLUMNS
        out = []
        for key, title in (("aaaaaaaaaaaaaaa1", "Python Developer"),
                           ("bbbbbbbbbbbbbbb2", "Java Developer"),
                           ("ccccccccccccccc3", "Cloud Engineer")):
            row = {c: "x" for c in DETAIL_COLUMNS}
            row.update(internal_job_id=key, job_id="id-" + key,
                       job_title=title, company_name="Co " + title,
                       apply_url="https://in.indeed.com/viewjob?jk=" + key,
                       source_url="https://in.indeed.com/")
            out.append(row)
        return out

    def test_the_site_constant_is_not_an_identity_key(self):
        from source_file.indeed_validator import identity_keys
        keys = identity_keys(self.rows()[0])
        self.assertNotIn("url:https://in.indeed.com/", keys)
        self.assertIn("url:https://in.indeed.com/viewjob?jk=aaaaaaaaaaaaaaa1",
                      keys)

    def test_different_jobs_are_not_duplicates_of_each_other(self):
        from source_file.indeed_validator import DuplicateIndex, decide
        index = DuplicateIndex()
        for row in self.rows():
            decision = decide(row, index)
            self.assertTrue(decision.should_save,
                            "%s was refused: %s" % (row["job_title"], decision))
            index.mark_saved(row)

    def test_the_same_job_twice_IS_a_duplicate(self):
        from source_file.indeed_validator import DuplicateIndex, decide
        index = DuplicateIndex()
        first = self.rows()[0]
        index.mark_saved(first)
        self.assertFalse(decide(first, index).should_save)

    def test_the_workbook_guard_ignores_a_keyless_url(self):
        import pandas as pd
        from source_file.indeed_excel import _already_in_frame
        rows = self.rows()
        frame = pd.DataFrame([rows[0]])
        self.assertTrue(_already_in_frame(rows[0], frame))   # same job
        self.assertFalse(_already_in_frame(rows[1], frame),  # different job
                         "a shared source_url must not make these duplicates")


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
