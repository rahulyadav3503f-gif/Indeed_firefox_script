"""Saved HTML source -> 32-column row, and the blank-cell rule.

Two things are proved here:

  1. Firefox's view-source save can be turned back into the page's ORIGINAL
     html exactly.  Everything downstream depends on that, and it is not
     obvious -- the saved file is a syntax-highlighted document several
     times the size of the original.

  2. A field the file does not state ends up as an EMPTY CELL in the right
     column.  Not "N/A", not "Unknown", not the next field shifted left.
"""

import html as _html
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from source_file import indeed_source as src                  # noqa: E402
from source_file.indeed_extractor import DETAIL_COLUMNS       # noqa: E402

def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


FIXTURES = os.path.join(BASE, "tests", "fixtures")
JSONLD = os.path.join(FIXTURES, "job_detail_jsonld.html")
PLAIN = os.path.join(FIXTURES, "job_detail_1.html")

#: The placeholder strings the change request forbids outright.
FORBIDDEN = ("N/A", "n/a", "NA", "Not Found", "not found", "Unknown",
             "unknown", "None", "none", "null", "NULL", "-", "--")


def firefox_view_source_wrapper(original):
    """Build the document Firefox's Ctrl+S writes for a view-source tab.

    Modelled on a REAL captured save: <body id="viewsource"> with one
    <span id="lineN"> per line and the source escaped inside it.  The point
    of reproducing it here is that the recovery function must survive the
    scaffolding, whatever the scaffolding happens to be.
    """
    lines = original.split("\n")
    spans = []
    for number, line in enumerate(lines, start=1):
        body = _html.escape(line, quote=False)
        newline = "\n" if number < len(lines) else ""
        spans.append('<span id="line%d"><span></span><span>%s</span>'
                     '<span>%s</span></span>' % (number, body, newline))
    return (
        '<!DOCTYPE html>\n<html><head>'
        '<meta http-equiv="content-type" content="text/html; charset=UTF-8">'
        '<title>view-source fixture</title>'
        '<link rel="stylesheet" type="text/css" '
        'href="resource://content-accessible/viewsource.css"></head>'
        '<body id="viewsource" style="tab-size: 4">'
        + "".join(spans) +
        '</body></html>\n')


class TestViewSourceRecovery(unittest.TestCase):

    def test_a_wrapped_save_is_recognised(self):
        wrapped = firefox_view_source_wrapper("<p>hello</p>\n")
        self.assertTrue(src.looks_like_view_source(wrapped))

    def test_raw_html_is_not_mistaken_for_a_wrapper(self):
        raw = read_text(PLAIN)
        self.assertFalse(src.looks_like_view_source(raw))

    def test_recovery_is_exact_for_a_real_fixture(self):
        """The whole pipeline rests on this being byte-for-byte."""
        for path in (PLAIN, JSONLD):
            with self.subTest(fixture=os.path.basename(path)):
                original = read_text(path)
                recovered = src.recover_original_html(
                    firefox_view_source_wrapper(original))
                self.assertEqual(recovered, original)

    def test_recovery_survives_escaped_entities_and_angle_brackets(self):
        original = ('<p title="a &amp; b">1 &lt; 2 &gt; 0</p>\n'
                    '<script>if (a < b && c > d) { x("&quot;"); }</script>\n')
        recovered = src.recover_original_html(
            firefox_view_source_wrapper(original))
        self.assertEqual(recovered, original)

    def test_raw_html_passes_through_untouched(self):
        raw = read_text(PLAIN)
        self.assertEqual(src.recover_original_html(raw), raw)


class TestJsonLd(unittest.TestCase):

    def setUp(self):
        self.html = read_text(JSONLD)
        self.posting = src.json_ld_job_posting(self.html)

    def test_the_job_posting_is_found(self):
        self.assertIsNotNone(self.posting)
        self.assertEqual(self.posting["title"], "Azure Administrator")

    def test_stated_fields_are_read(self):
        fields = src.fields_from_json_ld(self.posting)
        self.assertEqual(fields["job_title"], "Azure Administrator")
        self.assertEqual(fields["company_name"], "Northwind Cloud Services")
        self.assertEqual(fields["company_website"],
                         "https://www.northwind-cloud.example")
        self.assertEqual(fields["location"], "Pune, Maharashtra, IN")
        self.assertEqual(fields["datePosted"], "2026-10-28")
        self.assertEqual(fields["employmentType"], "FULL_TIME")
        self.assertEqual(fields["experience_required"], "2 - 5 years")

    def test_absent_fields_are_absent_not_empty_strings(self):
        """The fixture states no salary and no deadline."""
        fields = src.fields_from_json_ld(self.posting)
        for key in ("salary_text", "salary_currency", "validThrough",
                    "applicationDeadline"):
            self.assertNotIn(key, fields)

    def test_a_page_without_json_ld_simply_has_none(self):
        self.assertIsNone(src.json_ld_job_posting(
            read_text(PLAIN)))

    def test_malformed_json_ld_is_skipped_not_guessed_at(self):
        broken = '<script type="application/ld+json">{ not json </script>'
        self.assertIsNone(src.json_ld_job_posting(broken))


class TestRowFromSource(unittest.TestCase):
    """The end of the pipeline: a saved file becomes a 32-column row."""

    APPLY = "https://in.indeed.com/viewjob?jk=fixturejsonld"

    def setUp(self):
        self.row, self.report = src.build_row_from_html(
            read_text(JSONLD),
            apply_url=self.APPLY, source_path=JSONLD)

    def test_the_row_has_exactly_the_thirty_two_columns_in_order(self):
        self.assertEqual(len(DETAIL_COLUMNS), 32)
        ordered = [key for key in self.row if key in set(DETAIL_COLUMNS)]
        self.assertEqual(ordered, list(DETAIL_COLUMNS))

    def test_the_stated_fields_landed_in_the_right_columns(self):
        self.assertEqual(self.row["job_title"], "Azure Administrator")
        self.assertEqual(self.row["company_name"], "Northwind Cloud Services")
        self.assertEqual(self.row["city"], "Pune")
        self.assertEqual(self.row["apply_url"], self.APPLY)
        self.assertIn("Azure", self.row["job_description"])

    def test_the_related_jobs_rail_did_not_leak_in(self):
        """The fixture's 'Similar jobs' block is a DIFFERENT job."""
        blob = " ".join(str(value) for value in self.row.values())
        self.assertNotIn("Contoso Infrastructure", blob)
        self.assertNotIn("Senior Network Architect", blob)

    def test_unstated_fields_are_blank(self):
        for column in ("salary_min", "salary_max", "salary_currency",
                       "expiry_date", "application_deadline"):
            with self.subTest(column=column):
                self.assertEqual(str(self.row[column] or "").strip(), "",
                                 "%s was not stated in the file and must be "
                                 "blank" % column)

    def test_no_placeholder_strings_anywhere_in_the_row(self):
        for column in DETAIL_COLUMNS:
            value = str(self.row.get(column, "") or "").strip()
            if value:
                self.assertNotIn(value, FORBIDDEN,
                                 "%s holds the placeholder %r"
                                 % (column, value))

    def test_the_report_lists_what_was_blank(self):
        self.assertIn("salary_min", self.report.missing)
        self.assertIn("application_deadline", self.report.missing)
        # ...and does NOT claim the filled ones are missing.
        self.assertNotIn("job_title", self.report.missing)

    def test_provenance_says_where_each_value_came_from(self):
        self.assertEqual(self.report.provenance["job_title"], "json-ld")
        self.assertEqual(self.report.provenance["company_name"], "json-ld")

    def test_a_page_with_no_json_ld_still_produces_a_row(self):
        row, report = src.build_row_from_html(
            read_text(PLAIN),
            apply_url="https://in.indeed.com/viewjob?jk=plain")
        self.assertEqual(row["job_title"], "Backend Developer")
        self.assertEqual(row["company_name"], "Example Technologies Pvt Ltd")
        self.assertEqual(report.provenance["job_title"], "visible-text")

    def test_an_empty_document_invents_nothing(self):
        row, report = src.build_row_from_html("", apply_url="")
        for column in ("job_title", "company_name", "location",
                       "job_description", "salary_min"):
            self.assertEqual(str(row[column] or "").strip(), "")


class TestSavedFileEndToEnd(unittest.TestCase):
    """The file on disk, exactly as save_page_source.sh leaves it."""

    def test_a_view_source_save_round_trips_into_a_row(self):
        import tempfile
        original = read_text(JSONLD)
        wrapped = firefox_view_source_wrapper(original)
        handle = tempfile.NamedTemporaryFile("w", suffix=".html",
                                             delete=False, encoding="utf-8")
        try:
            handle.write(wrapped)
            handle.close()
            row, report = src.build_row_from_file(
                handle.name, apply_url="https://in.indeed.com/viewjob?jk=x")
            self.assertTrue(report.was_view_source)
            self.assertEqual(row["job_title"], "Azure Administrator")
            self.assertEqual(row["company_name"], "Northwind Cloud Services")
            self.assertEqual(str(row["salary_min"] or "").strip(), "")
        finally:
            os.unlink(handle.name)


class TestJobIsolation(unittest.TestCase):
    """Taking ONE job out of a multi-job listing document.

    Written against three real captures of an Indeed results page, each of
    which described 16 jobs and carried no JSON-LD at all.
    """

    def test_a_multi_job_document_is_counted(self):
        html = '<a href="/x?jk=aaaaaaaaaaaaaaaa">a</a> <a href="?vjk=bbbbbbbbbbbbbbbb">b</a>'
        self.assertEqual(src.count_jobs(html), 2)

    def test_the_description_comes_from_the_pane_not_the_snippet(self):
        """The card's snippet is a teaser; the pane has the real text.

        Measured on a real capture: snippet 135 chars, pane 4,319. First
        source wins in fields_from_source(), so the pane must be adopted
        first or every row gets the teaser.
        """
        source = open(os.path.join(BASE, "source_file", "indeed_source.py"),
                      encoding="utf-8").read()
        block = source.split("if card is not None:")[1].split("isolation =")[0]
        self.assertLess(block.index("job-pane"), block.index("job-card"))

    def test_the_pane_description_is_tied_to_the_selected_job(self):
        """It is only used when autoOpenJobAttributes.jobKey matches."""
        html = ('<script>window._initialData={"autoOpenJobAttributes":'
                '{"jobKey":"1111111111111111"},'
                '"sanitizedJobDescription":"' + ("x" * 500) + '"}</script>')
        self.assertTrue(src.selected_job_description(html, "1111111111111111"))
        self.assertEqual(src.selected_job_description(html, "2222222222222222"), "")

    def test_visible_text_is_not_used_once_a_job_is_isolated(self):
        """It would read the other 15 jobs' text. See the module comment."""
        source = open(os.path.join(BASE, "source_file", "indeed_source.py"),
                      encoding="utf-8").read()
        self.assertIn('if isolation == "job-card":', source)
        self.assertIn("visible-text parsing skipped", source)

    def test_a_currency_is_not_recorded_without_a_salary(self):
        self.assertEqual(src.fields_from_job_card(
            {"salarySnippet": {"currency": "INR"}}).get("salary_currency"),
            None)
        full = src.fields_from_job_card(
            {"salarySnippet": {"currency": "INR", "text": "Rs 20,000 a month"}})
        self.assertEqual(full.get("salary_currency"), "INR")

    def test_employment_type_comes_from_the_taxonomy_block(self):
        card = {"taxonomyAttributes": [
            {"label": "job-types", "attributes": [{"label": "Full-time"}]}]}
        self.assertEqual(src.fields_from_job_card(card)["employment_type"],
                         "Full-time")


if __name__ == "__main__":
    unittest.main(verbosity=2)
