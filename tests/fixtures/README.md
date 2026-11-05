# Local test fixtures

These pages exist so the browser automation can be exercised **without
touching Indeed**. Brief section 24: "Perform automated browser tests using
local HTML fixtures or other permitted test pages. Do not perform bulk live
Indeed collection as part of the test suite."

| File | What it is for |
|---|---|
| `listing_page.html` | Two-panel results page with four real `<a href>` job links, nav links before them (so `LINK_TAB_OFFSET` is exercised), and 1400 px of filler so `scroll_jobs.sh` has somewhere to scroll. |
| `job_detail_1.html` | A complete IT job. The happy path for the extractor. |
| `job_detail_2.html` | A second IT job, different salary shape (single figure, not a range) and different skills. |
| `job_detail_3.html` | **"Sales Executive"** — must be rejected by `is_non_it_title()`. |
| `job_detail_blocked.html` | An access-refusal page. `looks_like_access_denied()` must catch it. |
| `job_detail_empty.html` | Nav furniture only. The `--min-chars` floor must reject it. |

They are not copies of Indeed's markup. They reproduce only the structural
facts the automation depends on: a two-panel layout, job titles that are
genuine links to separate pages, and the page furniture the extractor has to
strip.
