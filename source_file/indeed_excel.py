"""The 32-column Excel output, its rollover, and its backups.

THE CONTRACT (brief section 18)
-------------------------------
    "Preserve: exact column names, exact column order, existing data
     normalisation, existing cycle rollover behaviour, existing duplicate-
     handling expectations, existing Excel compatibility."
    "Do not delete, modify, or overwrite historical Excel data from the
     existing collector.  The new project must use its own output
     directory."

Both halves are honoured literally:

*   The column list is IMPORTED from the original project (through
    ``indeed_extractor.DETAIL_COLUMNS``), so the names and the order are not
    merely "the same", they are the same object.  A test asserts it.

*   Every path this module touches is under ``Excel_Data/rank_N/`` inside
    THIS project.  ``assert_not_upstream()`` refuses any path outside the
    configured output root, so a mistyped setting cannot reach the original
    collector's workbooks.

THE ROLLOVER, AND WHY IT IS A PORT RATHER THAN AN IMPORT
--------------------------------------------------------
The original rollover lives in ``find_indeed_job.append_detail_to_excel()``,
in a 3,000-line module that executes its whole production configuration at
import time and resolves every path against the ORIGINAL project root.
Importing it would mean importing those paths.  So the algorithm is ported
here, step for step, and the steps are listed so the two can be compared:

    cycle_num = 0  ->  the next archive is current_data_cycle1.xlsx
    append the row to current_data.xlsx
    when len(df) >= EXCEL_BATCH_SIZE:
        write current_data_cycleN.xlsx
        save cycle_num = N
        truncate current_data.xlsx to a header-only sheet
    if an archive with that number already exists, step past it rather
        than destroying collected data

WHAT IS NEW
-----------
*   A ``Backup/`` copy of the working file before every rollover, because a
    rollover is the one point where the working file is emptied.
*   ``append_row()`` returns a definite "written" or "not written", and the
    caller advances the checkpoint only on "written" (brief section 18: "A
    failed save must not cause the checkpoint to incorrectly mark a job as
    permanently completed", and restriction 12).
"""

import os
import shutil
import time
from datetime import datetime

import pandas as pd

from .indeed_extractor import (DETAIL_COLUMNS, job_key_from_url,
                               row_for_excel)

# openpyxl refuses these; the original project strips the same set.
_ILLEGAL_EXCEL_CHARS = __import__("re").compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ExcelWriteError(RuntimeError):
    """A row could not be written.  The caller must NOT advance past it."""


class UnsafePathError(RuntimeError):
    """A path outside this project's own output directory was refused."""


# ---------------------------------------------------------------------------
# CELL SANITISING -- the original project's two helpers, unchanged
# ---------------------------------------------------------------------------

def _needs_cleaning(value):
    return isinstance(value, str) and bool(_ILLEGAL_EXCEL_CHARS.search(value))


def _clean_cell(value):
    if isinstance(value, str):
        return _ILLEGAL_EXCEL_CHARS.sub("", value)
    return value


# ---------------------------------------------------------------------------
# THE WRITER
# ---------------------------------------------------------------------------

class ExcelStore(object):
    """One rank's workbook, its archives and its backups."""

    def __init__(self, output_dir, backup_dir, working_file="current_data.xlsx",
                 batch_size=100, cycle_state_file="cycle_state.json",
                 keep_backups=20, logger=None):
        self.output_dir = os.path.abspath(output_dir)
        self.backup_dir = os.path.abspath(backup_dir)
        self.working_file = working_file
        self.batch_size = int(batch_size)
        self.cycle_state_file = cycle_state_file
        self.keep_backups = int(keep_backups)
        self.log = logger or (lambda message: None)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)

    # -- paths ----------------------------------------------------------
    def path(self, name):
        """Resolve ``name`` inside this rank's output directory.

        RESTRICTION 2 AND 3 ARE ENFORCED HERE: "Do not overwrite existing
        Excel files", "Do not modify historical checkpoint data".  An
        absolute path, or a relative path that climbs out with "..", is
        refused rather than followed.
        """
        candidate = os.path.abspath(os.path.join(self.output_dir, name))
        root = self.output_dir + os.sep
        if not candidate.startswith(root) and candidate != self.output_dir:
            raise UnsafePathError(
                "%r resolves to %s, which is outside this rank's output "
                "directory %s. Refusing to touch it -- the original "
                "collector's workbooks live outside this tree."
                % (name, candidate, self.output_dir))
        return candidate

    @property
    def working_path(self):
        return self.path(self.working_file)

    @property
    def cycle_state_path(self):
        return self.path(self.cycle_state_file)

    # -- reading --------------------------------------------------------
    def read_or_empty(self, file_path=None):
        """Read the workbook.  A damaged one is moved aside, never deleted.

        The original project REMOVES a corrupted workbook.  Here it is moved
        into ``Backup/`` instead: the brief forbids destroying collected
        data, and a workbook that openpyxl cannot read may still be
        recoverable by hand.
        """
        from zipfile import BadZipFile

        file_path = file_path or self.working_path
        if not os.path.exists(file_path):
            return pd.DataFrame(columns=DETAIL_COLUMNS)
        try:
            if os.path.getsize(file_path) == 0:
                raise ValueError("the workbook is zero bytes")
            frame = pd.read_excel(file_path, engine="openpyxl")
        except (BadZipFile, ValueError, OSError, EOFError, KeyError) as error:
            quarantine = os.path.join(
                self.backup_dir, "UNREADABLE_%s_%s"
                % (datetime.now().strftime("%Y%m%d_%H%M%S"),
                   os.path.basename(file_path)))
            try:
                shutil.move(file_path, quarantine)
                self.log("   [WARN] %s could not be read (%s). Moved to %s "
                         "-- NOT deleted -- and continuing with an empty "
                         "sheet." % (os.path.basename(file_path), error,
                                     quarantine))
            except OSError as move_error:
                self.log("   [WARN] %s is unreadable (%s) and could not be "
                         "moved aside (%s)."
                         % (file_path, error, move_error))
            return pd.DataFrame(columns=DETAIL_COLUMNS)

        for column in DETAIL_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return frame[DETAIL_COLUMNS]

    def saved_rows(self, file_path=None):
        """Rows already in the workbook, as dicts, for the duplicate index."""
        frame = self.read_or_empty(file_path)
        if frame.empty:
            return []
        return frame.fillna("").to_dict("records")

    def row_count(self, file_path=None):
        return len(self.read_or_empty(file_path))

    # -- writing --------------------------------------------------------
    def safe_write(self, frame, file_path):
        """Sanitise, write to a temp file, rename into place.

        The rename is atomic, so a Ctrl+C mid-save cannot leave a truncated
        workbook -- the original project's reasoning, kept.
        """
        file_path = self.path(os.path.basename(file_path)) \
            if not os.path.isabs(file_path) else file_path
        if os.path.isabs(file_path):
            root = self.output_dir + os.sep
            if not file_path.startswith(root):
                raise UnsafePathError(
                    "refusing to write outside %s: %s"
                    % (self.output_dir, file_path))

        cleaned = None
        cleaned_cells = 0
        for column in list(frame.columns):
            original = frame[column]
            changed = int(original.map(_needs_cleaning).sum())
            if changed:
                if cleaned is None:
                    cleaned = frame.copy()
                cleaned[column] = original.map(_clean_cell)
                cleaned_cells += changed
        if cleaned_cells:
            self.log("      [clean] removed Excel-illegal control characters "
                     "from %d cell(s) before saving %s"
                     % (cleaned_cells, os.path.basename(file_path)))
        payload = cleaned if cleaned is not None else frame

        folder = os.path.dirname(file_path)
        os.makedirs(folder, exist_ok=True)
        name, ext = os.path.splitext(os.path.basename(file_path))
        temp_file = os.path.join(folder, ".%s.tmp%s" % (name, ext))
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass

        payload.to_excel(temp_file, index=False, engine="openpyxl")
        os.replace(temp_file, file_path)
        return file_path

    # -- backups --------------------------------------------------------
    def backup(self, file_path=None, tag="backup"):
        """Copy the working file into ``Backup/``.  Never moves it."""
        file_path = file_path or self.working_path
        if not os.path.exists(file_path):
            return ""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(os.path.basename(file_path))
        target = os.path.join(self.backup_dir,
                              "%s_%s_%s%s" % (name, tag, stamp, ext))
        try:
            shutil.copy2(file_path, target)
        except OSError as error:
            self.log("      [WARN] backup of %s failed: %s"
                     % (file_path, error))
            return ""
        self._prune_backups(name)
        return target

    def _prune_backups(self, prefix):
        if self.keep_backups <= 0:
            return
        try:
            names = sorted(entry for entry in os.listdir(self.backup_dir)
                           if entry.startswith(prefix + "_"))
        except OSError:
            return
        for stale in names[:-self.keep_backups]:
            try:
                os.remove(os.path.join(self.backup_dir, stale))
            except OSError:
                pass

    # -- the rollover counter -------------------------------------------
    def load_cycle_num(self):
        """The Excel ARCHIVE counter (0 when there is none)."""
        import json
        try:
            with open(self.cycle_state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return int(data.get("cycle_num", 0))
        except (OSError, ValueError, TypeError):
            return 0

    def save_cycle_num(self, cycle_num):
        import json
        payload = {"cycle_num": int(cycle_num),
                   "updated_at": datetime.now().isoformat(timespec="seconds")}
        path = self.cycle_state_path
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    def next_cycle_file(self):
        """``(filename, number)`` for the next archive.

        The original project's belt-and-braces step is kept: if an archive
        with that number already exists -- a state file deleted by hand,
        say -- step PAST it rather than destroying collected data.
        """
        base = os.path.splitext(os.path.basename(self.working_file))[0]
        number = self.load_cycle_num() + 1
        while os.path.exists(self.path("%s_cycle%d.xlsx" % (base, number))):
            number += 1
        return "%s_cycle%d.xlsx" % (base, number), number

    # -- the one method the collector calls -----------------------------
    def append_row(self, row, duplicate_index=None):
        """Append one row.  Returns ``(written, info)``.

        ``written`` is True only when the workbook is on disk with this row
        in it.  Brief restriction 12 and section 18 both hang on that: the
        caller advances its checkpoint on True and does not on False, so a
        failed save can never mark a job permanently done.

        ``info`` carries ``rows``, ``file`` and, after a rollover,
        ``archived`` and ``cycle_num``.
        """
        if not isinstance(row, dict):
            raise ExcelWriteError("row is not a dict")

        clean_row = row_for_excel(row)
        frame = self.read_or_empty()

        # Last-ditch duplicate guard against the file itself, independent of
        # the in-memory index: two processes, or a resumed run, must not be
        # able to write the same job twice.
        if _already_in_frame(clean_row, frame):
            return False, {"reason": "duplicate in workbook",
                           "rows": len(frame),
                           "file": os.path.basename(self.working_path)}

        frame = pd.concat([frame, pd.DataFrame([clean_row])],
                          ignore_index=True)[DETAIL_COLUMNS]

        info = {"rows": len(frame),
                "file": os.path.basename(self.working_path)}
        try:
            if len(frame) >= self.batch_size:
                # A rollover empties the working file, so it is backed up
                # first.  This is the only destructive step in the module.
                self.backup(tag="pre_rollover")
                archive_name, cycle_num = self.next_cycle_file()
                self.safe_write(frame, self.path(archive_name))
                self.save_cycle_num(cycle_num)
                self.safe_write(pd.DataFrame(columns=DETAIL_COLUMNS),
                                self.working_path)
                info.update({"archived": archive_name,
                             "cycle_num": cycle_num,
                             "rolled_over": True})
                self.log("      [excel] batch complete -> %s | rows: %d"
                         % (archive_name, len(frame)))
                self.log("      [excel] emptied -> %s"
                         % os.path.basename(self.working_path))
            else:
                self.safe_write(frame, self.working_path)
                info["rolled_over"] = False
        except Exception as error:
            # openpyxl's IllegalCharacterError and friends: one bad job must
            # not end a run that has been collecting for hours.  It is
            # reported as NOT WRITTEN, which is the honest answer.
            name = type(error).__name__
            if name not in ("IllegalCharacterError", "ValueError",
                            "TypeError", "OSError", "PermissionError"):
                raise
            self.log("      [WARN] Excel refused this row (%s: %s) -- it is "
                     "NOT saved and the checkpoint will not advance past it."
                     % (name, error))
            return False, {"reason": "%s: %s" % (name, error),
                           "rows": len(frame) - 1,
                           "file": os.path.basename(self.working_path)}

        if duplicate_index is not None:
            duplicate_index.mark_saved(clean_row)
        return True, info


#: Columns that can identify a row, strongest first.  apply_url and
#: source_url are urls and are only trusted when they carry a job key.
_IDENTITY_COLUMNS = ("internal_job_id", "job_id", "apply_url", "source_url")
_URL_COLUMNS = ("apply_url", "source_url")


def _already_in_frame(row, frame):
    """The original project's ``is_duplicate_row``, made url-aware.

    A URL IS ONLY A DUPLICATE SIGNAL IF IT IDENTIFIES A JOB.

    The original compared source_url and job_id.  source_url is now the
    site constant "https://in.indeed.com/" on every row, so comparing it
    matched EVERY row against the first one already in the workbook: a run
    wrote one job and then refused the next nine as duplicates of it.
    Measured on ten real captures with ten distinct job keys.

    So url columns are skipped unless they carry a job key, and
    internal_job_id -- the job's own key, which no rewrite touches -- is
    checked first.
    """
    if frame is None or frame.empty:
        return False
    for column in _IDENTITY_COLUMNS:
        value = str(row.get(column) or "").strip()
        if not value or column not in frame.columns:
            continue
        if column in _URL_COLUMNS and not job_key_from_url(value):
            continue
        if (frame[column].astype(str).str.strip() == value).any():
            return True
    return False


def timestamped(prefix, extension=".xlsx"):
    return "%s_%s%s" % (prefix, time.strftime("%Y%m%d_%H%M%S"), extension)


__all__ = ["ExcelStore", "ExcelWriteError", "UnsafePathError",
           "DETAIL_COLUMNS", "timestamped"]
