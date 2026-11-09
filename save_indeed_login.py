"""Sign in to Indeed once, so the collector can reuse the session.

    python3 save_indeed_login.py              # rank 1's browser profile
    python3 save_indeed_login.py --rank 2

A Firefox window opens on Indeed's sign-in page -- the SAME browser profile
the collector uses.  **You** sign in by hand: your email, your password,
your OTP, and any verification Indeed asks for.  When you are signed in you
press Enter here, this script checks that a session really exists, closes
Firefox cleanly so the cookies are flushed to disk, and records what it
found.

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It never types, reads or stores a credential.  There is no password field
handling in this file at all.  It does not solve CAPTCHAs or verification
steps for you -- if Indeed asks for one, you answer it in the window.  All
it does is open the right profile, wait for you, and then confirm.

HOW THIS DIFFERS FROM THE ORIGINAL PROJECT'S VERSION
----------------------------------------------------
check_indeed/save_indeed_login.py drives Playwright and writes the session
to ``indeed_auth.json``.  This project may not use Playwright, and it does
not need a session file: it drives a REAL Firefox with its own
``--profile`` directory, and Firefox already stores the session there, in
``cookies.sqlite``.  Signing in once in that profile is the whole mechanism.

So there is no auth file to keep secret, no second copy of the session, and
nothing to pass to the collector -- it opens the same profile and is simply
already signed in.

WHAT THIS BUYS
--------------
Indeed asks for a login when paging deeper into results.  Without a session
the collector can read the first page and then hits a sign-in wall; with
one it can page on.  The signed-in session also makes the Apply destination
visible on more jobs.

CLEAN SHUTDOWN MATTERS
----------------------
Firefox keeps cookies in a write-ahead log and checkpoints it on exit.  The
script therefore asks Firefox to quit and WAITS for the process to go,
rather than killing it: a killed Firefox can leave the newest cookies
unwritten, which is exactly the session you just created.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

#: Indeed's sign-in entry point.  The collector's base url is read from the
#: main script so there is never a second copy of it.
SIGN_IN_URL = "https://secure.indeed.com/auth"
HOME_URL = "https://in.indeed.com/"

#: Cookies Indeed sets for a signed-in account.  Presence of any of these is
#: the evidence this script reports; it does not read their values.
LOGIN_COOKIE_NAMES = ("PPID", "SOCK", "SHOE", "CO", "LOGIN_SESSION",
                      "INDEED_CSRF_TOKEN", "JSESSIONID", "_indeed_session")

#: Where the result is recorded.  Not a credential -- it holds no session,
#: only the fact that one was created, for which profile, and when.
MARKER_NAME = "indeed_login.json"


def profile_dir_for(rank):
    """The browser profile the collector uses for this rank.

    Read from the collector's own configuration so the login lands in the
    directory the collector will actually open.
    """
    try:
        import find_indeed_job as collector
        return collector.build_controller_config(which_rank=rank).profile_dir
    except Exception as error:                       # pragma: no cover
        print("[WARN] could not read the profile path from "
              "find_indeed_job.py (%s) -- falling back to the default."
              % error)
        return os.path.join(BASE_DIR, "config", "firefox_profile",
                            "rank_%d" % rank)


def indeed_cookies(profile_dir):
    """{name: host} for every indeed cookie in the profile, or {}.

    The database is COPIED before reading: Firefox may hold a lock on it,
    and this script must never disturb the browser's own file.
    """
    source = os.path.join(profile_dir, "cookies.sqlite")
    if not os.path.isfile(source):
        return {}

    found = {}
    work_dir = tempfile.mkdtemp(prefix="indeed-cookies-")
    try:
        copy = os.path.join(work_dir, "cookies.sqlite")
        shutil.copy(source, copy)
        # The write-ahead log holds cookies not yet checkpointed into the
        # main file; without it a session created seconds ago is invisible.
        for suffix in ("-wal", "-shm"):
            side = source + suffix
            if os.path.isfile(side):
                shutil.copy(side, copy + suffix)
        connection = sqlite3.connect(copy)
        try:
            rows = connection.execute(
                "SELECT name, host FROM moz_cookies "
                "WHERE host LIKE '%indeed%'").fetchall()
        finally:
            connection.close()
        for name, host in rows:
            found[str(name)] = str(host)
    except (sqlite3.Error, OSError) as error:
        print("[WARN] could not read the cookie database: %s" % error)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return found


def login_evidence(cookies):
    """The login cookies present, in the order they were looked for."""
    return [name for name in LOGIN_COOKIE_NAMES if name in cookies]


#: The files Firefox keeps cookies in.  The -wal holds cookies not yet
#: checkpointed into the main database, so copying only cookies.sqlite can
#: copy a session that is missing its newest half.
COOKIE_FILES = ("cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm")


def rank_count():
    """How many ranks this project is configured for."""
    try:
        import find_indeed_job as collector
        return int(collector.num_sys)
    except Exception:                                # pragma: no cover
        return 5


def sync_login_to_other_ranks(source_profile, source_rank, ranks=None):
    """Copy the signed-in session into every OTHER rank's profile.

    WHY THIS EXISTS.  Each rank runs its own Firefox profile
    (config/firefox_profile/rank_N) so two ranks can run at once without
    fighting over one profile lock -- a second Firefox on the same profile
    does not get a window, it gets a "Close Firefox" dialog.

    The cost of that isolation is that a login in rank 1's profile is
    invisible to rank 2: separate profile, separate cookies.sqlite,
    separate session.  Signing in five times is the obvious answer and the
    wrong one.  Copying the cookie database across gives every rank the
    same session from one sign-in, and keeps the profiles separate.

    A rank whose Firefox is RUNNING is skipped, not overwritten: Firefox
    holds the database open and would write its own copy back over ours on
    exit, so the sync would silently undo itself.

    Returns (copied, skipped) as lists of rank numbers.
    """
    copied, skipped = [], []
    total = rank_count() if ranks is None else max(ranks)
    targets = ranks if ranks is not None else range(1, total + 1)

    for rank in targets:
        if rank == source_rank:
            continue
        target = profile_dir_for(rank)

        if firefox_pids(target):
            print("  rank %d: SKIPPED -- a Firefox is running on it. Close "
                  "it and re-run with --sync-only." % rank)
            skipped.append(rank)
            continue

        try:
            os.makedirs(target, exist_ok=True)
            for name in COOKIE_FILES:
                source_file = os.path.join(source_profile, name)
                target_file = os.path.join(target, name)
                if os.path.isfile(source_file):
                    shutil.copy2(source_file, target_file)
                elif os.path.isfile(target_file):
                    # The source has no -wal, so a stale -wal on the target
                    # would be replayed over the session we just copied.
                    os.remove(target_file)
        except OSError as error:
            print("  rank %d: FAILED -- %s" % (rank, error))
            skipped.append(rank)
            continue

        evidence = login_evidence(indeed_cookies(target))
        if evidence:
            print("  rank %d: session copied (%s)" % (rank, ", ".join(evidence)))
            copied.append(rank)
        else:
            print("  rank %d: copied, but no login cookie is readable there"
                  % rank)
            skipped.append(rank)

    return copied, skipped



def firefox_pids(profile_dir):
    """Firefox processes running on THIS profile, by /proc/PID/exe."""
    pids = []
    try:
        output = subprocess.run(
            ["pgrep", "-f", "--", "--profile %s" % profile_dir],
            capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return pids
    for line in output.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        try:
            target = os.readlink("/proc/%d/exe" % pid)
        except OSError:
            continue
        if "firefox" in target:
            pids.append(pid)
    return pids


def close_firefox(profile_dir, timeout=40):
    """Ask Firefox to quit and WAIT, so cookies are checkpointed to disk."""
    pids = firefox_pids(profile_dir)
    if not pids:
        return True
    print("  closing Firefox (pid %s) so the session is written to disk..."
          % ", ".join(str(pid) for pid in pids))
    for pid in pids:
        try:
            os.kill(pid, 15)                         # SIGTERM: a clean quit
        except OSError:
            pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not firefox_pids(profile_dir):
            print("  Firefox closed cleanly.")
            return True
        time.sleep(1)

    print("  [WARN] Firefox is still running after %ds. Close it yourself "
          "before running the collector, or the newest cookies may not be "
          "on disk yet." % timeout)
    return False


def open_browser(profile_dir, url, rank):
    """Open the collector's own Firefox on ``url``.  True when it worked."""
    script = os.path.join(BASE_DIR, "shell_scripts", "open_firefox.sh")
    temp_dir = os.path.join(BASE_DIR, "Temp_Data", "rank_%d" % rank)
    os.makedirs(temp_dir, exist_ok=True)

    environment = dict(os.environ)
    environment.setdefault("DISPLAY", ":0")
    environment.setdefault(
        "FIREFOX_XAUTH_COPY",
        os.path.join(BASE_DIR, "config", "xauth_xwayland"))

    print("  opening Firefox on %s" % url)
    result = subprocess.run(
        ["bash", script,
         "--profile", profile_dir,
         "--url", url,
         "--download-dir", temp_dir,
         "--expect-host", "indeed"],
        env=environment, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print("\n[STOP] the browser would not open:")
        for line in (result.stderr or "").strip().splitlines()[-6:]:
            print("   %s" % line)
        return False
    return True


def write_marker(profile_dir, evidence, cookie_count):
    """Record that a login was made -- never the session itself."""
    path = os.path.join(BASE_DIR, "config", MARKER_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = {
        "_comment": [
            "Records that an Indeed login was completed in the browser",
            "profile named below. It holds NO credential and NO session:",
            "the session lives in that profile's cookies.sqlite, which is",
            "where Firefox keeps it and where the collector reads it from.",
        ],
        "profile_dir": profile_dir,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "login_cookies_found": evidence,
        "indeed_cookies_total": cookie_count,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Sign in to Indeed once in the collector's own Firefox "
                    "profile. Nothing is typed for you and no credential is "
                    "stored by this script.")
    parser.add_argument("--rank", type=int, default=1,
                        help="which rank's browser profile to sign in "
                             "(default: 1)")
    parser.add_argument("--url", default=SIGN_IN_URL,
                        help="page to open (default: Indeed's sign-in page)")
    parser.add_argument("--no-sync", action="store_true",
                        help="do NOT copy the session to the other ranks")
    parser.add_argument("--sync-only", action="store_true",
                        help="copy this rank's existing session to the other "
                             "ranks without opening a browser")
    args = parser.parse_args(argv)

    profile_dir = profile_dir_for(args.rank)
    print("=" * 70)
    print("INDEED LOGIN  --  rank %d" % args.rank)
    print("=" * 70)
    print("  profile : %s" % profile_dir)

    if args.sync_only:
        evidence = login_evidence(indeed_cookies(profile_dir))
        if not evidence:
            print("\n[STOP] rank %d is not signed in, so there is no session "
                  "to copy." % args.rank)
            print("  Sign in first:  %s save_indeed_login.py --rank %d"
                  % (sys.executable, args.rank))
            return 4
        print("  session found (%s); copying to the other ranks:"
              % ", ".join(evidence))
        copied, skipped = sync_login_to_other_ranks(profile_dir, args.rank)
        print("\n  copied to %d rank(s)%s."
              % (len(copied),
                 ", skipped %s" % skipped if skipped else ""))
        return 0 if copied or not skipped else 4

    before = indeed_cookies(profile_dir)
    already = login_evidence(before)
    if already:
        print("  this profile already carries a login cookie (%s)."
              % ", ".join(already))
        print("  Signing in again is harmless -- carry on, or Ctrl+C to stop.")

    if firefox_pids(profile_dir):
        print("\n[STOP] a Firefox is already running on this profile.")
        print("  Close it first: two instances on one profile give a")
        print("  'Close Firefox' dialog instead of a browser window.")
        return 3

    if not open_browser(profile_dir, args.url, args.rank):
        return 3

    print("\n" + "-" * 70)
    print("  1. Sign in MANUALLY in the Firefox window that just opened:")
    print("     your email, your password, your OTP, and any verification")
    print("     Indeed asks for.")
    print("  2. Wait until the page clearly shows you are signed in.")
    print("  3. Come back here and press Enter.")
    print("")
    print("  Nothing is typed for you. This script stores no credential --")
    print("  only Firefox's own session, in its own profile.")
    print("-" * 70)
    try:
        input("\n  press Enter once you are signed in: ")
    except (EOFError, KeyboardInterrupt):
        print("\n  cancelled; nothing was changed.")
        return 1

    # Firefox must exit before the cookie file is trustworthy.
    close_firefox(profile_dir)

    after = indeed_cookies(profile_dir)
    evidence = login_evidence(after)
    added = sorted(set(after) - set(before))

    print("")
    print("  indeed cookies before : %d" % len(before))
    print("  indeed cookies after  : %d" % len(after))
    if added:
        print("  new cookies           : %s%s"
              % (", ".join(added[:10]), " ..." if len(added) > 10 else ""))

    if evidence:
        path = write_marker(profile_dir, evidence, len(after))
        print("")
        print("  LOGIN SAVED. Session cookies found: %s" % ", ".join(evidence))
        print("  They live in %s/cookies.sqlite" % profile_dir)
        print("  Recorded in %s" % path)
        if not args.no_sync:
            print("")
            print("  Copying this session to the other ranks, so one sign-in")
            print("  serves all of them:")
            sync_login_to_other_ranks(profile_dir, args.rank)

        print("")
        print("  Now run the collector -- it opens this same profile and is")
        print("  already signed in:")
        print("      venv/bin/python find_indeed_job.py")
        return 0

    print("")
    print("  COULD NOT CONFIRM A LOGIN.")
    print("  None of the cookies Indeed sets for a signed-in account (%s)"
          % ", ".join(LOGIN_COOKIE_NAMES[:4]))
    print("  are in the profile, so this script will not claim you are")
    print("  signed in when it cannot tell.")
    print("")
    print("  If you DID sign in, it may be that Indeed names its session")
    print("  cookie something not in that list. The new cookies above are")
    print("  the evidence -- send them over and the list can be corrected.")
    print("  Re-run this script to try again.")
    return 4


if __name__ == "__main__":
    sys.exit(main())
