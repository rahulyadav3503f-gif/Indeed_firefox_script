"""Turn clipboard text into the 32-column Indeed row.

WHAT THIS MODULE IS, AND WHAT IT DEFERS
---------------------------------------
There are two jobs in "extract a job", and this project only does one of
them itself:

    1. CLIPBOARD TEXT  ->  a raw field dict        <- this module
    2. a raw field dict ->  the 32-column row      <- the ORIGINAL project's
                                                      source_file/indeed_extractor.py

Step 2 is NOT reimplemented here.  The original ``extract_job_details()``
takes exactly the shape step 1 produces -- a plain dict of loosely-named
fields -- and it already owns the salary unit expansion, the city/state
resolution, the apply-url classification, the job_id hashing and the exact
column order.  Brief section 18 says the Excel contract must not be
redesigned; importing the one implementation is a stronger guarantee of that
than copying it, because a copy can drift and an import cannot.

So this file is a PARSER.  Its whole problem is that a browser clipboard
gives you a flat wall of visible text:

    Back to search results
    Backend Developer
    Example Technologies Pvt Ltd
    Pune, Maharashtra
    ₹8,00,000 - ₹12,00,000 a year
    Full-time
    Apply now
    Full job description
    We are looking for a Backend Developer with 3 to 6 years ...

...with no structure, no attributes, no hrefs, and -- crucially -- the
related-jobs rail and the navigation furniture mixed into the same text.

THE RULES (brief section 15)
----------------------------
*   NOTHING IS INVENTED.  A field the page did not state comes back absent,
    and the original extractor stores it as blank, which the importer reads
    as NULL.  There is no "probably Pune" and no "probably full-time".
*   THE RELATED-JOBS RAIL IS CUT OFF FIRST.  "Similar jobs", "People also
    viewed" and friends are a different job's title and company sitting in
    the same clipboard string; parsing past them is how one job's row gets
    another job's company name.
*   LABELS BEAT POSITION.  "Experience  3 - 6 years" is read from the
    label.  Position is only used for the few fields a job page states
    without one (title, company, location), and each positional guess is
    shape-checked before it is accepted.
*   WHAT COULD NOT BE PARSED IS REPORTED, not hidden.  ``parse_job_text()``
    returns an ``unavailable`` list, and the caller logs it.
"""

import re

from upstream import load_source_module as _load_source_module

# The ORIGINAL project's row builder and schema.  One definition, imported.
_upstream = _load_source_module("indeed_extractor")

#: The 32 columns, in the exact order the original project writes them.
DETAIL_COLUMNS = _upstream.DETAIL_COLUMNS
SOURCE_PLATFORM = _upstream.SOURCE_PLATFORM
SOURCE_TYPE = _upstream.SOURCE_TYPE

#: Re-exported so the rest of this project has one import site for them.
extract_job_details = _upstream.extract_job_details
row_for_excel = _upstream.row_for_excel
validate_row = _upstream.validate_row
clean_description = _upstream.clean_description
clean_value = _upstream.clean_value
now_utc = _upstream.now_utc
extract_internal_job_id = _upstream.extract_internal_job_id

#: Where those names actually come from, for the startup banner.
UPSTREAM_FILE = getattr(_upstream, "__file__", "")


# ===========================================================================
# 1. CUTTING THE TEXT DOWN TO ONE JOB
# ===========================================================================

# Headings that begin a DIFFERENT job's content.  Everything from the first
# one of these onwards is discarded before any field is read.
_RELATED_SECTION = re.compile(
    r"^\s*(?:"
    r"similar jobs|related jobs|jobs you might like|people also viewed|"
    r"more jobs (?:like this|at|from)|recommended jobs?|"
    r"other jobs (?:like this|from this)|view all jobs|"
    r"explore more jobs|job seekers also viewed|you might also like|"
    r"jobs for you"
    r")\s*[:.]?\s*$",
    re.IGNORECASE,
)

# Whole lines that are page furniture: buttons, breadcrumbs, cookie bars,
# relative timestamps.  Anchored, so a sentence that merely contains the
# word "apply" survives untouched.
_FURNITURE_LINE = re.compile(
    r"^\s*(?:"
    r"apply now|apply on company site|apply with indeed|easily apply|"
    r"easy apply|quick apply|continue to apply|apply to this job|"
    r"save this job|save job|saved|unsave|report job|report this job|"
    r"share|share this job|share job|copy link|"
    r"skip to main content|back to search results|back to results|"
    r"sign in|sign up|create an account|post your resume|employers / post job|"
    r"upload your resume|home|company reviews|salary guide|find salaries|"
    r"we use cookies.*|accept all cookies|cookie preferences|"
    r"reject all|manage cookies|privacy|terms|cookies, privacy and terms|"
    r"\d+\s*(?:minute|hour|day|week|month)s?\s*ago|just posted|today|"
    r"active \d+ days? ago|posted \d+ days? ago|hiring multiple candidates|"
    r"be an early applicant|urgently hiring|responsive employer|"
    r"\d+\s*jobs?|page \d+ of \d+|next page|previous page|"
    r"job post details|job details|show more|show less|read more|"
    r"profile insights|here.s how the job qualifications align|"
    r"do you have experience in.*\?|&nbsp;|\|"
    r")\s*[:.]?\s*$",
    re.IGNORECASE,
)

# Headings that begin the long-form description.
_DESCRIPTION_HEADING = re.compile(
    r"^\s*(?:"
    r"full job description|job description|about the (?:job|role|position)|"
    r"role description|about this (?:job|role)|the role|position overview|"
    r"job summary|job overview|description|job purpose|what you.ll do"
    r")\s*[:.]?\s*$",
    re.IGNORECASE,
)


def _lines(text):
    return [line.strip() for line in str(text or "").splitlines()]


def cut_related_jobs(text):
    """Return the text up to the first related-jobs heading.

    Brief section 15: "Do not confuse related jobs, recommendations, or
    navigation text with the intended job's details."  This is the cheapest
    and most effective guard against that, and it runs first so no later
    step can see the other job's text at all.
    """
    kept = []
    for line in str(text or "").splitlines():
        if _RELATED_SECTION.match(line):
            break
        kept.append(line)
    return "\n".join(kept)


def strip_furniture(lines):
    """Drop whole-line page furniture, and collapse runs of blank lines."""
    out = []
    for line in lines:
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if _FURNITURE_LINE.match(line):
            continue
        out.append(line)
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out


# ===========================================================================
# 2. LABELLED FIELDS
# ===========================================================================
# A job page states most of its facts under a label.  Reading the label is
# reliable; counting lines is not.  Both "Label: value" on one line and
# "Label" / "value" on two are handled, because browsers render both.

def _label_pattern(*labels):
    joined = "|".join(labels)
    return re.compile(r"^\s*(?:%s)\s*[:\-–]?\s*(.*)$" % joined, re.IGNORECASE)


_LABELS = {
    "experience_required": _label_pattern(
        r"experience", r"experience required", r"total experience",
        r"years of experience", r"work experience", r"exp"),
    "skills_required": _label_pattern(
        r"skills", r"skills required", r"required skills", r"key skills",
        r"technical skills", r"must have skills", r"desired skills"),
    "employment_type": _label_pattern(
        r"job type", r"job types", r"employment type", r"schedule",
        r"work type"),
    "salary_text": _label_pattern(
        r"salary", r"pay", r"compensation", r"ctc", r"package",
        r"estimated salary"),
    "location": _label_pattern(r"location", r"job location", r"work location"),
    "company_name": _label_pattern(r"company", r"company name", r"employer"),
    "posted_date": _label_pattern(r"posted", r"posted on", r"date posted"),
}


def read_labelled_fields(lines):
    """``{field: value}`` for every label found.  Absent labels are absent."""
    found = {}
    for index, line in enumerate(lines):
        if not line or len(line) > 80:
            # A label line is short.  An 800-character paragraph that opens
            # with the word "Experience" is prose, not a label.
            continue
        for field, pattern in _LABELS.items():
            if field in found:
                continue
            match = pattern.match(line)
            if not match:
                continue
            value = match.group(1).strip(" :-–\t")
            if not value:
                # "Label" on its own line: the value is the next non-blank.
                for follower in lines[index + 1:index + 4]:
                    if follower:
                        value = follower
                        break
            if value and not _FURNITURE_LINE.match(value):
                found[field] = value
    return found


# ===========================================================================
# 3. SHAPE RECOGNISERS
# ===========================================================================
# Used for the fields a job page states WITHOUT a label.  Each one answers
# "could this line be an X?" so a positional guess is checked before it is
# believed.

# NOTE ON THE WORD BOUNDARIES: an earlier version of this pattern used a
# bare "rs\.?" alternative, which matches the "rs" inside "3.8 out of 5
# staRS" -- so a company line carrying a star rating was read as a salary
# and the real salary line was then skipped. Every currency token is
# anchored with \b for that reason; the test
# test_extractor.py::test_company_rating_line_is_not_a_salary pins it.
_SALARY_SHAPE = re.compile(
    r"(?:₹|\brs\.?\s*\d|\binr\b|\blpa\b|\blakhs?\b|\blacs?\b|"
    r"\bcrores?\b|\bper annum\b|\bp\.?a\.?\b)|"
    r"\d[\d,.]*\s*(?:-|–|to)\s*[₹]?\s*\d[\d,.]*\s*"
    r"(?:a|per)\s+(?:year|month|week|hour|annum)|"
    r"\d[\d,.]*\s*(?:a|per)\s+(?:year|month|week|hour|annum)",
    re.IGNORECASE,
)

_EMPLOYMENT_SHAPE = re.compile(
    r"^\s*(?:full[\s-]?time|part[\s-]?time|contract(?:ual)?|contract to hire|"
    r"c2h|permanent|temporary|internship|intern|apprenticeship|freelance|"
    r"volunteer|fresher|regular|seasonal)"
    r"(?:\s*[,/+&]\s*(?:full[\s-]?time|part[\s-]?time|contract(?:ual)?|"
    r"permanent|temporary|internship|freelance|regular))*\s*$",
    re.IGNORECASE,
)

# "Pune, Maharashtra" / "Remote in Pune, Maharashtra" / "Pune, Maharashtra
# 411001" / "Hybrid work in Bengaluru, Karnataka".  Deliberately requires a
# comma or an explicit remote/hybrid word, so a one-word company name is not
# mistaken for a location.
# NOTE ON THE CASE FLAGS: the remote/hybrid PREFIX is matched
# case-insensitively with an inline (?i:...) group, because a page writes
# "Remote in Pune" with a capital R.  The CITY part stays case-SENSITIVE on
# purpose: requiring a capital letter is what distinguishes a place name
# from a sentence, so "we are looking for, among others" is not read as a
# location.  An earlier version made the whole pattern case-sensitive and
# silently failed on every "Remote in ..." and "Hybrid work in ..." line;
# test_location_shapes pins both.
_LOCATION_SHAPE = re.compile(
    r"^\s*(?i:"
    r"(?:remote|hybrid|work from home|temporarily remote|on-?site)"
    r"(?:\s+(?:in|work in|job in|from))?\s*,?\s*"
    r")?"
    r"(?:[A-Z][\w.'&-]*(?:\s+[A-Z][\w.'&-]*){0,4})"
    r"(?:\s*,\s*[A-Z][\w.'&-]*(?:\s+[A-Z][\w.'&-]*){0,3})"
    r"(?:\s*,?\s*(?:India|\d{6}))?\s*$")

_REMOTE_ONLY_SHAPE = re.compile(
    r"^\s*(?:remote|hybrid remote|work from home|hybrid work|fully remote)\s*$",
    re.IGNORECASE)

# A company line commonly carries a rating: "Example Technologies 3.8" or
# "Example Technologies 3.8 out of 5 stars".
_RATING_TAIL = re.compile(
    r"\s*(?:[0-5]\.\d)\s*(?:out of 5(?:\s*stars)?|stars?)?\s*$",
    re.IGNORECASE)

_REVIEW_TAIL = re.compile(r"\s*[-–|]?\s*\d[\d,]*\s*reviews?\s*$",
                          re.IGNORECASE)


def looks_like_salary(line):
    return bool(line) and bool(_SALARY_SHAPE.search(line)) and len(line) <= 120


def looks_like_employment_type(line):
    return bool(line) and bool(_EMPLOYMENT_SHAPE.match(line))


def looks_like_location(line):
    if not line or len(line) > 90:
        return False
    if _REMOTE_ONLY_SHAPE.match(line):
        return True
    return bool(_LOCATION_SHAPE.match(line))


def tidy_company(line):
    """Strip the rating and review-count tails off a company line."""
    text = _REVIEW_TAIL.sub("", str(line or "")).strip()
    text = _RATING_TAIL.sub("", text).strip()
    return text


# ===========================================================================
# 4. THE PARSER
# ===========================================================================

class ParsedJob(object):
    """What the clipboard could be made to yield for one job.

    ``raw`` is the dict handed to the original ``extract_job_details()``.
    ``unavailable`` names the fields the page did not state, so the log can
    say "salary: unavailable" instead of the row quietly carrying a zero.
    """

    def __init__(self, raw, unavailable, description_chars=0, notes=None):
        self.raw = raw
        self.unavailable = list(unavailable)
        self.description_chars = int(description_chars)
        self.notes = list(notes or [])

    @property
    def job_title(self):
        return self.raw.get("job_title", "")

    @property
    def company_name(self):
        return self.raw.get("company_name", "")

    def __repr__(self):                                  # pragma: no cover
        return "ParsedJob(%r @ %r, missing=%s)" % (
            self.job_title, self.company_name, ",".join(self.unavailable))


#: Fields that are only ever read from the page, never defaulted.
_OPTIONAL_FIELDS = ("salary_text", "employment_type", "experience_required",
                    "skills_required", "posted_date", "location")


def parse_job_text(text, apply_url="", input_row=None,
                   expected_title=""):
    """Clipboard text for ONE job detail page -> a ``ParsedJob``.

    ``apply_url`` is the url copied out of that window's address bar.  It is
    the job's own stable detail url, so it becomes ``source_url`` AND
    ``apply_url``; the distinction between the two is explained in
    README.md, "The Apply URL column".
    """
    input_row = input_row or {}
    notes = []

    body = cut_related_jobs(text)
    if len(body) < len(str(text or "")):
        notes.append("related-jobs rail cut off before parsing")

    all_lines = _lines(body)
    clean = strip_furniture(all_lines)

    # -- split header block from description ------------------------------
    description_at = None
    for index, line in enumerate(clean):
        if _DESCRIPTION_HEADING.match(line):
            description_at = index
            break

    if description_at is None:
        # No heading.  The description is then everything from the first
        # long paragraph onwards -- a job page's first 200-character line is
        # prose, not a header field.
        for index, line in enumerate(clean):
            if len(line) >= 200:
                description_at = index
                break

    if description_at is None:
        header = clean
        description_lines = []
        notes.append("no description heading and no long paragraph found")
    else:
        header = clean[:description_at]
        description_lines = clean[description_at + 1:] \
            if _DESCRIPTION_HEADING.match(clean[description_at]) \
            else clean[description_at:]

    labelled = read_labelled_fields(clean)

    # -- title ------------------------------------------------------------
    # The first header line that is not a recognisable location, salary or
    # employment type.  A job page leads with its title.
    job_title = ""
    title_index = None
    for index, line in enumerate(header):
        if not line:
            continue
        if looks_like_salary(line) or looks_like_employment_type(line):
            continue
        if looks_like_location(line) and index > 0:
            continue
        job_title = line
        title_index = index
        break

    # -- company ----------------------------------------------------------
    # The rating/review tail is stripped BEFORE the shape checks, not after:
    # "Example Technologies Pvt Ltd 3.8 out of 5 stars" has to be judged as
    # the company name it is, not as the number it ends with.
    company_name = tidy_company(labelled.get("company_name", ""))
    company_index = None
    if not company_name and title_index is not None:
        for offset, line in enumerate(header[title_index + 1:title_index + 5]):
            if not line:
                continue
            candidate = tidy_company(line)
            if not candidate:
                continue
            if looks_like_salary(candidate) \
                    or looks_like_employment_type(candidate) \
                    or looks_like_location(candidate):
                continue
            company_name = candidate
            company_index = title_index + 1 + offset
            break

    # -- location / salary / employment type ------------------------------
    location = labelled.get("location", "")
    salary_text = labelled.get("salary_text", "")
    employment_type = labelled.get("employment_type", "")

    for index, line in enumerate(header):
        if not line:
            continue
        # The title line and the company line are already accounted for;
        # re-reading either of them is how a company name ends up in the
        # salary column.
        if index == title_index or index == company_index:
            continue
        if not location and looks_like_location(line) and line != job_title \
                and line != company_name:
            location = line
        if not salary_text and looks_like_salary(line):
            salary_text = line
        if not employment_type and looks_like_employment_type(line):
            employment_type = line

    # -- description ------------------------------------------------------
    description = "\n".join(description_lines).strip()
    # clean_description() is the ORIGINAL project's cleaner: it keeps
    # paragraphs and bullets and drops the furniture it recognises.
    description = clean_description(description)

    # -- raw dict, in the shape the original extractor expects ------------
    raw = {}

    def put(key, value):
        value = str(value or "").strip()
        if value:
            raw[key] = value

    put("job_title", job_title)
    put("company_name", company_name)
    put("location", location)
    put("job_description", description)
    put("salary_text", salary_text)
    put("employment_type", employment_type)
    put("experience_required", labelled.get("experience_required", ""))
    put("skills_required", labelled.get("skills_required", ""))
    put("posted_date", labelled.get("posted_date", ""))

    # The url copied from the address bar is the job's own detail url, so it
    # is BOTH the stable source_url and the Apply URL this workflow was
    # asked to record.  It is never synthesised: when the address bar could
    # not be read, the caller does not reach this function.
    if apply_url:
        put("source_url", apply_url)
        put("apply_url", apply_url)

    # -- what the page did not say ----------------------------------------
    unavailable = [field for field in _OPTIONAL_FIELDS if field not in raw]
    if not description:
        unavailable.append("job_description")
    if not company_name:
        unavailable.append("company_name")
    if not job_title:
        unavailable.append("job_title")

    if expected_title and job_title and not title_matches(job_title,
                                                          expected_title):
        notes.append("parsed title %r does not match expected %r"
                     % (job_title[:40], str(expected_title)[:40]))

    return ParsedJob(raw, unavailable, len(description), notes)


# ===========================================================================
# 5. TITLE CROSS-CHECK
# ===========================================================================

def _normalise_title(text):
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9+#.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_matches(parsed_title, expected_title, min_overlap=0.5):
    """Loose agreement between a parsed title and one from another source.

    Used for the "incorrect copied job title" failure test.  It is a word
    overlap rather than equality, because a listing card and a detail page
    legitimately differ ("Backend Developer" vs "Backend Developer - Python").
    """
    left = set(_normalise_title(parsed_title).split())
    right = set(_normalise_title(expected_title).split())
    if not left or not right:
        return False
    smaller = min(len(left), len(right))
    return (len(left & right) / float(smaller)) >= float(min_overlap)


# ===========================================================================
# 6. THE WHOLE STEP, END TO END
# ===========================================================================

# ---------------------------------------------------------------------------
# THE APPLY URL COLUMN -- a deliberate divergence, stated out loud
# ---------------------------------------------------------------------------
# The ORIGINAL project's indeed_apply_url.py deliberately BLANKS an
# Indeed-hosted detail url in the apply_url column.  Its reasoning is sound
# and documented at length: copying the detail url into apply_url makes
# every row look as though it has an application destination, so a job
# seeker who clicks "Apply" is sent back to a description page.  It
# classifies `in.indeed.com/viewjob?jk=...` as "not_an_application".
#
# Brief section 13 asks for the opposite, explicitly and twice: "Save it in
# the existing Excel Apply URL field" and "Do not replace it with the
# listing-page URL".  It also names the distinction itself: "The copied
# address is the requested Apply URL for this workflow; it is not
# necessarily the employer's final external application destination.  If
# the existing Indeed schema distinguishes those concepts, document the
# distinction without changing the column structure."
#
# So: the brief wins, because it is an instruction rather than an
# inference, and APPLY_URL_FROM_WINDOW makes it switchable rather than
# silent.  What lands in the column is the url of the window the data was
# read from -- an Indeed-hosted job page, not an employer's ATS.  The
# column structure is untouched; only these two values' policy differs, and
# the row carries `_apply_url_kind` so the difference is auditable.
APPLY_URL_FROM_WINDOW = True

#: The canonical job page. Indeed's own permalink for a job is
#: https://in.indeed.com/viewjob?jk=<key>, and the key is exactly what the
#: results page carries as vjk=<key> for the selected card. So a card url
#:     https://in.indeed.com/jobs?q=full+stack+developer&l=Delhi&...&vjk=cba10d8415b155ab
#: becomes
#:     https://in.indeed.com/viewjob?jk=cba10d8415b155ab
#: The leading "v" is the only difference between the two parameter names.
INDEED_JOB_URL_TEMPLATE = "https://in.indeed.com/viewjob?jk=%s"

#: The site every row came from. One constant for every job, by request.
#: See the WARNING in identity_keys(): because this no longer identifies a
#: job, it must not be used to recognise one.
INDEED_SOURCE_URL = "https://in.indeed.com/"

#: vjk= (a card selected on a results page) or jk= (a job page).
_JOB_KEY_IN_URL = re.compile(r"[?&](?:vjk|jk|jobkey)=([A-Za-z0-9_-]+)",
                             re.IGNORECASE)


def job_key_from_url(url):
    """Indeed's job key out of any of its urls, or "" when there is none."""
    match = _JOB_KEY_IN_URL.search(str(url or ""))
    return match.group(1) if match else ""


def canonical_job_url(url_or_key):
    """https://in.indeed.com/viewjob?jk=<key>, or "" when there is no key.

    Never invents: given a url with no job key in it, the answer is blank
    and the apply_url column stays empty.
    """
    text = str(url_or_key or "").strip()
    if not text:
        return ""
    key = job_key_from_url(text)
    if not key and re.fullmatch(r"[A-Za-z0-9_-]{8,}", text):
        key = text                       # already a bare job key
    if not key:
        return ""
    return INDEED_JOB_URL_TEMPLATE % key


def apply_the_window_url(row, apply_url):
    """Set apply_url and source_url from the card url.

    apply_url   the job's own Indeed permalink, built from the card's
                vjk= key -- NOT the results-page url the card was selected
                on, which carries the search terms and tracking parameters
                and is the same page for sixteen different jobs.
    source_url  the site constant, the same for every row.

    Returns the row.  With no job key in ``apply_url`` nothing is invented:
    the existing values are left exactly as the original extractor set them.
    """
    if not APPLY_URL_FROM_WINDOW:
        return row

    canonical = canonical_job_url(apply_url)
    if not canonical:
        return row

    row["apply_url"] = canonical
    row["source_url"] = INDEED_SOURCE_URL
    row["_apply_url_kind"] = "indeed_job_permalink"
    row["_apply_url_reason"] = (
        "built from the selected card's job key (vjk -> jk); this is the "
        "Indeed job page, not necessarily the employer's external "
        "application destination")
    return row


def build_row(text, apply_url, input_row=None, state_resolver=None,
              fetched_at=None, expected_title=""):
    """``(row, parsed)`` -- clipboard text to a complete 32-column row.

    The row is produced by the ORIGINAL ``extract_job_details()``, so every
    column, its order and its normalisation are exactly what the existing
    collector writes.  The one value this project decides for itself is
    apply_url; see APPLY_URL_FROM_WINDOW above for why.
    """
    parsed = parse_job_text(text, apply_url=apply_url, input_row=input_row,
                            expected_title=expected_title)
    row = extract_job_details(parsed.raw, input_row=input_row,
                              state_resolver=state_resolver,
                              fetched_at=fetched_at)
    row = apply_the_window_url(row, apply_url)
    return row, parsed


__all__ = [
    "DETAIL_COLUMNS", "SOURCE_PLATFORM", "SOURCE_TYPE", "UPSTREAM_FILE",
    "ParsedJob", "build_row", "parse_job_text", "cut_related_jobs",
    "strip_furniture", "read_labelled_fields", "looks_like_salary",
    "looks_like_employment_type", "looks_like_location", "tidy_company",
    "title_matches", "extract_job_details", "row_for_excel", "validate_row",
    "apply_the_window_url", "APPLY_URL_FROM_WINDOW",
    "canonical_job_url", "job_key_from_url",
    "INDEED_JOB_URL_TEMPLATE", "INDEED_SOURCE_URL",
    "clean_description", "clean_value", "now_utc", "extract_internal_job_id",
]
