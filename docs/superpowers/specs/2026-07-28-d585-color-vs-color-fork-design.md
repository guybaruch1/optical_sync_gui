# D585 Color-vs-Color Fork — Design

## Goal

Fork `optical_sync_gui` into a new, independent sibling project that measures optical sync
between the Intel RealSense D585's two on-device color sensors (left/right, via its
"Dual RGB" firmware mode) instead of between an IR sensor and a dedicated RGB sensor.

The original `optical_sync_gui` is untouched. This is a new codebase for a different piece
of hardware with a different stream topology, not a mode switch inside the existing app.

## Background: what's different about the D585

Reference: `C:\Users\gbaruch\scripts\TS_Sync\d585_dual_rgb_mode.py` (standalone script, not
part of any existing project, provided as the source of truth for D585 mechanics).

- The D585 (and D535) ship with a firmware mode toggle between **Dedicated RGB (3C)** and
  **Dual RGB (2C)**. In Dedicated mode it behaves like a normal RealSense camera (one color
  sensor). In Dual RGB mode, the device exposes **two independent color streams** off the
  same physical stereo module, at `rs.stream.color` **stream index 1 (left)** and
  **stream index 2 (right)** — no infrared stream is involved in this fork at all.
- Mode is identified by USB product ID (PID), not by device name:
  - Dual RGB (2C): PIDs `0C01` (D535), `0C04` (D585), `0C07` (D585 Proto)
  - Dedicated RGB (3C): PIDs `0C02` (D535), `0C05` (D585), `0C08` (D585 Proto)
- Switching modes is: a debug-protocol register write (opcode `0x02`/MWD, register range
  `0x80000064`-`0x80000068`, 4-byte little-endian value: `0`=Dedicated, `1`=Dual) followed by
  `device.hardware_reset()`, which disconnects/reconnects the device over USB. The caller
  must re-enumerate by serial number afterward (PID will have changed).
- Both color streams support the same per-frame HW `frame_timestamp` metadata this project's
  metrics already depend on. `left_ts - right_ts` is expected to be near zero (both streams
  are the same physical clock domain) — a persistent nonzero value is itself a meaningful
  finding, not assumed away.
- Frame retrieval uses `frameset.get_color_frame(stream_index)`, which matches on
  `stream_type()==COLOR and stream_index()==index` internally.

## Scope decisions (confirmed)

- **Fork mechanism**: new sibling directory `optical_sync_gui_d585` next to
  `optical_sync_gui`, copied from the current source tree, with fresh git history (single
  initial commit) — not a branch of this repo, not a GitHub fork.
- **Mode switching**: built into the GUI's Device Select page. If the selected device is in
  Dedicated RGB mode, the page performs the switch + hardware reset + re-enumeration itself
  before proceeding, so the wizard works end-to-end on a freshly-connected device with no
  separate script run required first.
- **Metrics scope**: both existing metrics carry over, symmetric across left/right —
  `PairingGapMetric` (HW-timestamp delta) and `PositionGapMetric` (LED-scan position offset,
  requiring per-stream ROI + calibration, same as today's IR/RGB workflow). The full wizard
  (Device Select → Stream Config → ROI Select → Calibration → Live Session) is preserved.
- **Naming**: the two streams are called **left**/**right** throughout — variables, function
  params, `config.yaml` keys, CSV columns, UI labels/titles. This replaces `ir`/`rgb` naming
  everywhere it appears today.
- **Settled-frame capture approach** (Calibration, ROI Select): keep this codebase's existing
  raw-sensor-callback mechanism (`capture_synced_frame_pair`), which was deliberately chosen
  over `rs.pipeline()` after the pipeline-based approach previously caused spurious
  zero-LEDs-detected results (see `roi_select_page.py`/`calibration_page.py`'s existing
  comments). Adapted to open **one** color sensor with both stream-index profiles instead of
  two separate sensor objects, keying its callback by `stream_index()` instead of
  `stream_type()`. Live Session's `ContinuousCapture` keeps using `rs.pipeline()` as it
  already does today, just enabling color index 1+2 instead of infrared+color.
- **Device scope**: Device Select lists only devices recognized as D535/D585 Dual/Dedicated
  RGB variants (by PID), not arbitrary RealSense devices.

## File-by-file plan

### New module: `engine/rgb_mode.py`

Ported from `d585_dual_rgb_mode.py`'s mode-switch mechanics (hardware-facing, so it belongs
alongside `engine/streams.py`/`engine/led_panel.py`, not in `domain/`):

- `DUAL_RGB_PIDS`, `DEDICATED_RGB_PIDS` (PID constant sets)
- `get_mode(device) -> "dual" | "dedicated" | None` — pure PID lookup, no I/O beyond
  `device.get_info(...)`. This is the one function in this module that's pure enough to
  unit-test without hardware (fake an object with a `get_info` method).
- `switch_mode(device, target_mode)` — debug-protocol register write + `hardware_reset()`,
  returns the serial number to re-enumerate against.
- `wait_for_reenumeration(ctx, serial, timeout_s)` — polls `ctx.query_devices()` until the
  serial reappears.
- `ensure_dual_rgb_mode(ctx, device) -> device` — checks mode, switches+re-enumerates only if
  currently Dedicated, returns a device handle guaranteed to be in Dual RGB mode. This is what
  `device_select_page.py` calls.

`switch_mode`/`wait_for_reenumeration`/`ensure_dual_rgb_mode` are hardware-facing and stay
untested by design, matching this project's existing convention for
`engine/session_engine.py`/`engine/led_panel.py`.

### `engine/streams.py`

- `list_devices(ctx)`: filter by `product_id` in `DUAL_RGB_PIDS | DEDICATED_RGB_PIDS`
  (imported from `engine.rgb_mode`) instead of today's "Stereo Module"/"RGB Camera" sensor-
  name filter. `DeviceInfo` gains a `mode` field (`"dual"`/`"dedicated"`) so Device Select can
  display it and decide whether to switch mode.
- `get_sensors_for_device` → `get_color_sensor_for_device(ctx, serial)`: returns the single
  sensor exposing both color stream indices (the sensor whose `.profiles` include entries
  with `stream_index() in (1, 2)` for `rs.stream.color`). Raises a clear error if no such
  sensor is found (this exact assumption — one sensor, two indices — needs confirming against
  real hardware; the error message should say so).
- `list_supported_profiles(sensor, stream_type, fmt, stream_index)`: add a `stream_index`
  parameter. Today this only filters by `stream_type`+`format`, which would conflate index-1
  and index-2 profiles now that both are `rs.stream.color`.
- `match_profile(sensor, stream_type, fmt, width, height, fps, stream_index)`: same addition.
- `capture_synced_frame_pair(color_sensor, left_profile, right_profile, on_both_streaming=None, settle_frames=15, timeout_s=10.0)`:
  rewritten to open **one** sensor with `[left_profile, right_profile]` (previously two
  separate sensor objects), with callback state keyed by
  `frame.get_profile().stream_index()` (1 vs 2) instead of `stream_type()`. Same
  open-both/start-both/wait-for-streaming/trigger/reset-counters/wait-for-settled/stop-both
  flow as today, just one sensor instead of two.
- `ContinuousCapture.__init__`: rename params to `left_resolution, left_fps, right_resolution, right_fps`.
  `start()` calls `config.enable_stream(rs.stream.color, 1, *left_resolution, rs.format.bgr8, left_fps)`
  and `config.enable_stream(rs.stream.color, 2, *right_resolution, rs.format.bgr8, right_fps)`.
  `frames_with_diagnostics()` uses `frameset.get_color_frame(1)`/`frameset.get_color_frame(2)`
  instead of `get_infrared_frame()`/`get_color_frame()`, and decodes both with the new
  `color_bytes_to_image` (see below) instead of `ir_bytes_to_image`/`yuyv_to_bgr`.
- `disable_ir_emitter`: dropped entirely — no IR stream is used anywhere in this fork.
- `enable_auto_exposure(sensor)`: kept unchanged, called once on the shared color sensor.
- Color format: `rs.format.bgr8` (matches `d585_dual_rgb_mode.py`'s `DEFAULT_COLOR_FORMAT`) —
  already a directly-displayable/OpenCV-compatible buffer layout, no conversion step needed
  (unlike today's `yuyv_to_bgr`).

### `domain/realsense_utils.py`

- Replace `ir_bytes_to_image` and `yuyv_to_bgr` with a single
  `color_bytes_to_image(raw_bytes, width, height)`:
  `np.frombuffer(raw_bytes, dtype=np.uint8).reshape((height, width, 3)).copy()` — both
  streams decode identically now (both bgr8), unlike today's differing y8-vs-yuyv formats.
- `draw_bundle_overlay(...)`: rename `ir_frame_number/color_frame_number/ir_ts_us/color_ts_us`
  params to `left_frame_number/right_frame_number/left_ts_us/right_ts_us`; drop the
  grayscale-conversion branch (both images are already BGR, unlike today's IR-may-be-2D
  case).
- Unchanged (already format-agnostic): `sample_neighborhood_brightness`,
  `sample_all_neighborhood_brightness`, `apply_roi_mask`, `crop_to_roi`,
  `merge_close_centroids`, `detect_led_centroids`, `save_debug_detection_image`,
  `draw_led_state_overlay` — only their `ir_`/`rgb_`-named parameters (where present) get
  renamed to `left_`/`right_`.

### `engine/metrics.py` / `engine/test_session.py`

- `FramePairSample`: `ir_ts_us`/`rgb_ts_us` → `left_ts_us`/`right_ts_us`;
  `ir_bright`/`rgb_bright` → `left_bright`/`right_bright`.
- `PairingGapMetric.update()`: `gap = sample.left_ts_us - sample.right_ts_us` (same
  left-minus-right sign convention as `d585_dual_rgb_mode.py`'s `analyze_ts_sync`).
- `PositionGapMetric`: constructor params/attributes renamed
  `ir_threshold/rgb_threshold` → `left_threshold/right_threshold`,
  `ir_fps/rgb_fps` → `left_fps/right_fps`,
  `last_ir_on_mask/last_rgb_on_mask` → `last_left_on_mask/last_right_on_mask`. The on/off
  brightness-threshold + LED-scan-position comparison logic itself is unchanged — it's
  already symmetric between "stream A" and "stream B".
- `TestSession.process_pair()`: row's `ir_ts_us`/`rgb_ts_us` keys → `left_ts_us`/`right_ts_us`.
- **No changes needed** to `Metric.name` values (`pairing_gap_us`, `position_gap_ms`) — these
  already stay the same regardless of what physically produces the two streams.

### `domain/calibration.py` + `config.yaml`

- `update_config_leds(config_path, camera_name, left_positions, left_res, right_positions, right_res)`
  and `load_led_positions(config_path, camera_name)`: `"ir"`/`"rgb"` keys in the per-camera
  dict become `"left"`/`"right"`.
- The forked project starts with no `config.yaml` calibration data (today's D435I/D415/D455
  entries are irrelevant hardware for this fork) — first Calibration run creates it fresh.

### GUI pages

- **`gui/pages/device_select_page.py`**: `refresh_devices()` displays each device's mode
  (e.g. `"Intel RealSense D585 (dual RGB) (123456789)"`). `_on_next_clicked()` — if the
  chosen device is in Dedicated mode, calls `engine.rgb_mode.ensure_dual_rgb_mode(ctx, device)`
  before emitting `device_chosen`, showing a status label (e.g. "Switching to Dual RGB
  mode...") and disabling the Next button for the several seconds `hardware_reset()` +
  re-enumeration takes.
- **`gui/pages/stream_config_page.py`**: `ir_combo`/`rgb_combo` → `left_combo`/`right_combo`.
  `populate()` calls `list_supported_profiles(color_sensor, rs.stream.color, rs.format.bgr8, stream_index=1)`
  and `stream_index=2` respectively (both against the same sensor now, not `stereo_sensor`/`rgb_sensor`).
- **`gui/pages/roi_select_page.py`**: `_capture_and_select()` calls
  `get_color_sensor_for_device`, matches `left_profile`/`right_profile` via the updated
  `match_profile(..., stream_index=1/2)`, calls the adapted `capture_synced_frame_pair` with
  one sensor, decodes both frames with `color_bytes_to_image`. ROI popup titles and status
  text relabeled "Left"/"Right" instead of "IR"/"RGB".
- **`gui/pages/calibration_page.py`**: same capture-path adaptation as ROI Select; log
  messages and debug-image filenames (`debug_ir_detection.png`/`debug_rgb_detection.png` →
  `debug_left_detection.png`/`debug_right_detection.png`) relabeled Left/Right;
  `update_config_leds(...)` called with the renamed left/right params.
- **`gui/pages/live_session_page.py`** / **`engine/session_engine.py`**: `ir_panel`/`rgb_panel`
  → `left_panel`/`right_panel` (titles "Left"/"Right"); all `ir_`/`rgb_`-named
  params/attributes (`ir_resolution`, `color_resolution`, `ir_fps`, `color_fps`, `ir_xy`,
  `rgb_xy`, `_ir_drop_count`, `_rgb_drop_count`, etc.) renamed to `left_`/`right_` equivalents;
  `frame_ready` signal emits `"left"`/`"right"` instead of `"ir"`/`"rgb"`. `_short_camera_name`
  is unchanged (already generic — splits on whitespace, takes the last token).

### `settings.yaml`

- `camera.ir`/`camera.color` → `camera.left`/`camera.right`.

### No changes needed

- `domain/csv_export.py` — already fully generic over whatever dict keys `TestSession`
  produces; needs zero changes.
- `gui/widgets/stats_panel.py` — already fully generic over metric name/key; needs zero
  changes.
- `domain/plot_export.py`, `gui/widgets/live_plot.py`, `gui/widgets/video_panel.py` — expected
  to need no changes (not yet inspected line-by-line, but nothing in their current
  responsibilities is IR/RGB-specific); confirm during implementation and note here if that
  assumption turns out wrong.

## Testing plan

- Mechanical rename pass (mirroring the production renames above) across:
  `tests/engine/test_metrics.py`, `test_streams.py`, `test_test_session.py`,
  `test_acquisition_loop.py`, `tests/domain/test_calibration.py`,
  `tests/gui/pages/test_stream_config_page.py`, `test_live_session_page.py`,
  `tests/state/test_gui_state.py`.
- New test file `tests/engine/test_rgb_mode.py` covering `get_mode()` only (pure PID lookup —
  fake object with `.get_info()`), following the same "test the pure part, leave the
  hardware-facing part untested by design" convention this project already uses for
  `engine/led_panel.py`/`engine/session_engine.py`.
- No test changes needed for `domain/test_csv_export.py` (module untouched).
- Full suite must still pass with `QT_QPA_PLATFORM=offscreen` and no hardware connected, same
  as today.

## Docs

- `CLAUDE.md`: rewritten for the fork — D585-only device scope, left/right naming
  throughout, the new Device Select mode-switch step, the single-sensor/two-stream-index
  capture approach replacing the "ported from `optical_sync_poc_`" IR-vs-RGB architecture
  notes. Should explain the Dedicated/Dual RGB PID distinction and why `engine/rgb_mode.py`
  exists, the way current CLAUDE.md explains the `Metric`/`TestSession`/`AcquisitionLoop`
  split.
- `README.md`: updated to describe the D585 dual-color-vs-color measurement instead of
  IR-vs-RGB, and to reference `d585_dual_rgb_mode.py`'s mode-switch mechanism as prior art.

## Open risks to confirm against real hardware during implementation

- Whether both color stream indices genuinely live on **one** sensor object reachable via
  `device.query_sensors()` (assumed: a single sensor, likely still named `"RGB Camera"`,
  whose `.profiles` include both index-1 and index-2 entries) — `get_color_sensor_for_device`
  should raise a clear, specific error if this assumption doesn't hold, rather than failing
  silently.
- Whether `left`/`right` (stream index 1/2) actually corresponds to true physical left/right
  on a given rig — `d585_dual_rgb_mode.py`'s snapshot-save mechanism (cover one lens, check
  which saved image goes dark) is the confirmation method; worth carrying that same
  cover-lens sanity check into the new project's Calibration or ROI Select flow as a one-time
  manual check, not automated.
