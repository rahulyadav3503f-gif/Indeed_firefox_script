"""Saved HTML source -> the 32-column row.  Nothing is invented.

WHERE THIS SITS
---------------
    Ctrl+U, Ctrl+S         save_page_source.sh    a file in Temp_Data/
            |
            v
    recover_original_html()      <- this module, step 1
            |
            v
    fields_from_source()         <- this module, step 2
            |
            v
    extract_job_details()        <- the ORIGINAL project's row builder,
                                    imported, never reimplemented, so the
                                    32 columns and their order are exactly
                                    what the existing collector writes.

STEP 1 EXISTS BECAUSE OF A MEASURED SURPRISE
--------------------------------------------
Ctrl+S on a view-source tab does NOT write the page's HTML.  It writes
Firefox's *rendered* view-source document: the syntax-highlighted one, with
every original tag escaped and every line wrapped in <span id="lineN">.  A
1,440-byte fixture came back as 7,715 bytes of scaffolding.

The original source is recovered from it exactly -- the text content of
<body id="viewsource">, with entities unescaped, is the original file byte
for byte.  That was verified against the fixture before any of this was
built, and tests/test_source_recovery.py keeps verifying it.

A file that is already raw HTML is passed through untouched, so this module
works equally on a source saved some other way.

STEP 2'S ONE RULE: A FIELD THAT IS NOT IN THE FILE IS NOT IN THE ROW
--------------------------------------------------------------------
"If a field is missing, unavailable, or cannot be reliably identified, leave
the corresponding Excel cell blank.  Do not invent, assume, estimate, or
generate missing values.  Do not insert placeholder strings such as 'N/A'."

So a field is written into the raw dict ONLY when a real value was found.
Everything absent stays absent, and the original builder's last line --
``{column: row.get(column, "") for column in DETAIL_COLUMNS}`` -- turns
absence into an empty cell, in the right column, without shifting anything.
This module never writes "N/A", "Unknown", "Not Found" or "None" anywhere.

WHERE THE FIELDS COME FROM, BEST SOURCE FIRST
---------------------------------------------
1. JSON-LD ``JobPosting`` (<script type="application/ld+json">).  A job page
   that carries one is stating these values itself, in a standard schema.
   The original row builder already reads schema.org spellings -- datePosted,
   validThrough, employmentType, jobLocationType -- so they are handed over
   under their own names.
2. <meta> tags: og:title, og:description, description.
3. The visible text, parsed by the EXISTING clipboard parser
   (indeed_extractor.parse_job_text), which already knows how to cut the
   related-jobs rail off, drop page furniture and read labelled fields.

Later sources never overwrite earlier ones.  Every field records which
source it came from, so ``report.provenance`` can answer "where did this
company name come from?" without guessing.

WHAT THIS MODULE DOES NOT CLAIM
-------------------------------
It does not claim all 32 columns get filled.  Most job pages state a title,
a company, a location and a description, and state nothing at all about,
say, an application deadline.  Those columns stay blank, by design and by
instruction.  ``SourceReport.missing`` lists them for the log.
"""

import html as _html
import json
import os
import re

from .indeed_extractor import (DETAIL_COLUMNS, apply_the_window_url,
                               clean_value, extract_job_details,
                               parse_job_text)

# ===========================================================================
# 1. RECOVERING THE ORIGINAL SOURCE
# ===========================================================================

_VIEWSOURCE_BODY = re.compile(
    r"<body[^>]*\bid=[\"']viewsource[\"'][^>]*>(.*)</body>",
    re.IGNORECASE | re.DOTALL,
)
_ANY_TAG = re.compile(r"<[^>]+>")


def looks_like_view_source(text):
    """True when this is Firefox's rendered view-source document."""
    return bool(_VIEWSOURCE_BODY.search(text or ""))


def recover_original_html(text):
    """The page's ORIGINAL html.

    A Firefox view-source save is unwrapped; anything else is returned
    unchanged.  Unwrapping is exact: the scaffolding is only <span> and <a>
    elements, so dropping every tag and unescaping the entities leaves the
    original bytes.
    """
    text = text or ""
    match = _VIEWSOURCE_BODY.search(text)
    if not match:
        return text
    return _html.unescape(_ANY_TAG.sub("", match.group(1)))


def read_saved_source(path):
    """Read a saved source file and return its ORIGINAL html.

    Raises OSError when the file is unreadable -- the caller must not carry
    on and write a row for a job it could not read.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return recover_original_html(handle.read())


# ===========================================================================
# 2a. JSON-LD
# ===========================================================================

_LD_BLOCK = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def _iter_ld_objects(document):
    """Every dict inside a JSON-LD payload, including @graph members."""
    if isinstance(document, list):
        for item in document:
            for found in _iter_ld_objects(item):
                yield found
    elif isinstance(document, dict):
        yield document
        for key in ("@graph", "itemListElement", "mainEntity"):
            if key in document:
                for found in _iter_ld_objects(document[key]):
                    yield found


def json_ld_job_posting(original_html):
    """The first JSON-LD JobPosting object, or None."""
    for block in _LD_BLOCK.findall(original_html or ""):
        payload = block.strip()
        if not payload:
            continue
        try:
            document = json.loads(payload)
        except ValueError:
            # A malformed block is skipped, not guessed at.
            continue
        for item in _iter_ld_objects(document):
            kinds = item.get("@type") or item.get("type") or ""
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if any(str(kind).lower() == "jobposting" for kind in kinds):
                return item
    return None


def _text_of(value):
    """A plain string from a JSON-LD value, or "" when there isn't one."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "value", "@value", "text", "description"):
            if key in value:
                found = _text_of(value[key])
                if found:
                    return found
        return ""
    if isinstance(value, list):
        for item in value:
            found = _text_of(item)
            if found:
                return found
    return ""


def _address_of(posting):
    """The most specific stated location string, without inventing one."""
    location = posting.get("jobLocation")
    candidates = location if isinstance(location, list) else [location]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            found = _text_of(candidate)
            if found:
                return found
            continue
        address = candidate.get("address")
        if isinstance(address, dict):
            parts = [_text_of(address.get(key)) for key in
                     ("addressLocality", "addressRegion", "addressCountry")]
            parts = [part for part in parts if part]
            if parts:
                return ", ".join(parts)
        found = _text_of(address) or _text_of(candidate.get("name"))
        if found:
            return found
    return ""


def _salary_text(posting):
    """A faithful rendering of baseSalary, or "" when none is stated.

    This REPRESENTS what the page said; it does not estimate.  With no
    baseSalary the result is empty and the salary columns stay blank.
    """
    salary = posting.get("baseSalary") or posting.get("estimatedSalary")
    if not salary:
        return "", ""
    if isinstance(salary, (str, int, float)):
        return _text_of(salary), ""
    if not isinstance(salary, dict):
        return "", ""

    currency = _text_of(salary.get("currency")
                        or salary.get("salaryCurrency"))
    value = salary.get("value")
    if isinstance(value, (str, int, float)):
        return _text_of(value), currency
    if not isinstance(value, dict):
        return _text_of(salary.get("name")), currency

    minimum = _text_of(value.get("minValue"))
    maximum = _text_of(value.get("maxValue"))
    single = _text_of(value.get("value"))
    unit = _text_of(value.get("unitText"))

    if minimum and maximum and minimum != maximum:
        amount = "%s - %s" % (minimum, maximum)
    else:
        amount = single or minimum or maximum
    if not amount:
        return "", currency

    period = {"HOUR": "an hour", "DAY": "a day", "WEEK": "a week",
              "MONTH": "a month", "YEAR": "a year"}.get(unit.upper(), "")
    text = " ".join(part for part in (currency, amount, period) if part)
    return text.strip(), currency


#: JSON-LD key -> the raw key the ORIGINAL row builder reads.
_LD_DIRECT = (
    ("title",               "job_title"),
    ("description",         "description"),
    ("datePosted",          "datePosted"),
    ("validThrough",        "validThrough"),
    ("dateModified",        "dateModified"),
    ("employmentType",      "employmentType"),
    ("jobLocationType",     "jobLocationType"),
    ("applicationDeadline", "applicationDeadline"),
    ("experienceRequirements", "experience_required"),
    ("skills",              "skills_required"),
    ("qualifications",      "qualifications"),
)


def fields_from_json_ld(posting):
    """A raw-field dict from a JSON-LD JobPosting.  Absent stays absent."""
    found = {}
    if not posting:
        return found

    for ld_key, raw_key in _LD_DIRECT:
        value = _text_of(posting.get(ld_key))
        if value:
            found[raw_key] = value

    company = _text_of(posting.get("hiringOrganization"))
    if company:
        found["company_name"] = company

    organisation = posting.get("hiringOrganization")
    if isinstance(organisation, dict):
        website = _text_of(organisation.get("sameAs")
                           or organisation.get("url"))
        if website:
            found["company_website"] = website

    location = _address_of(posting)
    if location:
        found["location"] = location

    salary_text, currency = _salary_text(posting)
    if salary_text:
        found["salary_text"] = salary_text
    if currency:
        found["salary_currency"] = currency

    identifier = _text_of(posting.get("identifier"))
    if identifier:
        found["internal_job_id"] = identifier

    return found


# ===========================================================================
# 2b. <meta> AND <title>
# ===========================================================================

_META = re.compile(
    r"<meta\s+[^>]*?(?:name|property)=[\"']([^\"']+)[\"'][^>]*?"
    r"content=[\"']([^\"']*)[\"'][^>]*>",
    re.IGNORECASE,
)
_META_REVERSED = re.compile(
    r"<meta\s+[^>]*?content=[\"']([^\"']*)[\"'][^>]*?"
    r"(?:name|property)=[\"']([^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def meta_tags(original_html):
    """{name: content} for every <meta>, both attribute orders."""
    tags = {}
    for name, content in _META.findall(original_html or ""):
        tags.setdefault(name.strip().lower(), _html.unescape(content).strip())
    for content, name in _META_REVERSED.findall(original_html or ""):
        tags.setdefault(name.strip().lower(), _html.unescape(content).strip())
    return tags


def document_title(original_html):
    match = _TITLE.search(original_html or "")
    if not match:
        return ""
    return _html.unescape(_ANY_TAG.sub("", match.group(1))).strip()


def fields_from_meta(original_html):
    """Only the fields a <meta> tag actually states."""
    found = {}
    tags = meta_tags(original_html)

    title = tags.get("og:title") or tags.get("twitter:title")
    if title:
        found["job_title"] = title

    description = (tags.get("og:description") or tags.get("description")
                   or tags.get("twitter:description"))
    if description:
        found["description"] = description

    return found


# ===========================================================================
# 2c. VISIBLE TEXT
# ===========================================================================

# <nav> and <footer> go too.  They are navigation chrome, never the job,
# and a browser renders their links on ONE line ("Back to search results |
# Skip to main content"), which the existing furniture filter -- written
# against clipboard text, where each was its own line -- does not match.
# Observed: that joined line was read as the job title.  Dropping the
# elements is closer to the truth than teaching the filter a new shape.
#
# The related-jobs rail is deliberately NOT dropped here: cut_related_jobs()
# in the existing extractor already handles it, and leaving that one
# approved implementation in charge is better than adding a second.
#
# <title> is listed explicitly as well as <head>, because a page is not
# obliged to have a <head> element at all -- the parser supplies one, the
# BYTES often do not.  Without it the document title leaks in as the first
# visible line and gets read as the job title: job_detail_1.html produced
# "Backend Developer - Example Technologies Pvt Ltd - Local Fixture"
# instead of "Backend Developer".  A browser renders neither.
_DROPPED_ELEMENTS = re.compile(
    r"<\s*(script|style|noscript|svg|iframe|template|head|title|nav|footer)[^>]*>.*?"
    r"</\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_BLOCK_BOUNDARY = re.compile(
    r"</?\s*(p|div|section|article|br|tr|table|h[1-6]|ul|ol|li|"
    r"blockquote|header|footer|nav|main|aside|button|span)\b[^>]*>",
    re.IGNORECASE,
)
_MANY_BLANKS = re.compile(r"\n{3,}")


def html_to_visible_text(original_html):
    """Roughly what Ctrl+A, Ctrl+C on the rendered page would have given.

    The existing clipboard parser is written against exactly that shape, so
    producing it is what lets this project reuse it rather than grow a
    second field-reading implementation that could disagree with the first.
    """
    text = original_html or ""
    text = _DROPPED_ELEMENTS.sub(" ", text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = _BLOCK_BOUNDARY.sub("\n", text)
    text = _ANY_TAG.sub(" ", text)
    text = _html.unescape(text)
    text = text.replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return _MANY_BLANKS.sub("\n\n", "\n".join(line for line in lines if line))


# ===========================================================================
# 3. PUTTING IT TOGETHER
# ===========================================================================

class SourceReport(object):
    """What was found, where each value came from, and what was not there."""

    __slots__ = ("raw", "provenance", "missing", "notes", "source_path",
                 "was_view_source", "original_bytes", "parsed")

    def __init__(self, raw, provenance, missing, notes, source_path,
                 was_view_source, original_bytes, parsed):
        self.raw = raw
        self.provenance = provenance
        self.missing = missing
        self.notes = notes
        self.source_path = source_path
        self.was_view_source = was_view_source
        self.original_bytes = original_bytes
        self.parsed = parsed

    def __repr__(self):
        return ("<SourceReport %d fields, %d blank columns, from %s>"
                % (len(self.raw), len(self.missing),
                   os.path.basename(self.source_path or "<memory>")))


#: Columns the row builder fills from constants or provenance rather than
#: from the job page: they are NOT evidence that a job field was read, and
#: they are excluded from the "missing" report so the log stays honest.
_NON_JOB_COLUMNS = frozenset((
    "job_id", "fetched_at", "updated_at", "is_fake", "is_active",
    "source_type", "source_platform", "score", "country",
))


def fields_from_source(original_html, apply_url="", input_row=None,
                       expected_title=""):
    """(raw, provenance, notes, parsed) from one page's original html."""
    raw = {}
    provenance = {}
    notes = []

    def adopt(found, source_name):
        for key, value in found.items():
            value = clean_value(value)
            if not value:
                continue                      # absent stays absent
            if key in raw:
                continue                      # first (best) source wins
            raw[key] = value
            provenance[key] = source_name

    posting = json_ld_job_posting(original_html)
    if posting:
        adopt(fields_from_json_ld(posting), "json-ld")
        notes.append("JSON-LD JobPosting found")
    else:
        notes.append("no JSON-LD JobPosting in the source")

    adopt(fields_from_meta(original_html), "meta")

    # The visible-text parser runs last and fills only what is still unknown.
    text = html_to_visible_text(original_html)
    parsed = parse_job_text(text, apply_url=apply_url, input_row=input_row,
                            expected_title=expected_title)
    adopt(parsed.raw, "visible-text")
    notes.extend(parsed.notes)

    if apply_url:
        raw.setdefault("source_url", apply_url)
        raw.setdefault("apply_url", apply_url)
        provenance.setdefault("source_url", "address-bar")
        provenance.setdefault("apply_url", "address-bar")

    return raw, provenance, notes, parsed


def blank_columns(row):
    """Which of the 32 columns came out blank -- for the log, not for Excel."""
    return [column for column in DETAIL_COLUMNS
            if column not in _NON_JOB_COLUMNS
            and str(row.get(column, "") or "").strip() == ""]


def build_row_from_html(original_html, apply_url="", input_row=None,
                        state_resolver=None, fetched_at=None,
                        expected_title="", source_path=""):
    """(row, report) -- original html to a complete 32-column row."""
    raw, provenance, notes, parsed = fields_from_source(
        original_html, apply_url=apply_url, input_row=input_row,
        expected_title=expected_title)

    row = extract_job_details(raw, input_row=input_row,
                              state_resolver=state_resolver,
                              fetched_at=fetched_at)
    row = apply_the_window_url(row, apply_url)

    report = SourceReport(
        raw=raw, provenance=provenance, missing=blank_columns(row),
        notes=notes, source_path=source_path,
        was_view_source=False, original_bytes=len(original_html or ""),
        parsed=parsed)
    return row, report


def build_row_from_file(path, apply_url="", input_row=None,
                        state_resolver=None, fetched_at=None,
                        expected_title=""):
    """(row, report) -- a saved source FILE to a complete 32-column row."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        saved = handle.read()
    was_view_source = looks_like_view_source(saved)
    original_html = recover_original_html(saved)

    row, report = build_row_from_html(
        original_html, apply_url=apply_url, input_row=input_row,
        state_resolver=state_resolver, fetched_at=fetched_at,
        expected_title=expected_title, source_path=path)
    report.was_view_source = was_view_source
    if was_view_source:
        report.notes.insert(0, "unwrapped a Firefox view-source save "
                               "(%d bytes saved -> %d bytes of original html)"
                            % (len(saved), len(original_html)))
    return row, report


__all__ = [
    "looks_like_view_source", "recover_original_html", "read_saved_source",
    "json_ld_job_posting", "fields_from_json_ld", "meta_tags",
    "document_title", "fields_from_meta", "html_to_visible_text",
    "fields_from_source", "blank_columns", "build_row_from_html",
    "build_row_from_file", "SourceReport",
]
