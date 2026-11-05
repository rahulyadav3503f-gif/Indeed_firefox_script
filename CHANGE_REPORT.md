# Firefox + Ctrl+U/Ctrl+S conversion — change report

Date: 2026-11-05

## 1. What was asked, and the headline result

Replace Opera with Firefox, drive it with xdotool/xclip, take each job's
details from the page SOURCE saved with Ctrl+U then Ctrl+S, extract into the
existing 32-column Excel schema leaving unstated fields blank, and use the
newly supplied `target_audience_roles.py` and `new_mylib.py`.

**Done and verified:** the role/city switch, all six Firefox control
scripts, the saved-source extractor, the blank-field rule, both 10-second
delays. 102 tests pass.

**Done but NOT reliable on this machine:** the browser automation itself.
The desktop is Wayland, and keystrokes cannot be reliably delivered to our
window. This is measured, not suspected — see section 6. It is the one thing
standing between this project and a working run, and it needs a decision.

**Not done:** the limited live check against Indeed, because it depends on
the above.

---

## 2. Files created

| File | What it is |
|---|---|
| `vendor/target_audience_roles.py` | The authoritative keyword file, copied verbatim (md5 `54b2540006a5…`) |
| `vendor/new_mylib.py` | The authoritative city file, copied verbatim (md5 `5e06a7d1edef…`) |
| `vendor/PROVENANCE.json` | Where both came from, their md5 and size |
| `shell_scripts/_common.sh` | Rebuilt from scratch — exit codes, logging, window/clipboard primitives, and the four measured platform facts |
| `shell_scripts/open_firefox.sh` | Launch our own Firefox, fullscreen, verified |
| `shell_scripts/select_job_card.sh` | Click card N, then prove which job is showing |
| `shell_scripts/save_page_source.sh` | Ctrl+U, Ctrl+S, prove a real file arrived |
| `shell_scripts/close_source_tab.sh` | Close the source tab, confirm we are back on the listing |
| `source_file/indeed_source.py` | Saved source → the 32-column row |
| `tests/test_source_recovery.py` | 20 tests: recovery, JSON-LD, blank cells |
| `tests/test_delays.py` | 7 tests: both delays and their ORDER |
| `tests/fixtures/job_detail_jsonld.html` | Job page with JSON-LD and deliberately absent fields |

## 3. Files modified

| File | Change |
|---|---|
| `target_audience_roles.py` | Shim now re-exports the vendored authoritative file; exposes `role_department`, `role_plan_breakdown`, `classify_job`, `is_out_of_scope_row` |
| `new_mylib.py` | Shim now loads the vendored copy |
| `upstream.py` | Added `load_vendored()` and `vendor_provenance()` |
| `source_file/indeed_controller.py` | Opera → Firefox; `open_job_window`/`copy_job_details`/`close_job_window` replaced by `select_job_card`/`save_job_source`/`close_source_tab` |
| `find_indeed_job.py` | Per-job loop now saves source and parses the file; Opera/context-menu config replaced by Firefox + card geometry |
| `tests/test_role_plan.py` | Rewritten for the new plan (was asserting 85 roles) |

## 4. Files deleted

`shell_scripts/open_indeed.sh`, `open_job_window.sh`, `close_job_window.sh`,
`copy_job_details.sh`, `tools/calibrate_context_menu.sh` — all Opera-specific
and replaced.

---

## 5. Implementation details worth knowing

### 5.1 The keyword plan grew 15×

The project was wired to an **85-keyword, IT-only** file. The newly supplied
file produces **1,264 keywords**: Track A (200 — the 15 priority profiles
expanded into real search synonyms, the rest of the target audience, and 40
trending IT roles) interleaved through Track B (1,064 fresher-plausible
titles across 116 departments).

`is_non_it_title()` keeps its name and contract but is now a two-track
whitelist: `is_non_it_title("Staff Nurse")` was `True` (drop), is now
`False` (keep), and `role_department("Staff Nurse")` returns `"Nursing"`.
Nothing in this project re-filters its result.

Cities are unchanged: the supplied `new_mylib.py` was **byte-identical** to
the one already in use, so all 110 cities are the same.

Both files were **copied into `vendor/`** rather than imported from
`~/Desktop/naukri_script (1)/`. The authoritative file's own MAINTENANCE
note says each script folder must be self-contained and must never import
across folders — and a project whose role plan vanishes when a Desktop
folder is tidied up is not a project. `tests/test_role_plan.py` re-checks
the md5s.

### 5.2 Ctrl+S on a view-source tab does not save HTML

This was the biggest surprise, and it is measured. Ctrl+S on a `view-source:`
tab writes Firefox's **rendered, syntax-highlighted** document — escaped
entities, every line wrapped in `<span id="lineN">`. A 1,440-byte fixture
came back as 7,715 bytes. Grepping the saved file for `<title>` finds
nothing.

The original source is recovered **exactly** — byte for byte, verified
against the fixture — by taking the text content of `<body id="viewsource">`
and unescaping it. `recover_original_html()` does this, and five tests pin
it, including escaped `&lt;`/`&gt;` and embedded scripts.

Two further quirks, both handled: Firefox appends its own extension
(`job_1.html` → `job_1.html.html`, so the file is located by glob and
renamed), and in "Web Page, complete" mode it writes a `_files/` sidecar
directory (suppressed via `browser.download.save_converter_index=1`, and
removed if it appears anyway).

### 5.3 Field extraction, best source first

1. **JSON-LD `JobPosting`** — the existing row builder already reads
   schema.org spellings (`datePosted`, `validThrough`, `employmentType`,
   `jobLocationType`), so they are passed through under their own names.
2. **`<meta>` tags** — `og:title`, `og:description`.
3. **Visible text** — converted to the shape the EXISTING clipboard parser
   expects, so `parse_job_text()` is reused rather than a second
   field-reader being written that could disagree with the first.

Earlier sources win; every field records its provenance.

### 5.4 The blank rule

A field is written into the raw dict **only when a real value was found**.
Absence stays absence, and the original builder's final line —
`{column: row.get(column, "") for column in DETAIL_COLUMNS}` — turns it into
an empty cell in the correct column with nothing shifted. No `"N/A"`,
`"Unknown"`, `"Not Found"` or `"None"` is written anywhere; a test asserts
that across all 32 columns.

Note what is *not* covered by that rule: `country`, `source_platform`,
`source_type`, `score`, `is_active`, `is_fake`, `fetched_at`, `job_id` are
filled by the existing approved row builder from constants and provenance,
not from the job page. They are excluded from the "blank columns" report so
the log stays honest.

### 5.5 Both 10-second delays

`close_source_tab()` sleeps `pre_close_delay_seconds` (10), closes the tab,
then sleeps `post_close_delay_seconds` (10). `tests/test_delays.py` asserts
the **sequence**, not a count — a test that only counted two sleeps would
pass for an implementation that slept twice after closing.

---

## 6. The blocking limitation: Wayland cannot deliver our keystrokes

`XDG_SESSION_TYPE=wayland`. xdotool only drives X11, so Firefox is forced
onto XWayland (`MOZ_ENABLE_WAYLAND=0`, `GDK_BACKEND=x11`) — that part works,
and the window is a real X11 window.

But **keyboard delivery is routed by the compositor, not by X focus.** While
testing, a `Ctrl+L/Ctrl+A/Ctrl+C` aimed at our window returned
`jsw jetour t2 spy shots` — content from **your** Firefox. Throughout,
`xprop` reported our window as `_NET_WM_STATE_FOCUSED` and
`xdotool getwindowfocus` returned our window id, so no amount of reading X
state detects it.

Contributing facts, all measured:
- `_NET_ACTIVE_WINDOW` and `_NET_CURRENT_DESKTOP` are not published by
  mutter on XWayland, so the active workspace cannot even be read.
- Our window sits on desktop 0 of 2; which one the compositor is showing is
  unknowable from X.
- The behaviour is intermittent: the full chain (F11 → Ctrl+U → Ctrl+S →
  dialog driven → file saved) worked end to end several times, then stopped.

**What was added in response:** `assert_input_lands()` — a round-trip guard.
Before anything that types text, presses Return, saves or closes, the script
reads the address bar and checks it is OUR page. If it is not, the script
**stops** rather than typing. Read-only keys (Ctrl+L/A/C, Escape, F6) may go
unguarded because they cannot alter anything. This makes a misdirected run
fail safely; it does not make it succeed.

You chose to keep the shared Wayland desktop. The guard is in place and the
scripts refuse rather than misbehave — but on the evidence, runs will stop
frequently and unattended collection will not complete. The two fixes that
remove the problem are a dedicated Xvfb display (needs a small window
manager installed for verifiable fullscreen) or logging into "Ubuntu on
Xorg".

---

## 7. Tests executed

| Suite | Tests | Result |
|---|---|---|
| `test_role_plan` | 20 | OK |
| `test_city_distribution` | 16 | OK |
| `test_extractor` | 39 | OK |
| `test_source_recovery` | 20 | OK |
| `test_delays` | 7 | OK |
| **Total** | **102** | **all passing** |

Run them with:

```bash
cd /home/ubuntu/new_indeed_script && for t in test_role_plan test_city_distribution test_extractor test_source_recovery test_delays; do python3 -m unittest tests.$t; done
```

### Browser steps verified live (against local `file://` fixtures only)

- Launching our own Firefox without touching yours — **verified**
- Window identified by pid, not by recency — **verified**
- Fullscreen set and confirmed via `_NET_WM_STATE_FULLSCREEN` — **verified**
- Address bar read back correctly — **verified**
- Ctrl+U opening the view-source tab — **verified**
- Ctrl+S opening the Save dialog and the path being typed in — **verified**
- A real file arriving in `Temp_Data/rank_1/` — **verified**
- Saved source recovering to the original bytes — **verified**

All of these succeeded at least once; none succeeds *reliably*, for the
reason in section 6.

---

## 8. Remaining limitations

1. **Keystroke delivery is unreliable on this desktop** (section 6). This is
   the blocker.

2. **The live Indeed check has not been run.** So the question your brief
   raised — *does Ctrl+U's document source actually contain the selected
   job's details, or does Indeed load them dynamically?* — is **unanswered**.
   The extractor reads JSON-LD first precisely because that is how job pages
   usually carry this, but that is an expectation, not a measurement. Do not
   assume the 32 fields populate from a real Indeed page until this is run.

3. **Card geometry is unverified.** `CARD_X=430`, `FIRST_CARD_Y=300`,
   `CARD_PITCH=148` are starting values, never checked against a real
   results page. `select_job_card.sh` verifies what got selected and refuses
   on a mismatch, so a wrong value shows up as a clean refusal rather than
   as the wrong job — but they will need tuning.

4. **A cycle is now ~15× longer.** 1,264 keywords × 110 cities, where it was
   85 × 110. Same searches per cycle for the target audience; the cycle just
   takes proportionally longer to come round. `FRESHER_ROLES_PER_DEPARTMENT`
   in the authoritative file is the one knob that shortens it.

5. **One keyword is self-rejecting.** `"Architect"` is in the plan but its
   own filter drops it — the plan builder uses the department-aware
   `is_senior_title("Architect", "Architecture")` while the row filter gets
   a bare title and cannot apply the architect carve-out. 1 of 1,264
   keywords (0.08%). Left exactly as delivered, per your instruction to
   preserve the module's filtering; pinned in `test_role_plan.py` so a fix
   upstream is noticed.

6. **Unrecognised job titles are kept, by design.** Step 8 of the new filter
   is "anything else → keep", so an unrecognised occupation reaches Excel
   labelled `DEFAULT_DEPARTMENT` ("IT Department"). This is the delivered
   behaviour and is documented in the authoritative file; flagging it
   because it affects what lands in your spreadsheet.

7. **The disk is at 99%** (≈500 MB free on `/`). Saved sources are small,
   but a long run writes one file per job.

8. **No unattended collection has been started**, as instructed.
