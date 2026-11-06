#!/usr/bin/env python3
"""Turn the files captured by capture_cards.sh into 32-column rows.

Runs OFFLINE against the saved sources, so extraction can be re-run and
corrected without touching the browser or the live site.

    python3 tools/extract_captured.py [Temp_Data/rank_1/capture_log.tsv]

It prints, per job, the fields that were found and the columns left blank.
It does NOT write Excel and does NOT touch the checkpoint: this is the
verification step, not a collection run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_file import indeed_source as src                  # noqa: E402
from source_file.indeed_extractor import DETAIL_COLUMNS       # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG = os.path.join(BASE, "Temp_Data", "rank_1", "capture_log.tsv")

#: The columns a reader actually wants to see for a job, in reading order.
INTERESTING = ("job_title", "company_name", "location", "city", "state",
               "salary_min", "salary_max", "salary_currency",
               "employment_type", "experience_required", "skills_required",
               "posted_date", "apply_url", "job_description")


def read_log(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            if not line.strip():
                continue
            rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    return rows


def main(log_path=DEFAULT_LOG):
    entries = read_log(log_path)
    if not entries:
        sys.exit("no captured jobs in %s" % log_path)

    print("=" * 78)
    print("EXTRACTION FROM %d CAPTURED SOURCE FILE(S)" % len(entries))
    print("=" * 78)

    rows = []
    for entry in entries:
        path = entry["saved_file"]
        key = entry.get("job_key", "")
        page_url = entry.get("page_url", "")

        print("\n--- card %s  job %s  (%s) ---"
              % (entry.get("index", "?"), key, entry.get("method", "?")))

        if not os.path.isfile(path):
            print("   MISSING FILE: %s" % path)
            continue

        row, report = src.build_row_from_file(
            path, apply_url=page_url, job_key=key,
            input_row={"search_keyword": "", "city": ""})
        rows.append((key, row, report))

        print("   source        : %s bytes saved, %s bytes of original html"
              % (entry.get("bytes", "?"), report.original_bytes))
        print("   isolated      : %s" % getattr(report, "isolation", "n/a"))
        for column in INTERESTING:
            value = str(row.get(column, "") or "").strip()
            shown = (value[:88] + "...") if len(value) > 88 else value
            where = report.provenance.get(column, "")
            print("   %-20s %s%s"
                  % (column, shown if shown else "(blank)",
                     "   [%s]" % where if where and shown else ""))
        print("   blank columns : %d of 32" % len(report.missing))

    # -- cross-job contamination check ------------------------------------
    print("\n" + "=" * 78)
    print("ARE THE %d ROWS ACTUALLY DIFFERENT JOBS?" % len(rows))
    print("=" * 78)
    titles = [str(row.get("job_title", "")).strip() for _k, row, _r in rows]
    companies = [str(row.get("company_name", "")).strip() for _k, row, _r in rows]
    print("  distinct job_title   : %d of %d" % (len(set(titles)), len(titles)))
    print("  distinct company_name: %d of %d" % (len(set(companies)), len(companies)))
    for key, row, _report in rows:
        print("   %s  %-42s %s"
              % (key, str(row.get("job_title", ""))[:42],
                 str(row.get("company_name", ""))[:28]))
    if len(set(titles)) < len(titles):
        print("\n  WARNING: repeated titles mean the saved listing document was")
        print("  parsed as a whole and the SELECTED job was not isolated.")

    print("\n  schema: %d columns, order preserved: %s"
          % (len(DETAIL_COLUMNS),
             all(list(row.keys())[:32] == list(DETAIL_COLUMNS)
                 for _k, row, _r in rows) if rows else "n/a"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG)
