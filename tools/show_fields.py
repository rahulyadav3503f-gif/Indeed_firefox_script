#!/usr/bin/env python3
"""Print all 32 columns resolved from ONE saved source file.

    show_fields.py SAVED.html JOB_KEY [PAGE_URL]

Used by capture_cards.sh straight after Ctrl+S, so every job is fully
resolved from its own file before the run moves on.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_file import indeed_source as src                   # noqa: E402
from source_file.indeed_extractor import DETAIL_COLUMNS        # noqa: E402


def main(path, job_key, page_url=""):
    row, report = src.build_row_from_file(path, apply_url=page_url,
                                          job_key=job_key)
    filled = [c for c in DETAIL_COLUMNS
              if str(row.get(c, "") or "").strip()]
    print("      isolation=%s  jobs_in_document=%d  filled=%d/32"
          % (report.isolation, report.jobs_in_document, len(filled)))
    if report.isolation == "NONE":
        print("      REFUSED: the selected job could not be isolated; this "
              "row may belong to another job and must not be written.")
    for column in DETAIL_COLUMNS:
        value = str(row.get(column, "") or "").strip().replace("\n", " ")
        where = report.provenance.get(column, "")
        if value:
            shown = value if len(value) <= 62 else value[:59] + "..."
            print("      %-22s %s%s"
                  % (column, shown, "   [%s]" % where if where else ""))
        else:
            print("      %-22s (blank -- not stated in the saved page)"
                  % column)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: show_fields.py SAVED.html JOB_KEY [PAGE_URL]")
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
