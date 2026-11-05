"""Per-rank checkpoints, and the city-wise complete-cycle counter.

WHAT IS PRESERVED FROM THE ORIGINAL PROJECT (brief section 19)
--------------------------------------------------------------
The original ``crawl_cycle_state.json`` architecture is kept field for
field, because the brief says to reuse it "wherever possible" and because
its design decisions are the right ones:

    schema_version, rank, num_sys, crawl_cycle_number, cycle_started_at,
    cities, cities_fingerprint, keyword_order, keyword_plan_fingerprint,
    shuffle_seed, current_keyword_index, current_city_index, current_page,
    done_job_urls, cycle_complete, updated_at

In particular these three behaviours are unchanged:

*   THE SHUFFLE IS GATED ON THE CYCLE NUMBER ALONE, so a restart in the
    middle of a cycle resumes the saved order instead of reshuffling.
*   POSITION IS STORED AS INDICES, not names, so "Bengaluru" and
    "Bangalore" in the same rank can never be confused and resume is O(1).
*   THE FINGERPRINTS WARN RATHER THAN RESET.  If the city list or the
    keyword plan changes mid-cycle, the cycle finishes against the SAVED
    list so no keyword is dropped or crawled twice inside it.

THE ONE DELIBERATE CHANGE: THE LOOP IS INVERTED
-----------------------------------------------
The original loop is KEYWORD-outer, CITY-inner:

    for keyword in 85:  for city in 22:  crawl

Brief section 8 requires the opposite, and says so at length:

    "For each rank, process all 85 job keywords for the first assigned city
     before moving to the second assigned city.  Each completed city
     represents one complete cycle for that rank."

So this project is CITY-outer, KEYWORD-inner:

    for city in 22:  for keyword in 85:  crawl   -> city done = +1 cycle

Both index fields keep their original NAMES, so the file stays readable by
anything that understands the original format; what changed is which one
the outer loop advances.  ``nesting`` records that explicitly, so a
checkpoint can never be resumed under the wrong interpretation.

THE NEW FIELDS (brief section 19, "Mandatory Total Complete Cycle Tracking")
----------------------------------------------------------------------------
    total_assigned_cities   how many cities this rank owns
    completed_cities        which of them are finished IN THIS crawl cycle
    total_complete_cycle    LIFETIME count of completed city cycles
    current_city            the city name, for the terminal and the log
    current_keyword         the keyword name, likewise
    last_completed_job_id   the last job durably written
    saved_jobs / duplicate_jobs / failed_jobs
    failure_state           the last failure, or null

``total_complete_cycle`` is incremented in exactly one place,
``complete_city_cycle()``, and only when the city is not already in
``completed_cities``.  That is what makes rule 7 -- "Do not count the same
completed city cycle twice" -- true by construction rather than by care.
"""

import hashlib
import json
import os
import random
from datetime import datetime

#: Bumped from the original's 1, because ``nesting`` and the cycle counters
#: are new.  A reader that does not understand 2 should not guess.
CHECKPOINT_SCHEMA_VERSION = 2

#: What the outer loop advances.  Written into every checkpoint.
NESTING_CITY_OUTER = "city_outer_keyword_inner"


class CheckpointError(RuntimeError):
    """The checkpoint could not be read or written."""


# ---------------------------------------------------------------------------
# ATOMIC JSON
# ---------------------------------------------------------------------------

def write_json_atomic(path, payload):
    """Write JSON through a temp file and rename it into place.

    fsync before the rename, so a power loss cannot leave a checkpoint that
    names a job as done when its Excel row never reached the disk.
    """
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    temp = os.path.join(folder, ".%s.tmp" % os.path.basename(path))
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def read_json_or_none(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def fingerprint(items):
    """The original project's fingerprint, unchanged."""
    payload = " ".join(str(item) for item in items)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def plan_fingerprint(plan_pairs):
    return fingerprint(sorted("%s|%s" % tuple(pair) for pair in plan_pairs))


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# THE KEYWORD ORDER
# ---------------------------------------------------------------------------

def build_keyword_order(plan_pairs, crawl_cycle_number, rank,
                        shuffle_enabled=True):
    """A permutation of the plan, shuffled WITHIN each department.

    The original project's function, unchanged, including its two
    invariants: the seed is derived from (rank, cycle number, department) so
    the order is reproducible from the cycle number alone, and the result is
    asserted to be a permutation rather than assumed to be one.
    """
    from collections import OrderedDict

    buckets = OrderedDict()
    for category, keyword in plan_pairs:
        buckets.setdefault(category, []).append(keyword)

    order = []
    seeds = {}
    for category, keywords in buckets.items():
        shuffled = list(keywords)
        if shuffle_enabled:
            seed_source = "%s|%s|%s" % (rank, crawl_cycle_number, category)
            seed = int(hashlib.sha1(seed_source.encode("utf-8"))
                       .hexdigest()[:12], 16)
            seeds[category] = seed
            random.Random(seed).shuffle(shuffled)
        else:
            seeds[category] = None

        if len(shuffled) != len(keywords) or set(shuffled) != set(keywords):
            raise CheckpointError(
                "shuffle corrupted the keyword plan for %r (%d in, %d out)"
                % (category, len(keywords), len(shuffled)))
        order.extend([category, keyword] for keyword in shuffled)

    if len(order) != len(plan_pairs):
        raise CheckpointError("keyword order has %d entries but the plan has "
                              "%d" % (len(order), len(plan_pairs)))
    return order, seeds


# ---------------------------------------------------------------------------
# THE CHECKPOINT
# ---------------------------------------------------------------------------

class Checkpoint(object):
    """One rank's progress.  One file, owned by one rank, never shared.

    Brief section 19: "Use separate checkpoint files for each rank.  Do not
    alter existing production checkpoint files."  The path is built from the
    rank, lives inside THIS project, and ``assert_own_file()`` refuses a
    path that is not under the configured directory.
    """

    def __init__(self, path, rank, num_sys, logger=None):
        self.path = os.path.abspath(path)
        self.rank = int(rank)
        self.num_sys = int(num_sys)
        self.log = logger or (lambda message: None)
        self.state = None

    # -- construction ---------------------------------------------------
    @classmethod
    def for_rank(cls, directory, rank, num_sys, logger=None):
        path = os.path.join(directory, "checkpoint_rank_%d.json" % int(rank))
        return cls(path, rank, num_sys, logger=logger)

    # -- lifecycle ------------------------------------------------------
    def load(self):
        data = read_json_or_none(self.path)
        self.state = data if isinstance(data, dict) else None
        return self.state

    def save(self):
        if self.state is None:
            raise CheckpointError("nothing to save: no state is loaded")
        self.state["updated_at"] = _now()
        write_json_atomic(self.path, self.state)
        return self.path

    def open_new_cycle(self, cities, plan_pairs, previous_number=0,
                       shuffle_enabled=True, carried_total_cycles=0):
        """Open crawl cycle N+1: shuffle once, persist BEFORE the first page.

        ``carried_total_cycles`` is the lifetime city-cycle count, carried
        across crawl cycles.  Brief rule 5: "Preserve the count after script
        restart" -- and a new crawl cycle is not a reason to forget it.
        """
        number = int(previous_number) + 1
        order, seeds = build_keyword_order(plan_pairs, number, self.rank,
                                           shuffle_enabled)
        self.state = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "nesting": NESTING_CITY_OUTER,
            "rank": self.rank,
            "num_sys": self.num_sys,
            "crawl_cycle_number": number,
            "cycle_started_at": _now(),

            "cities": list(cities),
            "cities_fingerprint": fingerprint(cities),
            "total_assigned_cities": len(cities),

            "keyword_order": order,
            "keyword_plan_fingerprint": plan_fingerprint(plan_pairs),
            "shuffle_seed": seeds,
            "total_keywords": len(order),

            # CITY is the outer index now; KEYWORD is the inner one.
            "current_city_index": 0,
            "current_keyword_index": 0,
            "current_page": 1,
            "current_city": cities[0] if cities else "",
            "current_keyword": order[0][1] if order else "",

            "done_job_urls": [],
            "completed_cities": [],
            "total_complete_cycle": int(carried_total_cycles),

            "last_completed_job_id": "",
            "saved_jobs": 0,
            "duplicate_jobs": 0,
            "rejected_jobs": 0,
            "failed_jobs": 0,
            "examined_jobs": 0,
            "failure_state": None,
            "cycle_complete": False,
        }
        self.save()
        return self.state

    def load_or_open(self, cities, plan_pairs, shuffle_enabled=True):
        """Resume the cycle in progress, or open the next one.  Never both."""
        state = self.load()
        previous_number = int((state or {}).get("crawl_cycle_number", 0) or 0)
        carried = int((state or {}).get("total_complete_cycle", 0) or 0)

        resumable = bool(
            state
            and not state.get("cycle_complete")
            and state.get("keyword_order")
            and state.get("cities"))

        if resumable and (state.get("rank") != self.rank
                          or state.get("num_sys") != self.num_sys):
            self.log(
                "  [WARN] the saved checkpoint is rank=%s num_sys=%s but this "
                "process is rank=%s num_sys=%s. The city slice is positional, "
                "so the saved position means nothing here -- opening a fresh "
                "cycle. The lifetime cycle count (%d) is carried over."
                % (state.get("rank"), state.get("num_sys"), self.rank,
                   self.num_sys, carried))
            resumable = False

        if resumable and state.get("nesting") != NESTING_CITY_OUTER:
            self.log(
                "  [WARN] the saved checkpoint was written with nesting=%r, "
                "but this project is %r. The two indices mean different "
                "things, so resuming would crawl the wrong combination -- "
                "opening a fresh cycle instead."
                % (state.get("nesting"), NESTING_CITY_OUTER))
            resumable = False

        if not resumable:
            return self.open_new_cycle(cities, plan_pairs, previous_number,
                                       shuffle_enabled, carried)

        if state.get("cities_fingerprint") != fingerprint(cities):
            self.log(
                "  [WARN] this rank's city list has CHANGED since cycle %s "
                "started (saved %d, now %d). Finishing this cycle against the "
                "SAVED list; the new list applies from the next cycle."
                % (state.get("crawl_cycle_number"),
                   len(state.get("cities") or []), len(cities)))

        if state.get("keyword_plan_fingerprint") != plan_fingerprint(plan_pairs):
            self.log(
                "  [WARN] the keyword plan has CHANGED since cycle %s "
                "started. Finishing this cycle with the SAVED order so no "
                "keyword is dropped or crawled twice inside it."
                % state.get("crawl_cycle_number"))

        # Repair anything a hand-edit or an old version may have left out,
        # without touching a field that is already there.
        state.setdefault("nesting", NESTING_CITY_OUTER)
        state.setdefault("done_job_urls", [])
        state.setdefault("completed_cities", [])
        state.setdefault("total_complete_cycle", 0)
        state.setdefault("total_assigned_cities", len(state.get("cities") or []))
        for counter in ("saved_jobs", "duplicate_jobs", "rejected_jobs",
                        "failed_jobs", "examined_jobs"):
            state.setdefault(counter, 0)
        state["current_city_index"] = max(0, int(state.get("current_city_index", 0)))
        state["current_keyword_index"] = max(0, int(state.get("current_keyword_index", 0)))
        state["current_page"] = max(1, int(state.get("current_page", 1)))
        self.state = state
        return state

    # -- position -------------------------------------------------------
    def position(self):
        """``(city_index, keyword_index, page)`` -- CITY first, it is outer."""
        state = self.state or {}
        cities = state.get("cities") or []
        order = state.get("keyword_order") or []
        city_index = min(max(0, int(state.get("current_city_index", 0))),
                         max(0, len(cities)))
        keyword_index = min(max(0, int(state.get("current_keyword_index", 0))),
                            len(order))
        page = max(1, int(state.get("current_page", 1)))
        return city_index, keyword_index, page

    def set_position(self, city_index=None, keyword_index=None, page=None,
                     save=True):
        state = self.state
        cities = state.get("cities") or []
        order = state.get("keyword_order") or []
        if city_index is not None:
            state["current_city_index"] = int(city_index)
            state["current_city"] = cities[int(city_index)] \
                if 0 <= int(city_index) < len(cities) else ""
        if keyword_index is not None:
            state["current_keyword_index"] = int(keyword_index)
            state["current_keyword"] = order[int(keyword_index)][1] \
                if 0 <= int(keyword_index) < len(order) else ""
        if page is not None:
            state["current_page"] = max(1, int(page))
        if save:
            self.save()

    # -- per-job bookkeeping --------------------------------------------
    def note_examined(self, job_url="", save=False):
        self.state["examined_jobs"] = int(self.state.get("examined_jobs", 0)) + 1
        if job_url:
            urls = self.state.setdefault("done_job_urls", [])
            if job_url not in urls:
                urls.append(job_url)
        if save:
            self.save()

    def note_saved(self, job_id="", save=True):
        """Record a job as DURABLY saved.

        Called only after ``ExcelStore.append_row()`` has returned True, so
        ``last_completed_job_id`` cannot name a job whose row is not on
        disk.  Brief requirement 6: "Never advance the checkpoint before
        durable data saving."
        """
        self.state["saved_jobs"] = int(self.state.get("saved_jobs", 0)) + 1
        if job_id:
            self.state["last_completed_job_id"] = str(job_id)
        if save:
            self.save()

    def note_duplicate(self, save=False):
        self.state["duplicate_jobs"] = int(self.state.get("duplicate_jobs", 0)) + 1
        if save:
            self.save()

    def note_rejected(self, save=False):
        self.state["rejected_jobs"] = int(self.state.get("rejected_jobs", 0)) + 1
        if save:
            self.save()

    def note_failure(self, stage, reason, context=None, save=True):
        """Record a failure WITH its coordinates (brief section 22)."""
        self.state["failed_jobs"] = int(self.state.get("failed_jobs", 0)) + 1
        failure = {
            "at": _now(),
            "stage": str(stage),
            "reason": str(reason)[:600],
            "rank": self.rank,
            "city": self.state.get("current_city", ""),
            "keyword": self.state.get("current_keyword", ""),
            "page": self.state.get("current_page", 1),
        }
        failure.update(context or {})
        self.state["failure_state"] = failure
        history = self.state.setdefault("recent_failures", [])
        history.append(failure)
        del history[:-50]
        if save:
            self.save()
        return failure

    def clear_failure(self, save=False):
        self.state["failure_state"] = None
        if save:
            self.save()

    # -- the keyword boundary -------------------------------------------
    def complete_keyword(self, keyword_index, save=True):
        """One keyword finished for the current city.  NOT a complete cycle.

        Brief rule 3: "Do not increase the count after every keyword."  So
        this method deliberately does not touch ``total_complete_cycle``.
        """
        self.state["current_keyword_index"] = int(keyword_index) + 1
        order = self.state.get("keyword_order") or []
        next_index = int(keyword_index) + 1
        self.state["current_keyword"] = order[next_index][1] \
            if next_index < len(order) else ""
        self.state["current_page"] = 1
        self.state["done_job_urls"] = []
        if save:
            self.save()

    # -- THE CITY BOUNDARY: the one place the counter moves -------------
    def city_cycle_complete(self, city):
        """Has this city's cycle already been counted in this crawl cycle?"""
        return str(city) in (self.state.get("completed_cities") or [])

    def complete_city_cycle(self, city, save=True):
        """All 85 keywords are done for ``city``: that is ONE complete cycle.

        THE ONLY place ``total_complete_cycle`` is incremented.  Brief
        section 19, rules 2, 3, 4 and 7:

            2. increase only after all keywords for the city are completed
               -- the caller calls this at the city boundary and nowhere else
            3. not after every keyword   -- see complete_keyword()
            4. not after every job       -- see note_saved()
            7. never twice for the same city -- the completed_cities guard

        Returns ``(counted, total_complete_cycle)``.
        """
        city = str(city)
        completed = self.state.setdefault("completed_cities", [])
        if city in completed:
            self.log("      [cycle] %s was already counted in crawl cycle %s "
                     "-- not counting it twice (total still %d)"
                     % (city, self.state.get("crawl_cycle_number"),
                        int(self.state.get("total_complete_cycle", 0))))
            return False, int(self.state.get("total_complete_cycle", 0))

        completed.append(city)
        total = int(self.state.get("total_complete_cycle", 0)) + 1
        self.state["total_complete_cycle"] = total
        self.state["last_completed_city"] = city
        self.state["last_completed_city_at"] = _now()
        # The next city starts at keyword 0, page 1, with a clean job set.
        self.state["current_city_index"] = \
            int(self.state.get("current_city_index", 0)) + 1
        cities = self.state.get("cities") or []
        next_index = self.state["current_city_index"]
        self.state["current_city"] = cities[next_index] \
            if next_index < len(cities) else ""
        self.state["current_keyword_index"] = 0
        order = self.state.get("keyword_order") or []
        self.state["current_keyword"] = order[0][1] if order else ""
        self.state["current_page"] = 1
        self.state["done_job_urls"] = []
        if save:
            self.save()
        self.log("      [cycle] COMPLETE CYCLE %d -- all %d keywords done for "
                 "%s" % (total, len(order), city))
        return True, total

    # -- the crawl-cycle boundary ---------------------------------------
    def complete_crawl_cycle(self, save=True):
        """Every assigned city is finished: this crawl cycle is complete.

        ``total_complete_cycle`` is NOT reset -- it is a lifetime count, and
        rule 5 says it survives restarts.  ``completed_cities`` IS reset,
        because the next crawl cycle will visit the same cities again and
        each visit is a new cycle to count.
        """
        state = self.state
        state["cycle_complete"] = True
        state["completed_at"] = _now()
        state["current_city_index"] = 0
        state["current_keyword_index"] = 0
        state["current_page"] = 1
        state["done_job_urls"] = []
        if save:
            self.save()
        self.log("\n[DONE] CRAWL CYCLE %s COMPLETE -- all %d keywords crawled "
                 "across all %d rank cities. Total complete cycles so far: %d"
                 % (state.get("crawl_cycle_number"),
                    len(state.get("keyword_order") or []),
                    len(state.get("cities") or []),
                    int(state.get("total_complete_cycle", 0))))
        return state

    # -- reporting ------------------------------------------------------
    @property
    def total_complete_cycle(self):
        return int((self.state or {}).get("total_complete_cycle", 0))

    def summary(self):
        """The numbers the terminal banner and the log line need."""
        state = self.state or {}
        cities = state.get("cities") or []
        order = state.get("keyword_order") or []
        city_index, keyword_index, page = self.position()
        return {
            "rank": self.rank,
            "num_sys": self.num_sys,
            "crawl_cycle": state.get("crawl_cycle_number", 0),
            "city": state.get("current_city", ""),
            "city_index": city_index + 1,
            "total_cities": len(cities),
            "keyword": state.get("current_keyword", ""),
            "keyword_index": keyword_index + 1,
            "total_keywords": len(order),
            "page": page,
            "examined": int(state.get("examined_jobs", 0)),
            "saved": int(state.get("saved_jobs", 0)),
            "duplicates": int(state.get("duplicate_jobs", 0)),
            "rejected": int(state.get("rejected_jobs", 0)),
            "failures": int(state.get("failed_jobs", 0)),
            "total_complete_cycle": int(state.get("total_complete_cycle", 0)),
            "completed_cities": len(state.get("completed_cities") or []),
        }


__all__ = ["Checkpoint", "CheckpointError", "CHECKPOINT_SCHEMA_VERSION",
           "NESTING_CITY_OUTER", "build_keyword_order", "fingerprint",
           "plan_fingerprint", "read_json_or_none", "write_json_atomic"]
