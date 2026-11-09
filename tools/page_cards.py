#!/usr/bin/env python3
"""How many job cards is a saved results page actually showing?

    python3 tools/page_cards.py Temp_Data/rank_1/listing_1_page01.html
    python3 tools/page_cards.py --count FILE     # just the number, for shell

Runs OFFLINE against a saved file. This is the census the collector reads
before it decides how many cards to take from a page -- the same function,
so what this prints is what the run will do.

It distinguishes two numbers that are easy to confuse and are not the same:

    cards on the page   what is rendered, suggestions included
    search matched      what the SEARCH found

A search that matched 0 jobs still renders cards. Measured: "Mdm Engineer"
in Madurai matched nothing and showed five suggestion cards, reshuffled on
every reload.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_file import indeed_source as src                  # noqa: E402


def main(argv):
    count_only = "--count" in argv
    paths = [arg for arg in argv if not arg.startswith("-")]
    if not paths:
        sys.exit(__doc__.strip().splitlines()[0])

    status = 0
    for path in paths:
        try:
            cards = src.page_cards(src.read_saved_source(path))
        except OSError as error:
            if not count_only:
                print("%s: could not be read: %s" % (path, error))
            status = 1
            continue

        if count_only:
            # Nothing but the number, so a shell can use it. An unreadable
            # census prints nothing at all rather than a 0 that would be
            # mistaken for "this page has no jobs".
            if cards.keys:
                print(len(cards.keys))
            continue

        print("%s" % path)
        print("  cards on the page : %d   (evidence: %s)"
              % (len(cards.keys), cards.evidence))
        print("  page's own count  : %s"
              % ("not stated" if cards.declared_count is None
                 else cards.declared_count))
        print("  search matched    : %s"
              % ("not stated" if cards.total_matches is None
                 else cards.total_matches))
        if cards.total_matches == 0 and cards.keys:
            print("  NOTE: this search matched nothing -- the cards above are")
            print("        Indeed's suggestions, not results for the keyword.")
        for position, key in enumerate(cards.keys):
            print("   %2d  %s" % (position, key))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
