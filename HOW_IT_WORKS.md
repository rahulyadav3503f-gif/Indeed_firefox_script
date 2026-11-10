# How the new Indeed Firefox collector works

**Project:** `/home/ubuntu/new_indeed_script/`
**Document date:** 2026-11-06
**Status of this document:** describes the code **as it is now**, including
the parts that are not yet proven working. Section 14 says exactly which is
which. Nothing here is aspirational.

---

## 1. What this program is

It collects Indeed job adverts into a 32-column Excel file by **driving a
real Firefox window** with keyboard and mouse events, exactly as a person
would. There is no HTTP client, no Playwright, no Selenium, no API.

```
Python decides WHAT to do  ->  Bash scripts do it with xdotool/xclip
                           ->  Firefox reacts
                           ->  Python reads the result and writes Excel
```

The division of labour is strict and worth stating, because it is what
keeps the system debuggable:

| Layer | Owns | Never does |
|---|---|---|
| `find_indeed_job.py` | the plan: which keyword, which city, which page, when to rest, when to stop | touches the keyboard |
| `source_file/indeed_controller.py` | calling shell scripts, parsing their `RESULT:` lines, timing the two delays | business rules |
| `shell_scripts/*.sh` | clicks, keystrokes, window checks | knows any job keyword or city |
| `source_file/indeed_source.py` | saved HTML → fields | invents a value |
| `source_file/indeed_excel.py` | the workbook, rollover, backups | changes the schema |

A shell script receives a keyword as an **argument**. There is no role list
or city list anywhere in `shell_scripts/`.

---

## 2. The machine this runs on, and why it matters

Four facts were measured on this laptop, and each one breaks everything if
ignored. They are written at the top of `shell_scripts/_common.sh`.

**FACT 1 — the desktop is Wayland, `xdotool` only speaks X11.**
`XDG_SESSION_TYPE=wayland`. A Wayland surface is not an X11 window, so
xdotool cannot see or type into it. Firefox is therefore started with
`MOZ_ENABLE_WAYLAND=0` and `GDK_BACKEND=x11`, which makes its window a real
X11 window under XWayland.

**FACT 2 — Firefox here is a snap.**
Two consequences:
- The snap has a **private `/tmp`**. A page saved to `/tmp` by Ctrl+S lands
  inside the snap's own tmp and Python can never see it. Everything saved
  goes under `$HOME` (`Temp_Data/`), which `require_saveable_path()`
  enforces.
- Starting it through the `/usr/bin/firefox` wrapper with X11 forced exits
  with `cannot open display`. It must be started as the snap's inner binary
  inside `snap run --shell firefox`, with `XAUTHORITY` pointing at a copy
  of the mutter cookie the snap can read (`config/xauth_xwayland`).

**FACT 3 — a second Firefox needs `--new-instance` and its own `--profile`.**
A bare `firefox URL` opens a tab in *your* browser and exits. Worse, a
second instance on the **same** profile does not give a browser window at
all: it shows a "Close Firefox" dialog, which the window search would
otherwise latch onto. `open_firefox.sh` now names that dialog explicitly.

**FACT 4 — keystrokes can land in the wrong window.**
On Wayland the compositor decides who receives keyboard input; xdotool
cannot target a window. Measured: a read aimed at our Firefox returned
`jsw jetour t2 spy shots` — content from the operator's own browser. This is
why the **input guard** (section 6) exists.

---

## 3. Where the keywords and cities come from

```
vendor/target_audience_roles.py   ->  build_role_plan()  ->  1,264 keywords
vendor/new_mylib.py               ->  city_by_states     ->    110 cities
```

Both files are **copied into `vendor/`** with their md5 recorded in
`vendor/PROVENANCE.json`, and `tests/test_role_plan.py` re-checks those
hashes. The root-level `target_audience_roles.py` and `new_mylib.py` are
thin shims that re-export the vendored files — they declare no data of
their own.

The plan is **1,264 keywords**, not the old 85:

| Track | Count | What it is |
|---|---:|---|
| A — target audience | 200 | 15 priority IT profiles expanded into real search synonyms, the rest of the target audience, and 40 trending IT roles |
| B — freshers | 1,064 | fresher-plausible titles across 116 departments (Nursing, Accounts, Retail, …) |

`is_non_it_title()` keeps its name and contract (True = drop) but is now a
**two-track whitelist**: `is_non_it_title("Staff Nurse")` is `False` (keep),
and `role_department("Staff Nurse")` returns `"Nursing"`.

The 32-column row builder is still **imported read-only** from
`/home/ubuntu/check_indeed/` so the Excel contract cannot drift. The startup
banner states both facts separately:

```
roles+cities : vendor/ (local, authoritative) -- md5 …
row builder  : /home/ubuntu/check_indeed (read-only, 32-column schema)
```

---

## 4. Rank and city distribution

Five ranks share the 110 cities positionally:

```
one_unit = int(110 / 5) + 1  = 23
cities[23 * (rank - 1) : 23 * rank]
```

Rank 1 gets 23 cities (Delhi … Coimbatore), ranks 1–4 get 23 each and rank 5
gets 18. This is the **original project's algorithm, preserved exactly** —
it does not produce an even 22/22/22/22/22, and changing it would reassign
cities between ranks and invalidate every existing checkpoint.

---

## 5. The loop shape

```
rank 1
 └── city 1 of 23  (Delhi)
      └── keyword 1 of 1264   (page 1 … 4)
      │    └── card 0 … 14
      ├── keyword 2 of 1264
      └── … all 1264 keywords
 └── city 2 of 23  → … → city 23
 └── TOTAL COMPLETE CYCLE += 1
```

City is the **outer** loop, keyword the inner. A city is only marked
complete when every keyword has been attempted for it — and **never** when
the run stopped because of an access refusal.

**A fresh browser for every keyword.** A keyword+city is finished when
every card of every page it has is done. Then, before the next keyword:

```
   last card processed
        |
   close the browser        SIGTERM, and WAIT for the process to exit
        |
   wait 5 seconds           BROWSER_RESTART_WAIT_SECONDS
        |
   open the browser         on https://in.indeed.com, the signed-in profile
        |
   verify the search fields verify_search_fields.sh -- probe, read back, clear
        |
   next keyword, same city
```

and when the **last** keyword of a city is done — one **complete cycle** —
the same mechanism rests for **ten minutes** before the next keyword+city:

```python
BROWSER_RESTART_WAIT_SECONDS = 5.0      # between keywords
COMPLETE_CYCLE_REST_SECONDS  = 600.0    # after a complete cycle
```

One mechanism, two numbers, passed as an argument — so the two waits
cannot drift apart.

Three reasons the browser is restarted rather than simply searched again:

- One window used for hundreds of searches **accumulates state** — the
  detail pane, the suggestion dropdown, scroll position, the modals Indeed
  starts showing after a while. Each of those has broken a run at least
  once. A new window has none of it.
- The card coordinates are measured against a **fresh home page layout**.
- Firefox **checkpoints its cookies on a clean exit**, so the login is
  re-flushed and re-checked on every restart. The log says so only when the
  session's state *changes*, not once per keyword.

Two details that are not cosmetic:

- **The close waits for the process to actually exit.** A signalled-but-
  alive Firefox breaks the next launch: a second Firefox on the same
  profile gets a "Close Firefox" dialog rather than a window (FACT 3). And
  the signal is **SIGTERM, never SIGKILL** — a killed Firefox can lose the
  cookies it had not yet checkpointed, which is exactly the login.
- **The rest is taken with the browser closed.** Ten minutes of an idle
  logged-in window on a shared desktop is ten minutes of something that can
  go wrong, and the restart opens a fresh one anyway.

**Why the fields are verified, and why verifying means *finding*.** The
very next thing the run does is click at a coordinate and type a real
keyword. If that click misses the input, the keyword goes nowhere and
`Return` submits whatever the page had before — the failure that once sent
a run to *youtube.com*.

A fixed coordinate cannot carry that weight. Measured 2026-11-10, **three
things moved it independently**:

| What moved | Measured |
|---|---|
| the window manager | placed the window at `+70+27` when asked for `+0+34`, and `getwindowgeometry` reports the **frame**, so page content starts a title-bar lower than the arithmetic assumes |
| being **signed in** | `in.indeed.com/` is a different page — "Welcome, rohan", a *Jobs for you* feed, an open job pane — not the signed-out hero layout the coordinates were measured on |
| the page itself | the hero area keeps laying out after the page reports loaded |

The result was a click ~30 px high, into the header strip above the box.

So `verify_search_fields.sh` does what `select_job_card.sh` already does for
job cards: **it probes and it learns.** The given coordinates are tried
first, then nearby rows, **nearest first** — so a small offset costs two or
three probes and a large one still succeeds:

```
y = 233  213  253  193  273  173  293  153  313  …     (±20 px, reach 120)
```

It reports `learned_what_xy` / `learned_where_xy`, and the controller aims
the real search there. Two details that matter:

- **The learned position is stored as an offset from the window's corner**,
  not as a screen coordinate — because the browser is closed and reopened
  between every keyword and the window does not come back in the same
  place. It is written to `Temp_Data/rank_N/search_fields.json`, so a fresh
  process starts from a position already proven.
- **No probe is ever sent into Firefox's own chrome** (`MIN_PAGE_Y_OFFSET`).
  A probe that lands in the **address bar** types the probe, reads the probe
  back, and looks exactly like success — and the run would then type
  "Product Consultant" into the address bar and press Return. The floor is a
  safety property, not a tuning knob.

It never presses Return, and every box it touches is cleared. Three restarts
failing in a row stops the run (`MAX_CONSECUTIVE_RESTART_FAILURES`) rather
than typing into pages nothing can vouch for.

**The first browser of the run is verified too.** It was not, and that is
the gap the 2026-11-10 run fell through: every restart *between* keywords
verified the fields, but keyword 1 clicked at a coordinate nothing had
checked. To find the boxes without starting a collection run:

```bash
python3 find_indeed_job.py --verify-fields --rank 3
```

### A read-back is a field value, or it is the whole page

When the click misses, focus stays on the **document** — and there `Ctrl+A`
means *select the entire page*, so `Ctrl+C` copies it. The read-back came
back as four kilobytes of Indeed:

```
[search_jobs] ERROR(7): the keyword box holds ' non user content
    Start of main content
    Keyword : all jobs
    Edit location input box label
    Welcome, rohan
    … 120 more lines of job titles and salaries …
', not 'Product Consultant'.
```

The refusal was right; the reporting was not. It printed the page twice per
retry, buried the real fault, and read as though the box held that text.
Worse, it went through `emit` — and a `RESULT:` line is **line-based**, so a
page copy sprays 120 lines through the protocol.

`is_field_value()` in `_common.sh` separates the two cases **exactly, not
heuristically**: the value of a one-line search input *cannot contain a
newline*, and a page copy always does. `field_preview()` keeps either case
to one short line and says which it is:

```
73 characters of PAGE TEXT across 4 lines, starting ' non user content'
```

**The fixed plan.** How much of a search to take is two numbers in
`find_indeed_job.py`:

```python
FIXED_LISTING_PAGES  = 5     # results pages per keyword+city
FIXED_CARDS_PER_PAGE = 10    # job cards taken from each page
```

so one keyword+city yields at most 50 jobs. `TARGET_UNIQUE_JOBS` is
*derived* from them (`5 x 10`) so a second budget can never silently cap
the plan.

**`FIXED_CARDS_PER_PAGE` is a ceiling, not a promise.** Before a single
card is clicked, the results page's own source is saved and the card list
read out of it — `page_cards()` in `indeed_source.py`, called through
`read_page_census()`:

```
mosaic-provider-jobcards  ->  {"results": [{"jobkey": …}, …]}   the cards
"jobCount": 5                                                   corroborates
"totalJobCount": 0  /  <title>0 Mdm Engineer Jobs …</title>     the SEARCH
```

The card budget for the page is then `min(cards found, 10)`. A page with
five cards is five iterations, not ten of which five fail.

> **This replaced real waste.** "Mdm Engineer" in Madurai put **five**
> cards on the page. The collector, told to take ten, clicked empty space
> five times and reported "no more cards" each time.

**Three signals, and they are not the same number.** The same measurement
showed why this needs care:

| Signal | Value | What it means |
|---|---:|---|
| `len(results)` | 5 | cards rendered on the page |
| `"jobCount"` | 5 | Indeed's count of the same thing |
| `"totalJobCount"`, and the `<title>` | **0** | **what the search matched** |

The search matched *nothing*. The five cards were Indeed's **suggestions**,
filling an empty page — and they **reshuffled on every reload**: five saved
reloads of that one page drew from a pool of nine, with 0–40% of the cards
new each time.

They are still real jobs, so they are still collected. What stops is the
paging: a search with 0 matches has no page 2.

**When to stop paging.** Two signals, in this order:

1. **The match count.** `start + cards_on_page >= matches` ⇒ this is the
   last page. Arithmetic, not inference. Where the two count signals
   disagree the **larger** wins — over-stating costs one wasted page turn,
   under-stating throws real results away.
2. **The card list**, as a backstop for when no count is available. If
   half or fewer of this page's cards are new (`PAGE_REPEAT_NEW_CARD_FRACTION`),
   `start=` served a page already collected: the search has one page, and
   the next move is the next keyword.

> **Exact card-list equality was the obvious test and it does not work.**
> The cards rotate between loads, so two loads of one page are never
> byte-identical — measured 0–40% new. A real page 2 shares *nothing*.
> 0.5 sits in the middle of that gap rather than at the edge of a narrow
> one.

A census that cannot be read falls back to the fixed ten and disables the
repeat check. **"Unknown" is never read as "the results ended."**

**Turning the page.** Page 1 is the typed search. Page 2 onwards is page
1's own url, edited:

```
page 1   …/jobs?q=desktop+support+engineer&l=Chennai%2C+Tamil+Nadu
         &radius=25&from=searchOnDesktopSerp…&vjk=5a6f2e4d08b08903
                                              ^^^^^^^^^^^^^^^^^^^^ dropped
page 2   …/jobs?q=desktop+support+engineer&l=Chennai%2C+Tamil+Nadu
         &radius=25&from=searchOnDesktopSerp…&start=10
                                              ^^^^^^^^ added (20, 30, 40 …)
```

Two reasons it is derived rather than rebuilt from the keyword and city:
`radius=25` and the other parameters the form added *are* the search, and
dropping them gives a different result set; and `vjk=` names the job open
in the detail pane, which is not on page 2.

> **This replaced a bug.** Paging used to re-run the form search with
> `--start`, which `form` mode ignores — only `url` mode read it. So every
> "next page" ran the same search and came back with page 1.
> `goto_listing_page.sh` now verifies the `start=` it landed on, because
> silently getting page 1 again would collect it twice under page 2's name.


---

## 6. Step by step: one job, from browser to Excel

### Step 0 — startup
1. Load the role plan and city list, compute this rank's cities.
2. Load `config/checkpoints/checkpoint_rank_1.json`; resume at the stored
   city / keyword / page.
3. Verify the plan fingerprints still match the checkpoint.
4. Print the banner (browser name, counts, delays, paths).
5. Live collection requires `INDEED_LIVE_APPROVED=yes` in the environment.
   Without it the script refuses to touch the live site.

### Step 0b — signing in (once)  (`save_indeed_login.py`)

Indeed asks for a login when paging deeper into results, so a signed-out
run reads the first page or two and then stops finding new jobs.

```bash
venv/bin/python save_indeed_login.py          # rank 1's profile
venv/bin/python save_indeed_login.py --rank 2
```

It opens **the collector's own Firefox profile** on Indeed's sign-in page,
you sign in by hand, and you press Enter. It then closes Firefox cleanly
and checks the profile for Indeed's session cookies.

Unlike `check_indeed/save_indeed_login.py`, there is **no `auth.json`**.
That version drives Playwright and exports a `storage_state`; this project
drives a real Firefox with its own `--profile`, and Firefox already keeps
the session there in `cookies.sqlite`. Signing in once in that profile *is*
the mechanism — nothing is passed to the collector, which opens the same
profile and is simply already signed in.

Three details that matter:

- **It never types or stores a credential.** No password handling, no
  `getpass`. You sign in; it only confirms afterwards.
- **Firefox is asked to quit, not killed.** Cookies live in a write-ahead
  log that is checkpointed on exit, so a killed browser can lose exactly
  the session you just created.
- **It will not claim success it cannot prove.** If none of Indeed's known
  session cookies appear, it says so and lists the new cookies as evidence
  rather than reporting a login that may not exist.

**One login, every rank.** Each rank runs its own Firefox profile
(`config/firefox_profile/rank_N`) so two ranks can run at once without
fighting over a profile lock — a second Firefox on one profile gets a
"Close Firefox" dialog, not a window. The cost is that a login in rank 1's
profile is *invisible* to rank 2: separate profile, separate
`cookies.sqlite`, separate session. Symptom: change the rank, run again,
and the listing pages come back logged out.

Signing in five times is the obvious answer and the wrong one. After a
successful login the session is **copied into every other rank's profile**,
and it can be done on its own at any time:

```bash
venv/bin/python save_indeed_login.py --sync-only --rank 1
```
```
session found (PPID, SOCK, SHOE); copying to the other ranks:
  rank 2: session copied (PPID, SOCK, SHOE)
  rank 3: session copied (PPID, SOCK, SHOE)
  rank 4: session copied (PPID, SOCK, SHOE)
  rank 5: session copied (PPID, SOCK, SHOE)
```

Two details that make it correct rather than merely convenient:

- **A rank whose Firefox is running is skipped, never overwritten.** It
  holds the database open and would write its own copy back over ours on
  exit — the sync would silently undo itself.
- **`cookies.sqlite-wal` is copied too**, and a stale one on the target is
  removed. The write-ahead log holds cookies not yet checkpointed, so
  copying only `cookies.sqlite` can copy a session missing its newest half,
  and replaying a stale `-wal` would undo the one just written.

The collector checks at startup and **warns without blocking** — the first
page really does read signed out:

```
[WARN] NOT SIGNED IN to Indeed (no Indeed session cookie in …/rank_1).
       Indeed asks for a login when paging deeper into results, so this
       run will collect the first page or two and then stop finding jobs.
```

### Step 1 — open Firefox  (`open_firefox.sh`)
1. Record Firefox windows that already exist — they are **never** touched.
2. Write `user.js` into `config/firefox_profile/rank_N/`:
   no first-run pages, no update checks, downloads to `Temp_Data/rank_N`,
   and `browser.download.save_converter_index=1` ("HTML only") so Ctrl+S
   does not also write a `*_files/` sidecar directory.
3. Launch inside `snap run --shell firefox` with the X11 environment and a
   readable `XAUTHORITY`; record the pid.
4. Confirm the pid is really Firefox via `/proc/PID/exe` — **not** a
   command-line substring, which would also match this script.
5. Find the window owned by that pid (never "the newest window").
6. Refuse the window if it existed before we started, or if it is the
   "Close Firefox" profile-lock dialog.
7. **Normal window mode** — fullscreen is deliberately *not* used:
   - leave fullscreen if the profile reopened in it,
   - size/position to `WINDOW_SIZE = (1845, 1046)`, `WINDOW_POS = (0, 34)`,
     retrying up to 5 times because the first request is often ignored while
     the window is still mapping,
   - `require_window_ready()` then checks it is focused and at least
     900×600, because a smaller window makes every coordinate meaningless.
8. Read the address bar and confirm it contains `indeed`.
9. Check the **window title** for a refusal ("Just a moment…", "Access
   denied"). No page copy is involved.
10. Write `Temp_Data/rank_N/browser_window.json` with pid, window id and
    geometry.

### Step 2 — the search  (`search_jobs.sh`, mode `form`)
1. **Input guard** (see below) proves keystrokes reach our window.
2. Dismiss the address-bar suggestion panel.
3. **Wait `SEARCH_FIELD_DELAY_SECONDS = 7`.** Indeed keeps laying out after
   it reports loaded and the boxes move while it does.
4. Click Indeed's "what" box, `Ctrl+A`, type the keyword, `Escape`.
5. **Read the box back** with a field-level `Ctrl+A`/`Ctrl+C`.
6. Same for the "where" box and the city.
7. **Refuse to submit** unless both boxes read back exactly what was asked
   for. An empty read-back means the keystrokes never arrived, and pressing
   Return then would deliver it to whatever has focus.
8. Re-prove focus, then press Return.
9. **No post-search verification.** The script waits
   `SEARCH_RESULTS_WAIT_SECONDS = 10` and goes straight to the first job
   card. It no longer requires the url to contain `q=<keyword>` and
   `l=<city>`, and no longer waits for `vjk=` before declaring the search
   done — both used to block searches that had in fact loaded. What
   remains is: an **access refusal** still stops the run, a browser error
   page is reported as a warning, and the url is read once to pass the
   pre-selected job key on as a *hint*.

   Job identity is still guaranteed, further down: `select_job_card.sh`
   reads the key from the url, `save_page_source.sh --expect-url` refuses
   to save a page that no longer carries it, and `indeed_source.py`
   isolates that key out of the saved document.

`url` mode (building `…/jobs?q=…&l=…` in the address bar) still exists as a
fallback and is used automatically for `file://` fixture runs, which have no
search form.

### Step 3 — select a job card  (`select_job_card.sh`)
The card index is **0-based**.

- **Card 0 is usually already selected.** Indeed pre-selects the first job
  and puts its key in `vjk=`. The script takes it **without clicking** and
  reports `selection_method=preselected`.
- **Later cards are found by probing, not by arithmetic.** There is no
  `CARD_PITCH` any more: on a measured page the card tops were 410, 645 and
  835 — pitches of 259 and 191 — and the selected card is taller still
  because it expands. The script clicks at `CARD_X`, starting at `--start-y`,
  stepping down `CARD_PROBE_STEP = 55` px up to `CARD_PROBE_LIMIT = 12`
  times **per scroll round**, until `vjk=` changes to a key not already
  handled. The budget is per round on purpose: when it counted the whole
  search, the first screenful consumed it and only one scroll ever
  happened, so the page was declared exhausted with most of its cards
  still below the fold.
- It reports `learned_card_y`, and Python starts the next card's probe just
  below it (`MIN_CARD_GAP = 60`), so the spacing is **learned per page**.
- `--seen-keys` stops a probe re-collecting a job already taken.
- **When the probe window reaches the bottom, the list is SCROLLED** and
  probing restarts at the top of the card area (`AFTER_SCROLL_Y`), up to
  `CARD_SCROLL_ROUNDS = 6` times. Without this the run collected only the
  three or four cards that fit on screen, reported "no more cards" and
  moved on to the next search. Scrolling uses the wheel with the pointer
  parked in the results column, so it moves the job list rather than the
  page or an open suggestion panel.
- A scroll is reported back as `scrolled=yes`, and the caller resets its
  probe start to the top: a y learned *before* a scroll describes a view
  that no longer exists.
- If a click navigates away (some cards contain "View similar jobs" links),
  it presses **Back** and carries on probing — and if Back does not return
  to the listing, it stops rather than clicking blind.
- Nothing new below the limit ⇒ `no_more_cards=yes`, which the caller reads
  as the normal end of the page.

> **The address-bar dropdown is a trap, and it caused three failed runs.**
> `Ctrl+L` does not merely focus the address bar — it opens a **suggestion
> panel covering the top ~500px of the page**. Any click aimed at the page
> while it is open lands on a suggestion row, and Firefox navigates there.
> Observed landings: `youtube.com` and `wikipedia.org`.
>
> It bites wherever a read is followed by a click:
> - the search step reads the url, then clicks the keyword box;
> - the card-probe loop reads the url after each probe to see whether the
>   selection changed, then clicks the next candidate position.
>
> So `dismiss_url_dropdown()` (a single `Escape`) is called before **every**
> click into the page. Escape also means *stop loading*, so it is never
> called inside a wait loop — only immediately before a click, when nothing
> is in flight.

### Step 4 — Ctrl+U  (`save_page_source.sh`)
1. Read the address bar — this is the job identity, and `--expect-url`
   makes a mismatch a hard failure.
2. Put focus in the **page**, deterministically: `Ctrl+L` (always lands in
   the address bar) then `F6` (address bar → page). **F6 toggles**, so doing
   it from an unknown state is what previously landed focus in the address
   bar, where Ctrl+U means "delete to start of line" and merely wiped the
   URL.
3. Press `Ctrl+U`.
4. Wait for the address bar to read exactly `view-source:<the page url>` —
   not merely "something starting with view-source:", because a new source
   tab reports `view-source:about:blank` for a moment first.

### Step 5 — Ctrl+S
1. Press `Ctrl+S`.
2. Find the GTK "Save As" dialog **by name across the display** — it belongs
   to the desktop portal, not to the Firefox pid.
3. Type the absolute `Temp_Data/rank_N/job_<rank>_<NNNN>.html` path, Return.
4. Wait for a file to appear, then wait for its size to stop changing.
5. Firefox appends its own extension (`job.html` → `job.html.html`), so the
   file is located by **glob** and renamed to the promised path.
6. Remove any `*_files/` sidecar directory.
7. Refuse anything smaller than `MIN_SOURCE_BYTES = 500`.

> **What Ctrl+S actually writes.** Not the page's HTML — Firefox's
> *rendered* view-source document: syntax-highlighted, every original tag
> escaped, every line wrapped in `<span id="lineN">`. A 1,440-byte fixture
> came back as 7,715 bytes. The original is recovered **byte-for-byte**
> (verified) by taking the text of `<body id="viewsource">` and unescaping
> it.

### Step 6 — extraction  (`source_file/indeed_source.py`)
1. Read the saved file; unwrap the view-source scaffolding.
2. **Isolate the selected job.** A capture of a real results page was
   972,771 bytes and described **16 distinct jobs**. Parsing it whole would
   blend sixteen jobs into one row. So when more than one job is present,
   the embedded job-card JSON for the selected `vjk=` key is located and
   used. `report.isolation` records `job-card`, `single-job` or **`NONE`** —
   and `NONE` means the row must not be trusted.
3. Read fields, best source first:
   1. **JSON-LD `JobPosting`** — schema.org spellings (`datePosted`,
      `validThrough`, `employmentType`) are passed straight through, because
      the original row builder already reads them.
   2. **`<meta>` tags** — `og:title`, `og:description`.
   3. **Visible text** — converted to the shape the existing clipboard
      parser expects, so `parse_job_text()` is reused rather than a second
      field-reader being written that could disagree with the first.
   Earlier sources win; every field records its provenance.
4. Hand the fields to the original `extract_job_details()`, which produces
   the 32 columns in their exact order.

**The blank rule.** A field is written into the raw dict **only when a real
value was found**. Absence stays absence, and the builder's final line —
`{column: row.get(column, "") for column in DETAIL_COLUMNS}` — turns it into
an empty cell in the correct column with nothing shifted. No `"N/A"`,
`"Unknown"`, `"Not Found"` or `"None"` is ever written; a test asserts this
across all 32 columns.

Note which columns are *not* covered by that rule: `country`,
`source_platform`, `source_type`, `score`, `is_active`, `is_fake`,
`fetched_at` and `job_id` are filled by the existing approved builder from
constants and provenance, not from the advert.

### Step 6b — the two URL columns

```
card url    https://in.indeed.com/jobs?q=full+stack+developer&l=Delhi&...&vjk=cba10d8415b155ab
                                                                          ^^^^
apply_url   https://in.indeed.com/viewjob?jk=cba10d8415b155ab
                                          ^^^
source_url  https://in.indeed.com/          (the same on every row)
```

`apply_url` is Indeed's own permalink for the job, built from the selected
card's `vjk=` key — drop the leading `v` and it is the `jk=` the permalink
wants. It is **not** the results-page url the card was selected on: that
carries the search terms and tracking parameters and is the same page for
sixteen different jobs. With no job key in the card url, nothing is
invented and the column stays blank.

> **This change had a trap in it.** Both duplicate checks compared
> `source_url`. Once it became a constant, every job after the first
> collided with it: `identity_keys()` produced `url:https://in.indeed.com/`
> for everything, and `_already_in_frame()` matched the `source_url`
> column. Measured on ten real captures with ten distinct keys — one row
> written, nine refused as duplicates of it.
>
> Both now treat **a url as an identity only when it carries a job key**,
> and prefer `internal_job_id` (the job's own key) first. After the fix the
> same ten captures wrote 9 rows with 0 false duplicates.

### Step 7 — validate and de-duplicate  (`indeed_validator.py`)
In this order, deliberately:
1. `validate_row()` — no title or no stable URL ⇒ **INVALID**.
2. **identity** — no job key, no `source_url`, no `job_id` ⇒
   **UNIDENTIFIED**. A row that cannot be recognised again cannot be
   de-duplicated, so it is refused rather than written on every pass.
3. `is_non_it_title()` — the two-track filter ⇒ **NON_IT**.
4. **duplicate** — already saved ⇒ **DUPLICATE**. Checked last so a
   duplicate non-IT row is reported as non-IT, the more useful fact.

### Step 8 — write Excel  (`indeed_excel.py`)

> **The venv trap.** `pandas` imports without `openpyxl`, but `to_excel`
> needs it at write time. A project venv with
> `include-system-site-packages = false` had pandas and not openpyxl, so
> every job extracted perfectly and then logged
> `Excel Save: FAILED (ModuleNotFoundError: No module named 'openpyxl')`,
> with `saved_jobs` stuck at 0 while the run looked healthy.
> `check_excel_dependencies()` now refuses to start, naming
> `sys.executable` and the exact `pip install` to run — because the whole
> point is that the packages you have are not the packages the running
> interpreter can see.
>
> Run the collector with the SAME interpreter the deps are installed in:
> `venv/bin/python find_indeed_job.py`

1. Append to `Excel_Data/rank_N/current_data.xlsx`.
2. A **second** duplicate check against the workbook itself, independent of
   the in-memory index, so two processes or a resumed run cannot double-write.
3. Atomic write (temp file in the same directory, then rename).
4. At `EXCEL_BATCH_SIZE = 100` rows: back up, archive to
   `current_data_cycleN.xlsx`, and empty the working file. The backup is
   taken first because rollover is the only destructive step in the module.
5. `EXCEL_KEEP_BACKUPS = 20` backups are retained in `Backup/rank_N/`.
6. `append_row()` returns `written=True` **only** when the workbook is on
   disk with the row in it. The checkpoint advances on `True` and never
   otherwise, so a failed save cannot mark a job permanently done.

### Step 9 — the two delays, in this order
```
job written to Excel
      ↓  sleep PRE_CLOSE_DELAY_SECONDS   = 10       ← first delay
close the source tab  (close_source_tab.sh)
      ↓  sleep POST_CLOSE_DELAY_SECONDS  = 10       ← second delay
select the next job card
```
`close_source_tab.sh` identifies the tab **before** closing it — a blind
Ctrl+W would close the listing if the source tab had already gone — and
confirms the listing is back afterwards. `tests/test_delays.py` asserts the
**sequence**, not just that two sleeps happened.

---

## 7. The input guard

Because of FACT 4, every script obeys one rule:

- **Read-only keys** (`Ctrl+L`, `Ctrl+A`, `Ctrl+C`, `Escape`, `F6`) may be
  sent unguarded: if they land in the wrong window they select and copy,
  they do not alter anything.
- **Anything that types text, presses Return, saves or closes** must be
  preceded by `assert_input_lands()`, which does a *round trip*: read the
  address bar and check it is our page. If it is not, the script **stops**.

The guard sets `GUARD_URL`/`GUARD_REASON` and the caller does
`|| fail …` at top level. It is deliberately **not** called as
`URL=$(assert_input_lands …)` — `fail` ends with `exit`, and an `exit`
inside `$( )` ends only the subshell, so the script carried on and clicked
anyway. That was measured, and it is why the shape looks the way it does.

---

## 8. Pacing

| Setting | Value |
|---|---|
| `PRE_CLOSE_DELAY_SECONDS` / `POST_CLOSE_DELAY_SECONDS` | 10.0 / 10.0 |
| `SEARCH_FIELD_DELAY_SECONDS` | 7 |
| **between keywords** | **close the browser → 5 s → open → verify fields** |
| **after a complete cycle** | **close the browser → 10 min → open → verify fields** |
| `KEYWORD_GAP` / `CITY_GAP` | 20–45 s / 60–180 s — *only when `RESTART_BROWSER_BETWEEN_KEYWORDS = False`* |
| `LISTING_PAGE_GAP` | 15–30 s |
| `JOB_GAP` | 0 (the two 10 s delays already apply) |
| work period → break | 3.7–4.2 h → 30–60 min |
| `CYCLE_COOLDOWN_MINUTES` | 45 |
| **night rest 23:00–05:00 Asia/Kolkata** | **`NIGHT_PAUSE_ENABLED = False` — currently DISABLED** |

The night rest is implemented and the banner prints `disabled` when it is
off. Set `NIGHT_PAUSE_ENABLED = True` in `find_indeed_job.py` to enable it.

---

## 9. Checkpoint and resume

`config/checkpoints/checkpoint_rank_1.json` holds, among others:

```
rank, num_sys, crawl_cycle_number, cities, cities_fingerprint,
keyword_order (1264), keyword_plan_fingerprint, shuffle_seed,
current_city_index, current_keyword_index, current_page,
current_city, current_keyword, done_job_urls, completed_cities,
total_complete_cycle, saved_jobs, duplicate_jobs, rejected_jobs,
failed_jobs, examined_jobs, failure_state, cycle_complete, updated_at
```

- Written after every job and on `SIGINT`/`SIGTERM` (`[STOP] signal 2.
  Checkpoint saved`).
- The fingerprints detect a changed plan or city list, so a resume cannot
  silently crawl a different plan than it started.
- `completed_cities` and `total_complete_cycle` are what make city-wise
  complete cycles survive a restart.
- A city interrupted by an access refusal is **not** marked complete.

---

## 10. Files written

| Path | What |
|---|---|
| `Excel_Data/rank_N/current_data.xlsx` | the working 32-column workbook |
| `Excel_Data/rank_N/current_data_cycleN.xlsx` | archives, every 100 rows |
| `Backup/rank_N/` | pre-rollover backups, 20 kept |
| `Temp_Data/rank_N/job_<rank>_<NNNN>.html` | saved page sources, one per job |
| `Temp_Data/rank_N/listing_<rank>_page<NN>.html` | the page census — one per results page |
| `Temp_Data/rank_N/browser_window.json` | pid, window id, geometry |
| `config/checkpoints/checkpoint_rank_N.json` | resume state |
| `config/firefox_profile/rank_N/` | the dedicated browser profile |
| `config/xauth_xwayland` | X cookie copy the snap can read |
| `logs/` | run logs |

---

## 11. Failure handling

Shell scripts exit with codes Python maps to typed exceptions:

| Code | Meaning |
|---:|---|
| 2 | usage |
| 3 | browser would not start |
| 4 | no window / it disappeared |
| 5 | focus — **input guard refused to act** |
| 6 | (retired) fullscreen |
| 7 | expected page is not there |
| 8 / 9 | clipboard stale / empty |
| 10 | **access denied** |
| 11 | selected job is not the job we meant |
| 12 | Ctrl+U produced no view-source tab |
| 13 / 14 | save dialog / saved file |
| 15 | window is not a usable size |

An **access refusal stops the unit of work**. Nothing retries a refusal,
rotates an identity, changes a user agent, cycles a session or touches a
CAPTCHA.

---

## 12. Safety rules the code enforces

- Never adopt, focus, type into or close a Firefox window this project did
  not start. Pre-existing windows are recorded and refused.
- Never write outside `$HOME` (snap confinement would silently lose it).
- Never modify `/home/ubuntu/check_indeed/` — it is imported read-only.
- Never advance the checkpoint for a job Excel did not accept.
- Never write a placeholder into a missing field.
- Refuse to act rather than act on an unverified window.

---

## 13. How to run it

```bash
cd /home/ubuntu/new_indeed_script

# all tests, no browser needed
for t in test_role_plan test_city_distribution test_extractor \
         test_source_recovery test_delays test_regressions; do
  python3 -m unittest tests.$t
done

# show the plan without touching the site
python3 find_indeed_job.py --plan

# local HTML fixtures, real Firefox, no Indeed
python3 find_indeed_job.py --fixture-run

# live collection (requires explicit approval)
INDEED_LIVE_APPROVED=yes python3 find_indeed_job.py
```

Diagnostics in `tools/`: `capture_cards.sh` (capture N cards live — it runs
the page census first and lowers its own count to match),
`page_cards.py` (the census for any saved page: cards shown, and what the
search actually matched), `extract_captured.py` (extract offline from the
saved files), `inspect_source.py` (what is really inside a saved file),
`xwd_to_png.py` (turn a window capture into a viewable PNG — this machine
has no screenshot tool).

---

## 14. What is proven, and what is not

**Test suite: 299 tests, all passing** under `venv/bin/python`.

`tests/test_field_scan.py` runs `verify_search_fields.sh` **for real**
against fake `xdotool`/`xclip` standing in for Firefox. The fake models the
one thing that caused the failure — a click inside a box types into it, a
click anywhere else leaves focus on the document where `Ctrl+A` selects the
whole page — so both the fault and the scan that fixes it are reproducible
without a browser.

### Verified live against real Indeed
- Firefox opens in a **normal window** (1850×1053, title bar, not fullscreen).
- The address bar can be read back reliably.
- **Form typing works** — "Social Media Designer" and "Delhi" were typed
  into Indeed's own boxes, read back, and submitted; the result page title
  was *300 Social Media Designer Job Vacancies in Delhi*.
- Indeed **pre-selects** the first job; `select_job_card.sh` takes it with
  `selection_method=preselected` and **zero clicks**.
- **Ctrl+U opens the view-source tab** for the selected job, confirmed by
  window capture and by the address bar reading
  `view-source:…&vjk=60c2445d0567a701`.
- The saved source **does contain the selected job's details** — title,
  company, location, salary and description text all present.
- Ctrl+S drives the GTK save dialog and writes a file (verified on fixtures;
  the dialog was also driven live).
- View-source → original HTML recovery is **byte-for-byte exact**.

Since that list was written, more became true, measured rather than
assumed:

- **The page census works live.** Saved pages in `Temp_Data/` now show it
  doing its job across three ranks:

  | Search | Matched | Cards on page 1 | Collected |
  |---|---:|---:|---|
  | 7 Product Consultant jobs, Vapi | 7 | 7 | all 7, then next keyword |
  | 17 Book Editor jobs, Madurai | 17 | 15 | capped at 10, then `start=10` |
  | Social Media Designer, Delhi | 346 | 15 | capped at 10 |

  A full page is capped at the fixed ten; a short page is taken whole. Both
  behaviours confirmed against real saved sources.
- **`"jobCount"` is not the card count** and nothing decides from it any
  more. Measured: **5** on a page carrying **6** cards for a search matching
  **17**. Across 25 saved pages it was present on two and wrong on both.
  `"totalJobCount"` and the `<title>` are the match count, and they agree.

- **Live rows exist.** `Excel_Data/rank_1/current_data.xlsx` holds 6 rows
  and `rank_2` holds 2, all 32 columns, written by live runs.
- **Job isolation works against real files.** `job_card_for_key()` resolves
  the selected job out of a document describing the whole page; the
  measured description went from a 135-character teaser to 3,846 characters
  once the detail pane was preferred over the card snippet.
- **Card probing and scrolling work past card 0** — 12 of 12 cards taken on
  one page in a live run.

### Not yet proven end-to-end
- **The page census has not run live.** `page_cards()` is verified against
  the real saved pages in `Temp_Data/` (that is where the 0-match
  measurement comes from), and `card_budget_for_page()` is unit-tested, but
  the Ctrl+U/Ctrl+S that *produces* the census file has only been exercised
  through the per-job path, not the per-page one. They call the same
  `save_page_source.sh`.
- **URL paging has not run live.** `start=10/20/30/40` is unit-tested
  against the two worked examples and never driven in a browser.
- **The between-keyword browser restart has not run live.** The order
  (close → wait → open → verify) is proven by a recording test, but no live
  run has closed Firefox and reopened it between two keywords.
- **The probe-and-learn scan has not run live.** It converges against the
  simulated browser — box 30 px below the guess, found on probe 5, location
  box on probe 6, and 2 probes once the offset is remembered — but no live
  run has watched it find a real box. Run `--verify-fields` once before
  trusting a long run to it.
- `experience_required` mirrors the description text. That is the upstream
  `parse_experience()` behaviour and was deliberately left alone.

### A data question this exposed, for the operator to decide
A search that matches **nothing** still shows cards, and those cards get
collected with `search_keyword` set to the keyword that matched nothing.
Two rows in `Excel_Data/rank_2/` are exactly this: *Computer Operator* and
*Marketing and Social Media Intern*, stored under the keyword
**"Mdm Engineer"**. They are real jobs and real adverts — but they are not
Mdm Engineer jobs. Nothing in the code discards them, because discarding
collected data is not a decision to make silently. The run now says so in
the log every time it happens.

### The standing environmental risk
On this Wayland desktop the automation only works while our window genuinely
holds focus. If you use the machine during a run, keystrokes can be
delivered elsewhere — three live runs died this way. The code now **fails
safely** instead of misfiring, but it still fails. The durable fixes are an
**Ubuntu on Xorg** session or a dedicated **Xvfb** display (the latter needs
a small window manager installed for a verifiable window state).
