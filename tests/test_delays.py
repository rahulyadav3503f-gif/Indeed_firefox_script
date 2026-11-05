"""Both 10-second delays: that they exist, their default, and their ORDER.

The requirement is not just "sleep twice".  It is:

    process and save the job to Excel
    -> FIRST delay            (10s, before the source tab is closed)
    -> close the source tab
    -> SECOND delay           (10s, before the next card is selected)
    -> select the next job card

A test that only checked `time.sleep(10)` was called twice would pass for an
implementation that slept twice in a row after closing.  So what is asserted
here is the sequence of events, not a count.
"""

import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from source_file import indeed_controller as ctrl             # noqa: E402


class RecordingController(ctrl.IndeedController):
    """A controller whose sleeps and shell calls are written to a tape."""

    def __init__(self, config):
        super(RecordingController, self).__init__(config)
        self.tape = []
        self.listing_window = "12345"
        self.firefox_pid = "999"

    def run_script(self, name, args, timeout=None, allow_codes=()):
        self.tape.append(("script", name))
        return 0, {"closed": "yes", "url": "https://in.indeed.com/jobs?q=x",
                   "back_on_listing": "yes"}, ""

    def log(self, message):
        pass


class DelayTestCase(unittest.TestCase):

    def setUp(self):
        self.config = ctrl.ControllerConfig(project_dir=BASE, rank=1,
                                            verbose=False)
        self.controller = RecordingController(self.config)
        self._real_sleep = ctrl.time.sleep
        ctrl.time.sleep = self._record_sleep

    def tearDown(self):
        ctrl.time.sleep = self._real_sleep

    def _record_sleep(self, seconds):
        self.controller.tape.append(("sleep", seconds))


class TestDefaults(DelayTestCase):

    def test_both_delays_default_to_ten_seconds(self):
        self.assertEqual(self.config.pre_close_delay_seconds, 10.0)
        self.assertEqual(self.config.post_close_delay_seconds, 10.0)

    def test_both_delays_are_configurable(self):
        config = ctrl.ControllerConfig(project_dir=BASE,
                                       pre_close_delay_seconds=2,
                                       post_close_delay_seconds=3)
        self.assertEqual(config.pre_close_delay_seconds, 2.0)
        self.assertEqual(config.post_close_delay_seconds, 3.0)


class TestOrdering(DelayTestCase):

    def test_sleep_close_sleep_in_that_order(self):
        self.controller.close_source_tab()
        self.assertEqual(self.controller.tape, [
            ("sleep", 10.0),
            ("script", "close_source_tab.sh"),
            ("sleep", 10.0),
        ])

    def test_the_first_delay_happens_before_the_tab_closes(self):
        self.controller.close_source_tab()
        kinds = [entry[0] for entry in self.controller.tape]
        close_at = kinds.index("script")
        self.assertEqual(kinds[:close_at], ["sleep"],
                         "the first delay must come BEFORE the close")

    def test_the_second_delay_happens_after_the_tab_closes(self):
        self.controller.close_source_tab()
        kinds = [entry[0] for entry in self.controller.tape]
        close_at = kinds.index("script")
        self.assertEqual(kinds[close_at + 1:], ["sleep"],
                         "the second delay must come AFTER the close")

    def test_overrides_are_honoured_in_both_positions(self):
        self.controller.close_source_tab(pre_delay=1, post_delay=7)
        self.assertEqual(self.controller.tape, [
            ("sleep", 1),
            ("script", "close_source_tab.sh"),
            ("sleep", 7),
        ])

    def test_the_error_path_does_not_sleep(self):
        """force_close_source_tab() is cleanup; it must not burn 20 seconds."""
        self.controller.force_close_source_tab()
        self.assertEqual(self.controller.tape,
                         [("script", "close_source_tab.sh")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
