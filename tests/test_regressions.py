"""Guards for the faults found in the first live run.

Each test here exists because something actually went wrong on 2026-11-05,
and each one fails if that specific fault comes back.  They are deliberately
cheap -- static checks on the shell scripts and recorded calls against the
controller -- so they run without a browser.
"""

import glob
import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from source_file import indeed_controller as ctrl             # noqa: E402
from source_file import indeed_source as src                  # noqa: E402
import find_indeed_job as collector                           # noqa: E402

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
        """Card 0 must be aimed at.  It used to start at 1 and be skipped.

        The upper bound is now the page census (cards_this_page) rather
        than MAX_CARDS_PER_PAGE -- see TestCardBudget -- but the lower
        bound is the point of this test and is still 0.
        """
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        self.assertIn("for card_index in range(0, cards_this_page)", source)
        self.assertNotIn("for card_index in range(1,", source)


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


class TestIndeedLogin(unittest.TestCase):
    """save_indeed_login.py -- sign in once, in the collector's own profile.

    Indeed asks for a login when paging deeper into results, so without a
    session the run collects a page or two and then stops finding jobs.
    """

    def setUp(self):
        import save_indeed_login as helper
        self.helper = helper

    def test_it_signs_in_to_the_profile_the_collector_opens(self):
        """One profile, or the login lands where nothing will read it."""
        import find_indeed_job as collector
        self.assertEqual(self.helper.profile_dir_for(1),
                         collector.build_controller_config(
                             which_rank=1).profile_dir)

    def imported_modules(self):
        """Top-level module names this script imports.

        Checked with ast, not by searching the text: the docstring says the
        words "password" and "playwright" on purpose -- it explains what
        the script does NOT do and how it differs from the Playwright
        version -- and a text search cannot tell prose from code.
        """
        import ast
        tree = ast.parse(open(os.path.join(BASE, "save_indeed_login.py"),
                              encoding="utf-8").read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_it_never_reads_a_credential(self):
        """No getpass, no credential store -- the browser handles sign-in."""
        self.assertNotIn("getpass", self.imported_modules())
        self.assertNotIn("keyring", self.imported_modules())

    def test_it_does_not_use_playwright(self):
        """This project drives a real Firefox profile, not Playwright."""
        self.assertNotIn("playwright", self.imported_modules())

    def test_login_is_detected_from_the_session_cookies(self):
        self.assertEqual(self.helper.login_evidence({"CTK": "x"}), [])
        self.assertEqual(
            self.helper.login_evidence({"CTK": "x", "PPID": "y", "SOCK": "z"}),
            ["PPID", "SOCK"])

    def test_reading_cookies_does_not_touch_the_live_database(self):
        """It copies the db; Firefox holds a lock on the original."""
        source = open(os.path.join(BASE, "save_indeed_login.py"),
                      encoding="utf-8").read()
        body = source.split("def indeed_cookies(")[1].split("\ndef ")[0]
        self.assertIn("shutil.copy", body)
        self.assertIn("-wal", body)      # uncheckpointed cookies live here

    def test_firefox_is_asked_to_quit_not_killed(self):
        """A killed Firefox can leave the new session unwritten."""
        source = open(os.path.join(BASE, "save_indeed_login.py"),
                      encoding="utf-8").read()
        body = source.split("def close_firefox(")[1].split("\ndef ")[0]
        self.assertIn("os.kill(pid, 15)", body)       # SIGTERM
        self.assertNotIn(", 9)", body)                # never SIGKILL

    def test_a_missing_session_is_reported_but_does_not_block(self):
        """The first page reads fine signed out; say so, do not refuse."""
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        block = source.split("NOT SIGNED IN to Indeed")[1][:700]
        self.assertNotIn("return", block.split("log(\"\")")[0])
        self.assertIn("save_indeed_login.py", block)

    def test_each_rank_has_its_own_profile(self):
        """Deliberate: two ranks on one profile fight over the lock.

        The cost is that a login in rank 1 is invisible to rank 2 -- which
        is what sync_login_to_other_ranks() exists to pay.
        """
        import find_indeed_job as collector
        paths = {collector.build_controller_config(which_rank=r).profile_dir
                 for r in (1, 2, 3)}
        self.assertEqual(len(paths), 3, "ranks must not share a profile")

    def test_the_session_can_be_copied_to_the_other_ranks(self):
        source = open(os.path.join(BASE, "save_indeed_login.py"),
                      encoding="utf-8").read()
        body = source.split("def sync_login_to_other_ranks(")[1].split("\ndef ")[0]
        # the write-ahead log holds the newest half of a fresh session
        self.assertIn("cookies.sqlite-wal", source)
        self.assertIn("COOKIE_FILES", body)

    def test_a_rank_with_firefox_running_is_skipped_not_overwritten(self):
        """Firefox would write its own copy back over ours on exit."""
        source = open(os.path.join(BASE, "save_indeed_login.py"),
                      encoding="utf-8").read()
        body = source.split("def sync_login_to_other_ranks(")[1].split("\ndef ")[0]
        guard = body.split("firefox_pids(target)")[1][:300]
        self.assertIn("skipped.append", guard)
        self.assertIn("continue", guard)

    def test_a_stale_wal_on_the_target_is_removed(self):
        """Replaying it would undo the session we just copied."""
        source = open(os.path.join(BASE, "save_indeed_login.py"),
                      encoding="utf-8").read()
        body = source.split("def sync_login_to_other_ranks(")[1].split("\ndef ")[0]
        self.assertIn("os.remove(target_file)", body)

    def test_sync_only_refuses_when_the_source_is_not_signed_in(self):
        """Copying a logged-out profile over the others would undo them."""
        source = open(os.path.join(BASE, "save_indeed_login.py"),
                      encoding="utf-8").read()
        block = source.split("if args.sync_only:")[1][:500]
        self.assertIn("is not signed in", block)
        self.assertIn("return 4", block)

    def test_the_collector_tells_you_about_the_per_rank_profile(self):
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        warning = source.split("NOT SIGNED IN to Indeed")[1][:900]
        self.assertIn("--sync-only", warning)
        self.assertIn("--rank", warning)

    def test_the_marker_records_no_session(self):
        """The marker is a receipt, not a credential store."""
        source = open(os.path.join(BASE, "save_indeed_login.py"),
                      encoding="utf-8").read()
        body = source.split("def write_marker(")[1].split("\ndef ")[0]
        self.assertIn("login_cookies_found", body)
        self.assertNotIn("value", body)   # names only, never cookie values


class TestFixedPlan(unittest.TestCase):
    """A fixed number of pages x a fixed number of cards."""

    def test_both_numbers_exist_and_are_the_ones_used(self):
        import find_indeed_job as collector
        self.assertEqual(collector.MAX_LISTING_PAGES,
                         collector.FIXED_LISTING_PAGES)
        self.assertEqual(collector.MAX_CARDS_PER_PAGE,
                         collector.FIXED_CARDS_PER_PAGE)

    def test_the_unique_target_cannot_truncate_the_fixed_plan(self):
        """A second budget smaller than the plan would silently cap it."""
        import find_indeed_job as collector
        self.assertGreaterEqual(
            collector.TARGET_UNIQUE_JOBS,
            collector.FIXED_LISTING_PAGES * collector.FIXED_CARDS_PER_PAGE)

    def test_the_fixed_count_is_the_ceiling_on_one_page(self):
        """A long page gives FIXED_CARDS_PER_PAGE and no more.

        The loop is bounded by the page census now, so the fixed number is
        a CAP rather than a target: a page with forty cards still yields
        ten.  (A page with five yields five -- see TestCardBudget.)
        """
        import find_indeed_job as collector
        census = collector.PageCensus(["%016x" % n for n in range(40)],
                                      "results-array", 40, 400)
        count, stop, _last = collector.card_budget_for_page(census, 1, 0, [])
        self.assertEqual(count, collector.FIXED_CARDS_PER_PAGE)
        self.assertEqual(stop, "")


class TestUrlPaging(unittest.TestCase):
    """Page 2+ is page 1's url with vjk= dropped and start= set.

    The bug this replaced: --start was only honoured in `url` mode, and
    the default is `form` mode, so every "next page" re-ran the same form
    search and came back with page 1.
    """

    FIRST = ("https://in.indeed.com/jobs?q=desktop+support+engineer"
             "&l=Chennai%2C+Tamil+Nadu&radius=25"
             "&from=searchOnDesktopSerp%2Cwhatautocomplete"
             "&vjk=5a6f2e4d08b08903")

    def url(self, page):
        from source_file.indeed_controller import listing_page_url
        return listing_page_url(self.FIRST, page)

    def test_page_one_has_no_start(self):
        self.assertNotIn("start=", self.url(1))

    def test_later_pages_step_by_ten(self):
        for page, offset in ((2, 10), (3, 20), (4, 30), (5, 40)):
            with self.subTest(page=page):
                self.assertTrue(self.url(page).endswith("&start=%d" % offset))

    def test_vjk_is_dropped(self):
        """It names a job on page 1, which is not on page 2."""
        for page in (1, 2, 3):
            self.assertNotIn("vjk=", self.url(page))

    def test_the_searchs_own_parameters_survive(self):
        """radius above all -- a different radius is a different search."""
        page_two = self.url(2)
        for fragment in ("q=desktop+support+engineer",
                         "l=Chennai%2C+Tamil+Nadu",
                         "radius=25",
                         "from=searchOnDesktopSerp%2Cwhatautocomplete"):
            self.assertIn(fragment, page_two)

    def test_it_matches_the_example_exactly(self):
        self.assertEqual(
            self.url(2),
            "https://in.indeed.com/jobs?q=desktop+support+engineer"
            "&l=Chennai%2C+Tamil+Nadu&radius=25"
            "&from=searchOnDesktopSerp%2Cwhatautocomplete&start=10")

    def test_an_empty_first_page_url_yields_nothing(self):
        """No page 1 url means no page 2 -- never a guessed one."""
        from source_file.indeed_controller import listing_page_url
        self.assertEqual(listing_page_url("", 2), "")
        self.assertEqual(listing_page_url(None, 3), "")

    def test_page_one_is_a_search_and_later_pages_are_urls(self):
        source = open(os.path.join(BASE, "find_indeed_job.py"),
                      encoding="utf-8").read()
        loop = source.split("while page <= MAX_LISTING_PAGES")[1][:1400]
        self.assertIn("if page == 1 or not first_page_url", loop)
        self.assertIn("controller.search(", loop)
        self.assertIn("controller.goto_listing_page(first_page_url, page)",
                      loop)

    def test_the_page_turn_is_verified(self):
        """Landing on page 1 again would re-collect it under page 2's name."""
        body = code_of(script("goto_listing_page.sh"))
        self.assertIn("--expect-start", body)
        self.assertIn("The page did not turn", script("goto_listing_page.sh"))

    def test_turning_a_page_is_guarded_like_any_other_typing(self):
        body = code_of(script("goto_listing_page.sh"))
        self.assertIn("assert_input_lands", body)


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


# ===========================================================================
# THE PAGE CENSUS -- how many cards is this results page actually showing?
# ===========================================================================
# A live search returned FIVE job cards while FIXED_CARDS_PER_PAGE said ten,
# so the collector probed empty space five times and called it "no more
# cards".  And `start=10` on a one-page search serves page 1 again, which
# was then collected a second time and discarded card by card as duplicates.
#
# The fix reads the card list out of the page's own saved source.  These
# tests pin the three behaviours that matter: count what is there, take all
# of it when it is short, and recognise a repeated page.

def _mosaic(keys, job_count=None):
    """A results page shaped like the real one, with `keys` as its cards."""
    cards = ", ".join('{"jobkey": "%s", "title": "Job %d"}' % (key, n)
                      for n, key in enumerate(keys))
    count = '' if job_count is None else ', "jobCount": %d' % job_count
    return ('<html><script>window.mosaic["mosaic-provider-jobcards"] = '
            '{"metaData": {"mosaicProviderJobCardsModel": '
            '{"results": [%s]}}%s};</script></html>' % (cards, count))


class TestPageCards(unittest.TestCase):
    """indeed_source.page_cards() -- the card list, read off the page."""

    def test_the_cards_are_counted_in_page_order(self):
        keys = ["%016x" % (0x1111111111111110 + n) for n in range(5)]
        found = src.page_cards(_mosaic(keys, job_count=5))
        self.assertEqual(found.keys, keys)
        self.assertEqual(found.evidence, "results-array")
        self.assertEqual(found.declared_count, 5)

    def test_a_repeated_card_is_counted_once(self):
        key = "a" * 16
        found = src.page_cards(_mosaic([key, key]))
        self.assertEqual(found.keys, [key])

    def test_the_jobkey_scan_is_the_fallback(self):
        """No results array -- the keys the json mentions are better than 0."""
        html = '<html><script>x = {"jobkey":"%s"};y={"jobKey":"%s"}</script>' \
            % ("c" * 16, "d" * 16)
        found = src.page_cards(html)
        self.assertEqual(found.keys, ["c" * 16, "d" * 16])
        self.assertEqual(found.evidence, "jobkey-scan")

    def test_an_unreadable_page_reports_unknown_not_zero_jobs(self):
        """The whole safety of the feature rests on this distinction."""
        for html in ("", "<html>no json here</html>", None):
            found = src.page_cards(html)
            self.assertEqual(found.keys, [])
            self.assertEqual(found.evidence, "none")
            self.assertIsNone(found.declared_count)

    def test_it_agrees_with_the_real_saved_pages(self):
        """MEASURED: these files carry 5 cards, and the page says jobCount 5."""
        saved = sorted(glob.glob(os.path.join(BASE, "Temp_Data", "rank_*",
                                              "job_*.html")))
        if not saved:
            self.skipTest("no saved listing sources in Temp_Data to check")
        for path in saved:
            found = src.page_cards(src.read_saved_source(path))
            self.assertTrue(found.keys, "%s: no cards found" % path)
            self.assertEqual(found.evidence, "results-array", path)
            if found.declared_count is not None:
                self.assertEqual(len(found.keys), found.declared_count,
                                 "%s: %d cards but the page says %s"
                                 % (path, len(found.keys),
                                    found.declared_count))


class TestCardBudget(unittest.TestCase):
    """find_indeed_job.card_budget_for_page() -- what to do with the count."""

    def budget(self, keys, page=1, seen=(), declared=None, matches=None,
               start_at=None, evidence="results-array"):
        """(count, stop_reason, last_page) for a page shaped like this."""
        if matches is None:
            # Enough matches that the match-count signal never fires, so a
            # test can exercise the card-list backstop on its own.
            matches = 10000
        if start_at is None:
            start_at = (page - 1) * collector.INDEED_PAGE_STEP
        census = collector.PageCensus(keys, evidence if keys else "none",
                                      declared, matches)
        return collector.card_budget_for_page(census, page, start_at,
                                              list(seen))

    def test_a_short_page_is_taken_whole(self):
        count, stop, _last = self.budget(["%016x" % n for n in range(5)],
                                         declared=5)
        self.assertEqual(count, 5)
        self.assertEqual(stop, "")

    def test_a_full_page_is_capped_at_the_fixed_number(self):
        many = ["%016x" % n for n in range(40)]
        count, stop, last = self.budget(many)
        self.assertEqual(count, collector.FIXED_CARDS_PER_PAGE)
        self.assertEqual(stop, "")
        self.assertFalse(last)

    def test_the_same_cards_as_an_earlier_page_stops_the_keyword(self):
        keys = ["%016x" % n for n in range(5)]
        count, stop, last = self.budget(keys, page=2, seen=keys)
        self.assertEqual(count, 0)
        self.assertIn("one results page", stop)
        self.assertTrue(last)

    def test_a_reshuffled_page_is_still_the_same_page(self):
        """MEASURED: reloads of one page shared 60-100% of their cards.

        Indeed rotates the cards between loads, so byte-equal card lists
        are not what a repeated page looks like.
        """
        keys = ["%016x" % n for n in range(5)]
        again = list(reversed(keys[:4])) + ["%016x" % 999]   # 1 of 5 new
        count, stop, last = self.budget(again, page=2, seen=keys)
        self.assertEqual(count, 0)
        self.assertIn("one results page", stop)
        self.assertTrue(last)

    def test_a_different_page_2_is_collected(self):
        page1 = ["%016x" % n for n in range(5)]
        page2 = ["%016x" % (100 + n) for n in range(5)]
        count, stop, last = self.budget(page2, page=2, seen=page1)
        self.assertEqual(count, 5)
        self.assertEqual(stop, "")
        self.assertFalse(last)

    def test_one_repeated_card_does_not_condemn_a_real_page_2(self):
        """A sponsored card can appear on both pages. That is not a repeat."""
        page1 = ["%016x" % n for n in range(5)]
        page2 = [page1[0]] + ["%016x" % (100 + n) for n in range(4)]
        count, stop, last = self.budget(page2, page=2, seen=page1)
        self.assertEqual(count, 5)
        self.assertEqual(stop, "")

    def test_an_unreadable_census_falls_back_and_never_stops(self):
        """"Unknown" must not be read as "the results ended"."""
        count, stop, last = self.budget([], page=3, seen=["%016x" % 1])
        self.assertEqual(count, collector.FIXED_CARDS_PER_PAGE)
        self.assertEqual(stop, "")
        self.assertFalse(last)

    def test_a_page_that_says_zero_cards_is_believed(self):
        count, stop, last = self.budget([], declared=0)
        self.assertEqual(count, 0)
        self.assertIn("0 cards", stop)
        self.assertTrue(last)


class TestMatchCountDecidesPaging(unittest.TestCase):
    """The page states how many jobs the search matched; use it.

    MEASURED: "Mdm Engineer" in Madurai matched NOTHING and Indeed still
    rendered five suggestion cards, reshuffled on every reload. The
    collector took those five cards and then asked for start=10, 20, 30
    and 40 of a search with no results.
    """

    def budget(self, keys, matches, page=1, seen=()):
        start_at = (page - 1) * collector.INDEED_PAGE_STEP
        census = collector.PageCensus(keys, "results-array" if keys
                                      else "none", len(keys) or None, matches)
        return collector.card_budget_for_page(census, page, start_at,
                                              list(seen))

    def test_zero_matches_takes_the_cards_but_turns_no_page(self):
        """The suggestions are still real jobs -- collect them, then stop."""
        keys = ["%016x" % n for n in range(5)]
        count, stop, last = self.budget(keys, matches=0)
        self.assertEqual(count, 5, "the cards on the page are not discarded")
        self.assertEqual(stop, "")
        self.assertTrue(last, "a search with 0 matches has no second page")

    def test_zero_matches_and_no_cards_stops_outright(self):
        count, stop, last = self.budget([], matches=0)
        self.assertEqual(count, 0)
        self.assertIn("0 jobs", stop)
        self.assertTrue(last)

    def test_the_last_page_of_a_real_search_is_recognised(self):
        """7 matches: page 1 takes 7, and there is no page 2."""
        count, stop, last = self.budget(["%016x" % n for n in range(7)],
                                        matches=7)
        self.assertEqual(count, 7)
        self.assertEqual(stop, "")
        self.assertTrue(last)

    def test_a_middle_page_keeps_paging(self):
        """40 matches, 15 cards at start=10: pages remain."""
        count, stop, last = self.budget(["%016x" % n for n in range(15)],
                                        matches=40, page=2)
        self.assertEqual(count, collector.FIXED_CARDS_PER_PAGE)
        self.assertEqual(stop, "")
        self.assertFalse(last)

    def test_the_two_count_signals_disagree_in_favour_of_more_pages(self):
        """Under-stating the count would throw real results away."""
        html = ('<html><head><title>137 Python Developer Jobs in Delhi'
                '</title></head><body>{"totalJobCount":0}</body></html>')
        self.assertEqual(src.search_match_count(html), 137)

    def test_the_count_is_read_from_the_real_saved_pages(self):
        """MEASURED: that search matched 0 while the page showed 5 cards.

        This is the case the whole feature turns on, so it is checked
        against the actual files rather than a fixture.
        """
        paths = sorted(glob.glob(os.path.join(BASE, "Temp_Data", "rank_*",
                                              "job_*.html")))
        if not paths:
            self.skipTest("no saved listing sources in Temp_Data to check")
        for path in paths:
            cards = src.page_cards(src.read_saved_source(path))
            if cards.total_matches != 0:
                continue
            self.assertTrue(
                cards.keys,
                "%s: 0 matches and no cards -- then this file does not "
                "show the case being guarded" % path)
            self.assertEqual(
                collector.card_budget_for_page(
                    collector.PageCensus(cards.keys, cards.evidence,
                                         cards.declared_count, 0),
                    1, 0, [])[2],
                True, "%s: a 0-match search must be its own last page"
                % path)


class TestCensusIsWiredIn(unittest.TestCase):
    """The loop must USE the measured budget, not the fixed constant."""

    def setUp(self):
        self.source = open(os.path.join(BASE, "find_indeed_job.py"),
                           encoding="utf-8").read()
        self.combo = self.source.split("def run_combo(")[1].split("\ndef ")[0]

    def test_the_card_loop_is_bounded_by_the_census(self):
        self.assertIn("for card_index in range(0, cards_this_page):",
                      self.combo)
        self.assertNotIn("range(0, MAX_CARDS_PER_PAGE)", self.combo)

    def test_the_census_runs_before_the_cards(self):
        self.assertLess(self.combo.index("read_page_census"),
                        self.combo.index("for card_index in range"))

    def test_the_census_is_saved_per_page_not_per_card(self):
        """A per-card name would overwrite a job's own source file."""
        controller = open(os.path.join(BASE, "source_file",
                                       "indeed_controller.py"),
                          encoding="utf-8").read()
        body = controller.split("def save_listing_source(")[1] \
                         .split("\n    def ")[0]
        self.assertIn('"listing_%s_page%02d.html"', body)

    def test_an_access_refusal_during_the_census_stops_the_run(self):
        """Not retried, not worked around -- stopped."""
        self.assertIn("census_access_denied", self.combo)
        self.assertIn('return "access_denied"', self.combo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
