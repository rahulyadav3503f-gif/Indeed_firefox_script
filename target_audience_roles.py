"""The complete keyword plan -- RE-EXPORTED from the AUTHORITATIVE file.

WHICH FILE, AND WHY IT CHANGED
------------------------------
The change request supplied a new ``target_audience_roles.py`` and made it
the authoritative source, replacing the 85-role file this project used
before.  The difference is not cosmetic:

    OLD (85 keywords)     Track A only.  IT infrastructure roles.
                          is_non_it_title("Staff Nurse") -> True (DROP).

    NEW (1264 keywords)   Track A (200: the 15 priority profiles expanded
                          into real search synonyms, plus the rest of the
                          target audience, plus 40 trending IT roles) AND
                          Track B (1064: fresher-plausible titles across
                          116 departments).
                          is_non_it_title("Staff Nurse") -> False (KEEP),
                          role_department("Staff Nurse") -> "Nursing".

Both numbers are measured, not quoted: see tests/test_role_plan.py.

So ``is_non_it_title`` keeps its name and its contract (True means drop the
row) but is now a two-track whitelist rather than an IT-only blocklist.  The
change request is explicit that this new filtering behaviour is to be
preserved rather than re-restricted to IT, so nothing in this project
re-filters what it returns.

THIS FILE DECLARES NO ROLES OF ITS OWN
--------------------------------------
"Do not create another hardcoded list of job roles or cities."  It loads
``vendor/target_audience_roles.py`` -- the authoritative file, copied in
verbatim, md5 recorded in vendor/PROVENANCE.json -- and re-publishes its
names, so

    from target_audience_roles import build_role_plan

resolves to the authoritative definitions and there is exactly one role list
in this project.  See upstream.load_vendored for why it is a copy.
"""

from upstream import load_vendored as _load_vendored

_authoritative = _load_vendored("target_audience_roles")

# -- the plan ---------------------------------------------------------------
#: The complete current keyword list.  Obtained DYNAMICALLY, as required:
#: nothing in this project hardcodes a count or a subset of it.
build_role_plan = _authoritative.build_role_plan
role_plan_split = _authoritative.role_plan_split
role_plan_breakdown = _authoritative.role_plan_breakdown

# -- filtering (two-track, preserved exactly as delivered) ------------------
is_non_it_title = _authoritative.is_non_it_title          # alias kept by the
is_out_of_scope_title = _authoritative.is_out_of_scope_title   # new file
is_out_of_scope_row = _authoritative.is_out_of_scope_row
classify_job = _authoritative.classify_job
is_senior_title = _authoritative.is_senior_title

# -- department classification (so a nursing row is not "IT Department") ----
role_department = _authoritative.role_department
DEFAULT_DEPARTMENT = _authoritative.DEFAULT_DEPARTMENT
FRESHER_ROLES_BY_DEPARTMENT = _authoritative.FRESHER_ROLES_BY_DEPARTMENT
fresher_roles_by_department = _authoritative.fresher_roles_by_department

# -- the role groups, re-exported verbatim ----------------------------------
PRIORITY_PROFILE_KEYWORDS = _authoritative.PRIORITY_PROFILE_KEYWORDS
PRIORITY_ROLES = _authoritative.PRIORITY_ROLES
TARGET_ROLES_IT_SUPPORT = _authoritative.TARGET_ROLES_IT_SUPPORT
TARGET_ROLES_NETWORK = _authoritative.TARGET_ROLES_NETWORK
TARGET_ROLES_SYSTEM = _authoritative.TARGET_ROLES_SYSTEM
TARGET_ROLES_CLOUD = _authoritative.TARGET_ROLES_CLOUD
TARGET_AUDIENCE_ROLES = _authoritative.TARGET_AUDIENCE_ROLES
HIGH_DEMAND_IT_ROLES = _authoritative.HIGH_DEMAND_IT_ROLES
TRENDING_IT_ROLES = _authoritative.TRENDING_IT_ROLES
TRACK_A_ROLES = _authoritative.TRACK_A_ROLES

# -- the module's own configuration switches, preserved ---------------------
DROP_SENIOR_TITLES = _authoritative.DROP_SENIOR_TITLES
FRESHER_ROLES_PER_DEPARTMENT = _authoritative.FRESHER_ROLES_PER_DEPARTMENT
STRICT_EXPERIENCE_MODE = _authoritative.STRICT_EXPERIENCE_MODE
PRIORITY_HEAD_SIZE = _authoritative.PRIORITY_HEAD_SIZE

#: Absolute path of the file these names actually come from.
SOURCE_FILE = getattr(_authoritative, "__file__", "")

__all__ = [
    "build_role_plan", "role_plan_split", "role_plan_breakdown",
    "is_non_it_title", "is_out_of_scope_title", "is_out_of_scope_row",
    "classify_job", "is_senior_title",
    "role_department", "DEFAULT_DEPARTMENT", "FRESHER_ROLES_BY_DEPARTMENT",
    "fresher_roles_by_department",
    "PRIORITY_PROFILE_KEYWORDS", "PRIORITY_ROLES",
    "TARGET_ROLES_IT_SUPPORT", "TARGET_ROLES_NETWORK", "TARGET_ROLES_SYSTEM",
    "TARGET_ROLES_CLOUD", "TARGET_AUDIENCE_ROLES", "HIGH_DEMAND_IT_ROLES",
    "TRENDING_IT_ROLES", "TRACK_A_ROLES",
    "DROP_SENIOR_TITLES", "FRESHER_ROLES_PER_DEPARTMENT",
    "STRICT_EXPERIENCE_MODE", "PRIORITY_HEAD_SIZE", "SOURCE_FILE",
]
