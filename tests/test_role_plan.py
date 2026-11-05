"""The keyword plan and the two-track filter, as the NEW authoritative file
defines them.

This file replaces the 85-role assertions that were here before.  The change
request supplied a new ``target_audience_roles.py``, made it authoritative,
and said in terms: do not restrict the script to the previous 85 IT
keywords, obtain the complete list dynamically from ``build_role_plan()``,
and preserve the new module's two-audience filtering rather than
re-imposing the IT-only rule.

So the numbers below are COUNTED from the authoritative file, and the two
that are hardcoded (200 Track A, 110 cities) are hardcoded only because the
change request names them.  Nothing here re-declares a role.
"""

import hashlib
import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import target_audience_roles as roles                        # noqa: E402


class TestItComesFromTheAuthoritativeFile(unittest.TestCase):
    """One role list, and it is the vendored authoritative one."""

    def test_roles_resolve_to_the_vendored_copy(self):
        self.assertTrue(roles.SOURCE_FILE.endswith(
            os.path.join("vendor", "target_audience_roles.py")),
            "roles must come from vendor/, got %r" % roles.SOURCE_FILE)

    def test_the_vendored_bytes_match_the_recorded_md5(self):
        """A silent edit to vendor/ must not pass unnoticed."""
        record = json.load(open(os.path.join(BASE, "vendor",
                                             "PROVENANCE.json")))
        for name, expected in record["files"].items():
            with self.subTest(file=name):
                data = open(os.path.join(BASE, "vendor", name), "rb").read()
                self.assertEqual(hashlib.md5(data).hexdigest(),
                                 expected["md5"],
                                 "%s no longer matches PROVENANCE.json" % name)

    def test_the_shim_declares_no_roles_of_its_own(self):
        """'Do not create another hardcoded list of job roles or cities.'"""
        text = open(os.path.join(BASE, "target_audience_roles.py")).read()
        body = text.split('"""', 2)[-1]          # past the module docstring
        self.assertNotIn("[", body.split("__all__")[0],
                         "the shim appears to declare a list of its own")


class TestThePlanIsTheCompleteNewOne(unittest.TestCase):

    def setUp(self):
        self.plan = roles.build_role_plan()

    def test_the_plan_is_far_larger_than_the_old_eighty_five(self):
        # The exact number is the authoritative file's business, not this
        # project's; what this project must guarantee is that it is no
        # longer the old 85-keyword subset.
        self.assertGreater(len(self.plan), 1000)

    def test_the_plan_has_no_duplicates(self):
        self.assertEqual(len(self.plan), len(set(self.plan)))

    def test_track_a_is_the_mandated_two_hundred(self):
        target, other, percent = roles.role_plan_split()
        self.assertEqual(target, 200)
        self.assertEqual(target + other, len(self.plan))
        self.assertAlmostEqual(percent, round(target * 100.0 / len(self.plan), 1))

    def test_track_b_brings_non_it_departments_into_the_plan(self):
        """The whole point of the new file: freshers outside IT."""
        departments = {roles.role_department(role) for role in self.plan}
        self.assertIn("Nursing", departments)
        self.assertIn("Accounts", departments)
        self.assertGreater(len(departments), 50)

    def test_the_priority_profiles_lead_the_canonical_order(self):
        head = self.plan[:roles.PRIORITY_HEAD_SIZE]
        self.assertTrue(set(head).issubset(set(roles.PRIORITY_ROLES)))

    def test_the_original_target_audience_lists_are_untouched(self):
        # The new file keeps these verbatim; other modules read them.
        self.assertEqual(len(roles.TARGET_AUDIENCE_ROLES), 68)
        self.assertEqual(len(roles.HIGH_DEMAND_IT_ROLES), 17)

    def test_excluding_freshers_gives_track_a_alone(self):
        track_a = roles.build_role_plan(include_freshers=False)
        self.assertEqual(len(track_a), 200)

    def test_the_plan_is_obtained_dynamically_not_copied(self):
        """A caller must get a fresh list it can shuffle without damage."""
        first = roles.build_role_plan()
        first.append("MUTATION CANARY")
        self.assertNotIn("MUTATION CANARY", roles.build_role_plan())


class TestTwoTrackFilter(unittest.TestCase):
    """is_non_it_title keeps its name and contract; its MEANING changed."""

    KEPT_TRACK_A = [
        "System Administrator", "Azure Administrator", "Java Developer",
        "Cloud Support Engineer", "Desktop Support Engineer",
    ]
    # The rows the old IT-only filter could never let through, which are the
    # entire reason the new file exists.
    KEPT_TRACK_B = [
        "Staff Nurse", "Accounts Assistant", "Cashier", "Delivery Driver",
        "Teacher", "Lab Technician",
    ]
    DROPPED_SENIOR = [
        "Area Sales Manager", "Head of Marketing", "Senior Staff Nurse",
    ]

    def test_track_a_titles_are_kept(self):
        for title in self.KEPT_TRACK_A:
            with self.subTest(title=title):
                self.assertFalse(roles.is_non_it_title(title))

    def test_fresher_titles_outside_it_are_now_kept(self):
        for title in self.KEPT_TRACK_B:
            with self.subTest(title=title):
                self.assertFalse(roles.is_non_it_title(title),
                                 "%r is a Track B fresher job and must be "
                                 "kept by the new filter" % title)

    def test_senior_non_it_titles_are_dropped(self):
        for title in self.DROPPED_SENIOR:
            with self.subTest(title=title):
                self.assertTrue(roles.is_non_it_title(title))

    #: Plan entries that the plan's own filter rejects.  See
    #: test_architect_is_searched_but_discarded below for why.
    KNOWN_SELF_REJECTING = {"Architect"}

    def test_every_planned_role_survives_its_own_filter(self):
        """Searching for a role the filter then discards wastes the crawl."""
        offenders = [title for title in roles.build_role_plan()
                     if roles.is_non_it_title(title)]
        self.assertEqual(set(offenders), self.KNOWN_SELF_REJECTING,
                         "the set of self-rejecting plan entries changed")

    def test_architect_is_searched_but_discarded(self):
        """A discrepancy in the authoritative file, pinned and NOT fixed.

        'Architect' is in the plan because build_fresher_plan() calls the
        department-aware is_senior_title('Architect', 'Architecture'), and
        ARCHITECT_IS_ENTRY_LEVEL_DEPARTMENTS exempts it.  The row filter the
        scrapers actually call, is_out_of_scope_title(), is handed a BARE
        title with no department, so it cannot apply that carve-out and
        rejects the same string.

        Net effect: one search per city returns rows that are then all
        discarded -- 1 keyword of 1264, 0.08% of the crawl.

        The change request says to preserve the new module's filtering
        functions and configuration as delivered, so this project does not
        patch it.  Fixing it upstream means passing the department into
        is_out_of_scope_title(); this test will start failing when that
        happens, which is the intent.
        """
        self.assertIn("Architect", roles.build_role_plan())
        self.assertTrue(roles.is_non_it_title("Architect"))
        # The department-aware function disagrees with the bare-title one.
        self.assertFalse(roles.is_senior_title("Architect", "Architecture"))
        self.assertTrue(roles.is_senior_title("Architect"))

    def test_blank_titles_are_not_rejected(self):
        for value in ("", None, "   "):
            self.assertFalse(roles.is_non_it_title(value))

    def test_unrecognised_titles_are_kept_by_design(self):
        """Pinned, not fixed: step 8 of the filter is 'anything else -> keep'.

        The authoritative file documents this ("Unrecognised is not the same
        as unwanted") and the change request says to preserve its filtering
        behaviour, so this project does not re-filter it.  The consequence
        is worth knowing: an unrecognised occupation reaches Excel and is
        labelled with DEFAULT_DEPARTMENT.
        """
        self.assertFalse(roles.is_non_it_title("Astrologer"))
        self.assertEqual(roles.role_department("Astrologer"),
                         roles.DEFAULT_DEPARTMENT)


class TestDepartmentLabelling(unittest.TestCase):

    def test_a_nursing_role_is_not_labelled_it(self):
        self.assertEqual(roles.role_department("Staff Nurse"), "Nursing")

    def test_an_it_role_keeps_the_default_department(self):
        self.assertEqual(roles.role_department("Java Developer"),
                         roles.DEFAULT_DEPARTMENT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
