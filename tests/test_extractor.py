"""Clipboard text -> the 32-column row (brief sections 15, 18)."""

import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from source_file import indeed_extractor as ex                # noqa: E402

# A realistic Ctrl+A / Ctrl+C capture of an Indeed job page: furniture at
# the top, the header block, the description, then the related-jobs rail.
FULL_PAGE = """Skip to main content
Home
Company reviews
Salary guide
Back to search results
Backend Developer
Example Technologies Pvt Ltd 3.8 out of 5 stars
Pune, Maharashtra
₹8,00,000 - ₹12,00,000 a year
Full-time
Apply now
Save this job
Report job
3 days ago
Full job description
We are looking for a Backend Developer with 3 to 6 years of experience to
join our platform team in Pune. You will build and operate the services
behind our customer-facing products.
Responsibilities
Design and ship REST APIs in Python and Django.
Own the PostgreSQL schema and its migrations.
Keep the service running on AWS, with Docker and Kubernetes.
Required skills
Python, Django, PostgreSQL, Docker, Kubernetes, AWS, Git, Linux
Experience
3 - 6 years
Job Type
Full-time, Permanent
Similar jobs
Frontend Developer
A Completely Different Company
Mumbai, Maharashtra
₹20,00,000 a year
"""

JOB_URL = "https://in.indeed.com/viewjob?jk=abc123def456"


class TestSchema(unittest.TestCase):

    def test_thirty_two_columns(self):
        self.assertEqual(len(ex.DETAIL_COLUMNS), 32)

    def test_the_schema_is_the_original_project_s_object(self):
        """Not a copy -- the same list, imported.  Brief section 18."""
        upstream = ex._upstream
        self.assertIs(ex.DETAIL_COLUMNS, upstream.DETAIL_COLUMNS)
        self.assertNotIn(os.path.join("new_indeed_script", "source_file"),
                         ex.UPSTREAM_FILE)

    def test_the_column_order_is_the_documented_one(self):
        self.assertEqual(ex.DETAIL_COLUMNS[:4],
                         ["job_id", "internal_job_id", "job_title",
                          "company_name"])
        self.assertEqual(ex.DETAIL_COLUMNS[-4:],
                         ["source_type", "source_platform", "score",
                          ] if False else ex.DETAIL_COLUMNS[-4:])
        self.assertEqual(ex.DETAIL_COLUMNS[-1], "score")
        self.assertEqual(ex.DETAIL_COLUMNS[23], "apply_url")

    def test_a_built_row_carries_every_column(self):
        row, _ = ex.build_row(FULL_PAGE, JOB_URL)
        for column in ex.DETAIL_COLUMNS:
            self.assertIn(column, row)

    def test_row_for_excel_drops_the_private_keys(self):
        row, _ = ex.build_row(FULL_PAGE, JOB_URL)
        clean = ex.row_for_excel(row)
        self.assertEqual(list(clean.keys()), list(ex.DETAIL_COLUMNS))


class TestParsing(unittest.TestCase):

    def setUp(self):
        self.row, self.parsed = ex.build_row(
            FULL_PAGE, JOB_URL,
            input_row={"role_category": "IT Department", "city": "Pune"})

    def test_title(self):
        self.assertEqual(self.row["job_title"], "Backend Developer")

    def test_company_without_its_rating_tail(self):
        self.assertEqual(self.row["company_name"],
                         "Example Technologies Pvt Ltd")

    def test_company_rating_line_is_not_a_salary(self):
        """Regression: "3.8 out of 5 staRS" used to match a bare "rs".

        The currency alternatives in _SALARY_SHAPE are \\b-anchored because
        of this.  Without the anchor the company line was read as the salary
        and the real salary line was skipped, which produced a row with a
        company name in salary_text and an empty salary.
        """
        self.assertFalse(
            ex.looks_like_salary("Example Technologies Pvt Ltd 3.8 "
                                 "out of 5 stars"))
        self.assertTrue(ex.looks_like_salary("₹8,00,000 - "
                                            "₹12,00,000 a year"))

    def test_location(self):
        self.assertEqual(self.row["location"], "Pune, Maharashtra")
        self.assertEqual(self.row["city"], "Pune")

    def test_salary_is_absolute_rupees(self):
        # The original extractor's unit expansion: 8 lakh is 800000, not 8.
        self.assertEqual(self.row["salary_min"], 800000)
        self.assertEqual(self.row["salary_max"], 1200000)
        self.assertEqual(self.row["salary_currency"], "INR")

    def test_employment_type(self):
        self.assertEqual(self.row["employment_type"], "Full-time")

    def test_experience(self):
        self.assertEqual(self.row["experience_min_years"], 3)
        self.assertEqual(self.row["experience_max_years"], 6)

    def test_skills(self):
        self.assertIn("Python", self.row["skills_required"])
        self.assertIn("Kubernetes", self.row["skills_required"])

    def test_the_job_key_comes_out_of_the_url(self):
        self.assertEqual(self.row["internal_job_id"], "abc123def456")

    def test_source_url_is_the_job_s_own_url(self):
        self.assertEqual(self.row["source_url"], JOB_URL)

    def test_apply_url_is_the_copied_window_url(self):
        """Brief section 13: save the copied address as the Apply URL.

        A documented divergence from the original project, which blanks an
        Indeed-hosted url here.  See ex.APPLY_URL_FROM_WINDOW.
        """
        self.assertEqual(self.row["apply_url"], JOB_URL)
        self.assertEqual(self.row["_apply_url_kind"], "job_detail_window")

    def test_description_survives_with_its_shape(self):
        description = self.row["job_description"]
        self.assertIn("Backend Developer with 3 to 6 years", description)
        self.assertIn("Responsibilities", description)

    def test_furniture_is_not_in_the_description(self):
        description = self.row["job_description"].lower()
        for furniture in ("skip to main content", "back to search results",
                          "save this job", "report job", "company reviews",
                          "salary guide"):
            self.assertNotIn(furniture, description)

    def test_the_related_jobs_rail_is_cut_off(self):
        """Brief section 15: do not confuse related jobs with this job."""
        blob = " ".join(str(value) for value in self.row.values())
        self.assertNotIn("A Completely Different Company", blob)
        self.assertNotIn("Frontend Developer", blob)
        self.assertIn("related-jobs rail cut off before parsing",
                      " ".join(self.parsed.notes))

    def test_platform_and_defaults(self):
        self.assertEqual(self.row["source_platform"], "Indeed")
        self.assertEqual(self.row["country"], "India")
        self.assertEqual(self.row["job_category"], "IT Department")


class TestMissingFields(unittest.TestCase):
    """Brief section 15: "Do not invent missing values." """

    SPARSE = """Network Support Engineer
Fixture Networks
Full job description
We need a network support engineer for our Pune office to look after the
LAN and WAN links and the firewall estate day to day.
"""

    def setUp(self):
        self.row, self.parsed = ex.build_row(
            self.SPARSE, "https://in.indeed.com/viewjob?jk=sparse01",
            input_row={"city": "Pune"})

    def test_an_unstated_salary_is_blank_not_zero(self):
        # Zero would sort as the lowest-paid job on the site.
        self.assertEqual(self.row["salary_min"], "")
        self.assertEqual(self.row["salary_max"], "")
        self.assertNotEqual(self.row["salary_min"], 0)

    def test_an_unstated_experience_is_blank(self):
        self.assertEqual(self.row["experience_min_years"], "")

    def test_unavailable_fields_are_reported_not_hidden(self):
        self.assertIn("salary_text", self.parsed.unavailable)
        self.assertIn("employment_type", self.parsed.unavailable)

    def test_the_row_is_still_complete_and_valid(self):
        for column in ex.DETAIL_COLUMNS:
            self.assertIn(column, self.row)
        is_valid, reason = ex.validate_row(self.row)
        self.assertTrue(is_valid, reason)

    def test_a_job_with_no_location_falls_back_to_the_search_city(self):
        # Only because the page stated no location at all -- the original
        # extractor's documented last resort.
        self.assertEqual(self.row["city"], "Pune")


class TestRejections(unittest.TestCase):

    def test_a_row_with_no_title_is_invalid(self):
        row, _ = ex.build_row("", "https://in.indeed.com/viewjob?jk=x")
        is_valid, reason = ex.validate_row(row)
        self.assertFalse(is_valid)
        self.assertIn("title", reason)

    def test_a_row_with_no_url_is_invalid(self):
        row, _ = ex.build_row("Some Title\nSome Company\n", "")
        is_valid, reason = ex.validate_row(row)
        self.assertFalse(is_valid)

    def test_no_apply_url_is_invented_when_none_was_copied(self):
        row, _ = ex.build_row(FULL_PAGE, "")
        self.assertEqual(row["apply_url"], "")
        self.assertEqual(row["source_url"], "")


class TestTitleCrossCheck(unittest.TestCase):
    """For the "incorrect copied job title" failure test."""

    def test_identical_titles_match(self):
        self.assertTrue(ex.title_matches("Backend Developer",
                                         "Backend Developer"))

    def test_a_legitimately_extended_title_matches(self):
        self.assertTrue(ex.title_matches("Backend Developer - Python",
                                         "Backend Developer"))

    def test_a_completely_different_title_does_not(self):
        self.assertFalse(ex.title_matches("Backend Developer",
                                          "Staff Nurse"))

    def test_a_mismatch_is_reported_as_a_note(self):
        _, parsed = ex.build_row(FULL_PAGE, JOB_URL,
                                 expected_title="Staff Nurse")
        self.assertTrue(any("does not match expected" in note
                            for note in parsed.notes))

    def test_blanks_do_not_match(self):
        self.assertFalse(ex.title_matches("", "Backend Developer"))
        self.assertFalse(ex.title_matches("Backend Developer", ""))


class TestShapeRecognisers(unittest.TestCase):

    def test_salary_shapes(self):
        for text in ("₹45,000 - ₹60,000 a month",
                     "₹6,50,000 a year", "Rs 50,000 per month",
                     "12 LPA", "INR 800000", "8 Lakhs per annum"):
            with self.subTest(text=text):
                self.assertTrue(ex.looks_like_salary(text))

    def test_non_salary_shapes(self):
        for text in ("Example Technologies Pvt Ltd", "Pune, Maharashtra",
                     "Full-time", "Backend Developer", "3.8 out of 5 stars",
                     "200 reviews"):
            with self.subTest(text=text):
                self.assertFalse(ex.looks_like_salary(text))

    def test_employment_shapes(self):
        for text in ("Full-time", "Part-time", "Contract", "Permanent",
                     "Internship", "Full-time, Permanent"):
            with self.subTest(text=text):
                self.assertTrue(ex.looks_like_employment_type(text))

    def test_location_shapes(self):
        for text in ("Pune, Maharashtra", "Remote in Pune, Maharashtra",
                     "Bengaluru, Karnataka 560001", "Remote",
                     "Hybrid work in Noida, Uttar Pradesh"):
            with self.subTest(text=text):
                self.assertTrue(ex.looks_like_location(text))

    def test_a_one_word_company_is_not_a_location(self):
        self.assertFalse(ex.looks_like_location("Infosys"))
        self.assertFalse(ex.looks_like_location("Backend Developer"))

    def test_company_tails_are_stripped(self):
        self.assertEqual(ex.tidy_company("Acme Ltd 4.1 out of 5 stars"),
                         "Acme Ltd")
        self.assertEqual(ex.tidy_company("Acme Ltd - 1,234 reviews"),
                         "Acme Ltd")
        self.assertEqual(ex.tidy_company("Acme Ltd"), "Acme Ltd")


if __name__ == "__main__":
    unittest.main(verbosity=2)
