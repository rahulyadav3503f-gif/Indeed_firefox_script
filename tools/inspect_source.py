#!/usr/bin/env python3
"""Look inside a saved Indeed source file and report what is really in it.

A diagnostic, not part of the collector.  It answers the questions that
decide whether extraction can be trusted:

  * Is the file a Firefox view-source save, and how big is the original?
  * How many DISTINCT jobs does the one document describe?
  * Is the selected job's data in there, and in what shape?
  * Which of the structured sources (JSON-LD, meta, embedded JSON) exist?

    python3 tools/inspect_source.py Temp_Data/rank_1/job_1_0000.html <job_key>
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_file import indeed_source as src          # noqa: E402


def main(path, job_key=""):
    raw = open(path, encoding="utf-8", errors="replace").read()
    wrapped = src.looks_like_view_source(raw)
    html = src.recover_original_html(raw)

    print("file            : %s" % path)
    print("saved bytes     : %d" % len(raw))
    print("view-source save: %s" % wrapped)
    print("original bytes  : %d" % len(html))
    print("<title>         : %s" % (src.document_title(html) or "<none>")[:90])

    keys = sorted(set(re.findall(r"(?:jk|vjk)=([a-f0-9]{16})", html)))
    print("distinct job ids: %d" % len(keys))
    if job_key:
        print("selected job    : %s  (%s in document)"
              % (job_key, "PRESENT" if job_key in keys else "ABSENT"))

    print("\n-- structured sources --")
    posting = src.json_ld_job_posting(html)
    print("  JSON-LD JobPosting : %s" % ("yes" if posting else "no"))
    tags = src.meta_tags(html)
    for name in ("og:title", "description", "og:description"):
        if name in tags:
            print("  meta %-14s : %s" % (name, tags[name][:80]))

    # Indeed embeds its card data as JSON in inline <script> blocks.
    print("\n-- embedded JSON blobs --")
    for label, pattern in (
        ("_initialData", r"window\.?_initialData\s*="),
        ("mosaic-provider-jobcards", r"mosaic-provider-jobcards"),
        ("jobmap", r"jobmap\["),
        ("jobKeysWithTwoPaneEligibility", r"jobKeysWithTwoPane"),
        ("hydration-data", r"hydration"),
    ):
        hits = len(re.findall(pattern, html))
        print("  %-30s %s" % (label, "%d hit(s)" % hits if hits else "-"))

    if job_key:
        print("\n-- context around the selected job id --")
        for match in list(re.finditer(re.escape(job_key), html))[:3]:
            start = max(0, match.start() - 160)
            snippet = html[start:match.end() + 160]
            snippet = re.sub(r"\s+", " ", snippet)
            print("  ...%s..." % snippet)
            print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: inspect_source.py SAVED.html [JOB_KEY]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
