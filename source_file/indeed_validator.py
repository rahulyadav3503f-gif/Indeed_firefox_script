"""Row validation, non-IT filtering and duplicate detection.

WHAT IS REUSED RATHER THAN REWRITTEN (brief sections 16, 17)
------------------------------------------------------------
    validate_row()      the ORIGINAL project's rule for "is this row worth
                        saving" -- title, company, a stable per-job
                        source_url, and all 32 columns present.
    is_non_it_title()   the ORIGINAL blocklist-with-IT-override.  Not
                        re-tuned, not re-ordered, not extended: the brief
                        says preserve the semantics, so the function is
                        imported and called, never copied.

WHAT THIS MODULE ADDS
---------------------
The duplicate problem the original project solves against a DataFrame, and
that this project also has to solve in memory, several times over:

    * within one keyword+city combination, across the cards of one page;
    * across the pages of one combination;
    * against everything already written to this rank's workbook;
    * and across combinations, because the same job legitimately appears
      under "DevOps Engineer" and under "Cloud Engineer".

``DuplicateIndex`` is the single answer to all four.  It keys on the job's
STABLE identity, not on its title:

    1. ``internal_job_id``  -- Indeed's own ``jk``, when the url carried one
    2. ``source_url``       -- normalised: scheme, host, path and jk only
    3. ``job_id``           -- the original project's content hash

Brief section 17: "Avoid assuming job title alone uniquely identifies a
job."  Title is never a key here.  Two different companies advertising
"Network Engineer" in Pune are two jobs, and they both get saved.
"""

import re
from urllib.parse import parse_qsl, urlparse, urlunparse

from target_audience_roles import is_non_it_title
from .indeed_extractor import DETAIL_COLUMNS, clean_value, validate_row

# Query parameters that identify the job, as opposed to the click that got
# you there.  Everything else is dropped when a url is normalised, so the
# same job reached from two different search result pages compares equal.
_IDENTIFYING_PARAMS = ("jk", "vjk", "jobkey", "id")


def normalise_job_url(url):
    """A url reduced to the part that identifies the JOB.

    ``.../viewjob?jk=ABC&from=serp&tk=1h2&vjs=3``
        -> ``https://in.indeed.com/viewjob?jk=ABC``

    Tracking parameters differ on every visit, so comparing raw urls counts
    one job as several.  This is the normalisation that stops that.
    """
    text = clean_value(url)
    if not text:
        return ""
    try:
        parts = urlparse(text)
    except ValueError:
        return text.strip().lower()

    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parts.path or "").rstrip("/").lower() or "/"

    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        if key.lower() in _IDENTIFYING_PARAMS and value:
            kept.append("%s=%s" % (key.lower(), value))
    kept.sort()

    return urlunparse((parts.scheme.lower() or "https", host, path, "",
                       "&".join(kept), ""))


_JK_IN_URL = re.compile(r"[?&](?:jk|vjk|jobkey)=([A-Za-z0-9_-]+)",
                        re.IGNORECASE)


def job_key_of(row_or_url):
    """Indeed's own job key, from a row or a url.  Blank when unknowable."""
    if isinstance(row_or_url, dict):
        key = clean_value(row_or_url.get("internal_job_id"))
        if key:
            return str(key)
        url = clean_value(row_or_url.get("source_url")) \
            or clean_value(row_or_url.get("apply_url"))
    else:
        url = clean_value(row_or_url)
    if not url:
        return ""
    match = _JK_IN_URL.search(url)
    return match.group(1) if match else ""


def identity_keys(row):
    """Every key this row can be recognised by, strongest first.

    A row with no key at all gets an empty set, and ``DuplicateIndex`` then
    refuses it -- an unidentifiable row cannot be de-duplicated, so saving
    it would mean saving it again on the next pass.
    """
    keys = []
    job_key = job_key_of(row)
    if job_key:
        keys.append("jk:%s" % job_key.lower())

    # A URL IS ONLY AN IDENTITY IF IT IDENTIFIES A JOB.
    #
    # source_url is now the site constant "https://in.indeed.com/" for every
    # row. Using it as a recognition key would mean every job after the
    # first collided with it and was thrown away as a duplicate -- the whole
    # crawl would save exactly one row. So a url is only taken as a key when
    # it actually carries a job key; apply_url (the job's own permalink,
    # .../viewjob?jk=<key>) is preferred, and source_url is used only if it
    # happens to identify a job too.
    candidates = []
    if isinstance(row, dict):
        candidates = [row.get("apply_url"), row.get("source_url")]
    else:
        candidates = [row]
    for candidate in candidates:
        url = normalise_job_url(candidate)
        if url and _JK_IN_URL.search(url):
            keys.append("url:%s" % url)
            break
    if isinstance(row, dict):
        job_id = clean_value(row.get("job_id"))
        if job_id:
            keys.append("id:%s" % str(job_id).lower())
    return keys


class DuplicateIndex(object):
    """Every job identity this rank has already dealt with.

    Three sets, because the brief asks three different questions of them:

        saved      written to Excel.  Never written twice.
        seen       examined at all, saved or not.  This is what
                   TARGET_UNIQUE_JOBS counts (see below), and what makes
                   "this page brought nothing new" a reliable end-of-results
                   signal.
        rejected   examined and refused (non-IT, invalid).  Kept separately
                   so a rejected job is not re-examined, and so the log can
                   tell "100 saved" from "100 looked at".
    """

    def __init__(self):
        self.saved = set()
        self.seen = set()
        self.rejected = set()

    # -- loading --------------------------------------------------------
    def load_saved_rows(self, rows):
        """Seed ``saved`` from rows already in the workbook."""
        count = 0
        for row in rows or []:
            keys = identity_keys(row)
            if keys:
                self.saved.update(keys)
                self.seen.update(keys)
                count += 1
        return count

    def load_seen_urls(self, urls):
        """Seed ``seen`` from a checkpoint's ``done_job_urls``."""
        count = 0
        for url in urls or []:
            key = normalise_job_url(url)
            if not key:
                continue
            self.seen.add("url:%s" % key)
            job_key = job_key_of(url)
            if job_key:
                self.seen.add("jk:%s" % job_key.lower())
            count += 1
        return count

    # -- asking ---------------------------------------------------------
    def is_saved(self, row):
        return any(key in self.saved for key in identity_keys(row))

    def is_seen(self, row):
        return any(key in self.seen for key in identity_keys(row))

    def is_rejected(self, row):
        return any(key in self.rejected for key in identity_keys(row))

    # -- telling --------------------------------------------------------
    def mark_seen(self, row):
        keys = identity_keys(row)
        self.seen.update(keys)
        return bool(keys)

    def mark_saved(self, row):
        keys = identity_keys(row)
        if not keys:
            return False
        self.saved.update(keys)
        self.seen.update(keys)
        return True

    def mark_rejected(self, row):
        keys = identity_keys(row)
        self.rejected.update(keys)
        self.seen.update(keys)
        return bool(keys)

    @property
    def unique_seen(self):
        """How many DISTINCT jobs have been examined.

        Counts ``jk:`` keys where they exist and ``url:`` keys otherwise, so
        one job with both keys counts once rather than twice.
        """
        job_keys = {key for key in self.seen if key.startswith("jk:")}
        urls = {key for key in self.seen if key.startswith("url:")}
        # A url whose jk is already counted must not be counted again.
        counted_jks = {key[3:] for key in job_keys}
        extra = {url for url in urls
                 if (job_key_of(url[4:]) or "").lower() not in counted_jks}
        return len(job_keys) + len(extra)

    @property
    def unique_saved(self):
        job_keys = {key for key in self.saved if key.startswith("jk:")}
        urls = {key for key in self.saved if key.startswith("url:")}
        counted_jks = {key[3:] for key in job_keys}
        extra = {url for url in urls
                 if (job_key_of(url[4:]) or "").lower() not in counted_jks}
        return len(job_keys) + len(extra)


# ===========================================================================
# THE DECISION
# ===========================================================================

class Decision(object):
    """Why one row was accepted or refused.

    ``outcome`` is one of:
        "save"        write it
        "duplicate"   already in this rank's data
        "non_it"      is_non_it_title() refused the title
        "invalid"     validate_row() refused it
        "unidentified" no stable identity, so it cannot be de-duplicated

    Brief restriction 12: "Do not claim a job was saved unless its data was
    actually written successfully."  A Decision of "save" is a decision, not
    a claim -- the claim is made by indeed_excel.append_row(), and only
    after the workbook is on disk.
    """

    SAVE = "save"
    DUPLICATE = "duplicate"
    NON_IT = "non_it"
    INVALID = "invalid"
    UNIDENTIFIED = "unidentified"

    def __init__(self, outcome, reason=""):
        self.outcome = outcome
        self.reason = reason

    @property
    def should_save(self):
        return self.outcome == self.SAVE

    def __repr__(self):                                  # pragma: no cover
        return "Decision(%s, %r)" % (self.outcome, self.reason)

    def __str__(self):
        return self.outcome if not self.reason \
            else "%s (%s)" % (self.outcome, self.reason)


def decide(row, index, require_identity=True):
    """Should this row be saved?  Order matters and is deliberate.

    1.  validate_row()   -- the original project's minimum.  A row with no
                            title or no stable url is refused first,
                            because the later checks depend on both.
    2.  identity         -- a row that cannot be identified cannot be
                            de-duplicated.  Refusing it here is what stops
                            the same unidentifiable job being written on
                            every pass.
    3.  is_non_it_title()-- the original filter, unchanged.
    4.  duplicate        -- last, so a duplicate non-IT row is reported as
                            non-IT: the more useful of the two facts.
    """
    if not isinstance(row, dict):
        return Decision(Decision.INVALID, "row is not a dict")

    is_valid, reason = validate_row(row)
    if not is_valid:
        return Decision(Decision.INVALID, reason)

    keys = identity_keys(row)
    if require_identity and not keys:
        return Decision(
            Decision.UNIDENTIFIED,
            "no job key, no source_url and no job_id -- this row could not "
            "be recognised again, so it cannot be de-duplicated")

    title = clean_value(row.get("job_title"))
    if title and is_non_it_title(title):
        return Decision(Decision.NON_IT, "non-IT title: %s" % title[:60])

    if index is not None and index.is_saved(row):
        return Decision(Decision.DUPLICATE,
                        "already saved: %s" % (keys[0] if keys else "?"))

    return Decision(Decision.SAVE)


def missing_columns(row):
    """Columns of the 32 that this row does not carry at all."""
    if not isinstance(row, dict):
        return list(DETAIL_COLUMNS)
    return [column for column in DETAIL_COLUMNS if column not in row]


def blank_columns(row):
    """Columns present but empty -- what the page did not state."""
    if not isinstance(row, dict):
        return list(DETAIL_COLUMNS)
    return [column for column in DETAIL_COLUMNS
            if not clean_value(row.get(column))]


__all__ = [
    "Decision", "DuplicateIndex", "decide", "identity_keys", "job_key_of",
    "normalise_job_url", "is_non_it_title", "validate_row",
    "missing_columns", "blank_columns",
]
