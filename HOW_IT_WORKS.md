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

Limits per keyword+city: `MAX_LISTING_PAGES = 4`,
`MAX_CARDS_PER_PAGE = 15`, `TARGET_UNIQUE_JOBS = 100`.

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
9. Verify **without copying the page**:
   - window title is not a refusal or an error page,
   - the URL matches `in.indeed.com…q=<keyword>…l=<city>`,
   - a `vjk=` parameter appears, which is Indeed saying "the results pane is
     populated" — and which hands over the pre-selected first job.

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
  times, until `vjk=` changes to a key not already handled.
- It reports `learned_card_y`, and Python starts the next card's probe just
  below it (`MIN_CARD_GAP = 60`), so the spacing is **learned per page**.
- `--seen-keys` stops a probe re-collecting a job already taken.
- If a click navigates away (some cards contain "View similar jobs" links),
  it presses **Back** and carries on probing.
- Nothing new below the limit ⇒ `no_more_cards=yes`, which the caller reads
  as the normal end of the page.

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
| `KEYWORD_GAP` | 20–45 s |
| `CITY_GAP` | 60–180 s |
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
| `Temp_Data/rank_N/job_<rank>_<NNNN>.html` | saved page sources |
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

Diagnostics in `tools/`: `capture_cards.sh` (capture N cards live),
`extract_captured.py` (extract offline from the saved files),
`inspect_source.py` (what is really inside a saved file),
`xwd_to_png.py` (turn a window capture into a viewable PNG — this machine
has no screenshot tool).

---

## 14. What is proven, and what is not

**Test suite: 140 tests, all passing** (role plan 20, cities 16, extractor
39, source recovery 20, delays 7, regressions 38).

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

### Not yet proven end-to-end
- **A complete 5-card capture has never finished.** The last attempt stopped
  at the search step: the keyword box read back empty, so the script
  correctly refused to submit. Three separate causes were found and fixed
  along the way (address-bar dropdown covering the page, toothless input
  guard, single-attempt clipboard reads); the remaining keyword read-back
  failure was still being diagnosed when work paused.
- **No row has been written to Excel from a live capture.** The Excel path
  is exercised by tests, not by a live run.
- **Job isolation from a listing document is written but unverified** — the
  `job_card_for_key()` field mapping was authored against Indeed's expected
  JSON shape and has not been run against a real saved file. Until it is,
  `report.isolation == "NONE"` is the signal that a row may mix jobs.
- Card-probe geometry beyond card 0 has not been exercised live.

### The standing environmental risk
On this Wayland desktop the automation only works while our window genuinely
holds focus. If you use the machine during a run, keystrokes can be
delivered elsewhere — three live runs died this way. The code now **fails
safely** instead of misfiring, but it still fails. The durable fixes are an
**Ubuntu on Xorg** session or a dedicated **Xvfb** display (the latter needs
a small window manager installed for a verifiable window state).
