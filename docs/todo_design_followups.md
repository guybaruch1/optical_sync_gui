# Design follow-ups: functionality behind the new UI

The Live Session page's layout/styling was updated to match the
`claude.ai/design` mockup "Optical Sync GUI.dc.html" (project "GUI layout
redesign options", imported via the DesignSync MCP tool). That pass was
**visual only** — several controls now on screen don't do anything real
yet. This file tracks what's left, so nothing gets forgotten.

## Wired up already (no follow-up needed)

- **Frame drops checkbox** — fully functional. Toggles both `ir_frame_drops`
  and `rgb_frame_drops` visibility on `drop_plot` via the same
  `LivePlot.set_series_visible` the other two checkboxes already used, so
  there was no reason to leave it inert.

## Needs real implementation

### 1. Per-chart "Copy" button
Each chart's header row has a small `⧉` icon button (`gui/pages/live_session_page.py:_make_chart_header`). Currently it just sets `status_label` to "Copy isn't implemented yet." Unclear from the mockup alone what it should actually do — needs a decision:
- Copy the chart as an image to the clipboard?
- Copy the underlying series data (e.g. as CSV text) to the clipboard?

### 2. Per-chart "Export CSV" button
Same header row, next to Copy. Currently a no-op status message. Needs deciding:
- Does it export *only* that chart's own series, or the same full-session CSV as the automatic Stop export (`domain.csv_export.export_session_csvs`)?
- Where does it write to — same `output/` convention, or a user-chosen path (a file save dialog)?

### 3. Toolbar "Export CSV" button
`gui/pages/live_session_page.py`, `control_row`. Currently a no-op status message. Today, `pipeline_sync_raw.csv`/`pipeline_sync_frame_drops.csv` are only written automatically in `_on_session_finished`, once, at Stop. This button implies a **manual**, on-demand export — needs deciding whether it:
- Re-exports the same already-buffered rows from the last completed session (only meaningful after Stop), or
- Exports whatever's been captured so far *during* a still-running session (would need `TestSession`'s buffered rows to be readable mid-run, not just returned at `stop()`).

### 4. "Stats" section — avg / std / max tiles
`gui/widgets/stats_panel.py` tiles `hw_ts_sync_summary` and `optical_latency_summary` are placeholder text (`"-"`). Nothing in the engine currently tracks a running average/std-dev/max of anything. Needs:
- Decide the exact source metric for "Optical Latency" — the mockup uses that term, but the codebase doesn't; my best guess is it means `position_gap_ms`, but that should be confirmed, not assumed.
- Add running-stats tracking (count/mean/variance/max — a simple incremental accumulator, no need to store full history) somewhere in `engine/` or `gui/pages/live_session_page.py`, updated per pair like the drop counters already are.
- Decide the update cadence (every pair, like the drop counts, vs. every throttled `_on_stats_ready` tick like the plots).
- Format the tile text as `"avg / std / max"` (matching the mockup's compact style) once real numbers exist.

## Known visual limitations (not blocking, just honest about the gap)

- **Camera panel rounded corners**: `VideoPanel`'s `border-radius` styling paints correctly on the empty placeholder background, but Qt does **not** automatically clip a `QLabel`'s pixmap content to a rounded-corner mask — once a real video frame is showing, the corners will look square again despite the style. True clipping would need a custom paint event or a `QGraphicsEffect`/mask; not attempted here since it's cosmetic-only and non-trivial.
- **Camera panel size**: kept the existing responsive `Expanding` size policy rather than matching the mockup's fixed ~250x240px boxes, since shrinking the live video feed felt like a behavior change beyond "make it look like the mockup," not a pure style tweak. Revisit if you actually want smaller/fixed camera panels.
- **Sidebar scrolling**: the mockup's stats sidebar has `overflow-y:auto` (scrolls if content overflows). Not implemented — with today's 8 tiles it fits fine on a maximized window, but if more stats get added later this may need a `QScrollArea`.
