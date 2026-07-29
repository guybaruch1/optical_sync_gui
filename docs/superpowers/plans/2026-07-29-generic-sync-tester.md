# Generic RealSense Sync Tester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This plan is written for a future execution pass** — a local machine with a
> multi-repo workspace (this repo plus room for a brand-new sibling directory) and,
> for the "Open risks" verification steps, real RealSense hardware (at minimum one
> D400-series device with a stereo module + dedicated RGB sensor, and one D500-series
> D585/D535 for the Dual RGB topology). It was authored in a docs-only remote pass with
> neither available and has not been executed.

**Goal:** Fork `optical_sync_gui` into `optical_sync_gui_generic` — a new standalone
project where the user picks any two video streams (any `stream_type`, any
`stream_index`, any resolution/fps/format) on any connected RealSense device, instead of
a hardcoded IR-vs-RGB or color-vs-color topology.

**Architecture:** Same `domain -> engine -> gui` + `state` layering as both existing
projects. The one genuinely new function, `resolve_and_group`, groups two stream picks by
their *distinct resolved sensor object* — collapsing "two separate sensors" (today's
IR+RGB shape) and "one shared sensor, two stream indices" (D585's shape) into a single
code path. Everything else is a mechanical rename (`ir_`/`rgb_` → `stream_a_`/`stream_b_`)
or a straightforward parameterization (`stream_index` added to existing profile-matching
functions, exactly as the D585 fork already did).

**Tech Stack:** Python 3.10+, PySide6, pyrealsense2, opencv-python, numpy, pyyaml,
pyqtgraph, matplotlib, pytest.

## Global Constraints

- Full spec: `docs/superpowers/specs/2026-07-29-generic-sync-tester-design.md` (this repo, committed).
- New project root: a brand-new sibling directory next to `optical_sync_gui` and
  `optical_sync_gui_d585` (e.g. `optical_sync_gui_generic`), fresh git history.
- Scope: video streams only (`rs.stream.infrared`, `rs.stream.color`), any
  `stream_index`. No depth/motion/pose. Exactly two streams ("Stream A" / "Stream B") —
  not N-way.
- Naming: **`stream_a`**/**`stream_b`** everywhere `ir`/`rgb` (or `left`/`right`) appears
  today — variables, function params, `config.yaml` keys, CSV columns, UI labels. No
  `ir_`/`rgb_` names survive.
- D585 firmware mode-switch: copy `engine/rgb_mode.py` from `optical_sync_gui_d585`
  verbatim — do not re-derive it.
- Camera controls (new, not present in either existing project): user-configurable IR
  emitter on/off and auto/manual exposure+gain, applied once per **distinct resolved
  sensor**, not once per stream.
- Every task's tests must pass with `QT_QPA_PLATFORM=offscreen` and no hardware
  connected — this project's own convention, inherited from both existing projects.
- Hardware-facing modules (`engine/rgb_mode.py`'s non-pure functions,
  `engine/session_engine.py`, `gui/pages/roi_select_page.py`,
  `gui/pages/calibration_page.py`, `engine/stream_preview_thread.py`, `gui/main_window.py`)
  stay untested by design, matching both existing projects' convention — only their pure
  sub-parts get unit tests.

---

### Task 1: Fork the repository into a new sibling directory

**Files:**
- Create: `<parent>/optical_sync_gui_generic/` (full copy of `optical_sync_gui`'s current tree)
- Modify: `config.yaml` (reset to `leds: {}` — no carried-over device-specific calibration data)

- [ ] **Step 1: Copy the tree, excluding build/VCS artifacts**

```bash
SRC="/path/to/optical_sync_gui"
DST="/path/to/optical_sync_gui_generic"
mkdir -p "$DST"
cp -r "$SRC"/. "$DST"/
cd "$DST"
rm -rf .git .venv .pytest_cache output .claude gui_state.json
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
```

- [ ] **Step 2: Reset config.yaml to empty**

Replace the entire contents of `config.yaml` with:

```yaml
leds: {}
```

- [ ] **Step 3: Set up the venv and confirm the untouched copy still works**

```bash
cd "$DST"
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -v
```

Expected: all tests PASS (unmodified copy of already-working code) — a baseline check
before any renames/new logic begins.

- [ ] **Step 4: git init and first commit**

```bash
git init
git add -A
git commit -m "Initial import: fork of optical_sync_gui for generic stream-pair sync testing"
```

---

### Task 2: `engine/streams.py` — `list_video_stream_options` + `resolve_and_group`

**Files:**
- Modify: `engine/streams.py`
- Test: `tests/engine/test_streams.py`

**Interfaces:**
- Produces: `list_video_stream_options(ctx, serial) -> list[dict]` (each dict:
  `{"sensor_index": int, "stream_type": rs.stream, "stream_index": int, "format":
  rs.format, "width": int, "height": int, "fps": int}`), `resolve_and_group(device,
  pick_a: dict, pick_b: dict) -> list[tuple[sensor, list[profile]]]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_streams.py (additions)
import pyrealsense2 as rs
from engine.streams import list_video_stream_options, resolve_and_group


class FakeVideoProfile:
    def __init__(self, width, height):
        self._width, self._height = width, height
    def width(self): return self._width
    def height(self): return self._height


class FakeProfile:
    def __init__(self, stream_type, stream_index, fmt, width=None, height=None, fps=30, is_video=True):
        self._stream_type = stream_type
        self._stream_index = stream_index
        self._fmt = fmt
        self._fps = fps
        self._is_video = is_video
        self._video = FakeVideoProfile(width, height) if is_video else None

    def stream_type(self): return self._stream_type
    def stream_index(self): return self._stream_index
    def format(self): return self._fmt
    def fps(self): return self._fps
    def is_video_stream_profile(self): return self._is_video
    def as_video_stream_profile(self): return self._video


class FakeSensor:
    def __init__(self, profiles):
        self.profiles = profiles


class FakeDevice:
    def __init__(self, sensors):
        self._sensors = sensors
    def query_sensors(self):
        return self._sensors


def test_list_video_stream_options_includes_infrared_and_color_only():
    ir_sensor = FakeSensor(profiles=[
        FakeProfile(rs.stream.infrared, 1, rs.format.y8, 1280, 720, 30),
        FakeProfile(rs.stream.gyro, 0, rs.format.motion_xyz32f, is_video=False),  # excluded: not IR/color
    ])
    color_sensor = FakeSensor(profiles=[
        FakeProfile(rs.stream.color, 0, rs.format.bgr8, 1280, 720, 30),
    ])
    device = FakeDevice([ir_sensor, color_sensor])

    options = list_video_stream_options_from_device(device)  # test the pure-device-arg variant directly

    assert len(options) == 2
    assert {"sensor_index": 0, "stream_type": rs.stream.infrared, "stream_index": 1,
            "format": rs.format.y8, "width": 1280, "height": 720, "fps": 30} in options
    assert {"sensor_index": 1, "stream_type": rs.stream.color, "stream_index": 0,
            "format": rs.format.bgr8, "width": 1280, "height": 720, "fps": 30} in options


def test_list_video_stream_options_excludes_non_video_profiles_without_crashing():
    sensor = FakeSensor(profiles=[
        FakeProfile(rs.stream.pose, 0, rs.format.six_dof, is_video=False),
    ])
    device = FakeDevice([sensor])

    options = list_video_stream_options_from_device(device)

    assert options == []  # no crash from calling width()/height() on a non-video profile


def test_resolve_and_group_two_distinct_sensors():
    ir_profile = FakeProfile(rs.stream.infrared, 1, rs.format.y8, 1280, 720, 30)
    color_profile = FakeProfile(rs.stream.color, 0, rs.format.bgr8, 1280, 720, 30)
    ir_sensor = FakeSensor(profiles=[ir_profile])
    color_sensor = FakeSensor(profiles=[color_profile])
    device = FakeDevice([ir_sensor, color_sensor])
    pick_a = {"sensor_index": 0, "stream_type": rs.stream.infrared, "stream_index": 1,
              "format": rs.format.y8, "width": 1280, "height": 720, "fps": 30}
    pick_b = {"sensor_index": 1, "stream_type": rs.stream.color, "stream_index": 0,
              "format": rs.format.bgr8, "width": 1280, "height": 720, "fps": 30}

    groups = resolve_and_group(device, pick_a, pick_b)

    assert len(groups) == 2  # two distinct sensors -> two groups
    sensors_in_groups = [g[0] for g in groups]
    assert ir_sensor in sensors_in_groups and color_sensor in sensors_in_groups
    for sensor, profiles in groups:
        assert len(profiles) == 1


def test_resolve_and_group_one_shared_sensor():
    left_profile = FakeProfile(rs.stream.color, 1, rs.format.bgr8, 1280, 720, 30)
    right_profile = FakeProfile(rs.stream.color, 2, rs.format.bgr8, 1280, 720, 30)
    shared_sensor = FakeSensor(profiles=[left_profile, right_profile])
    device = FakeDevice([shared_sensor])
    pick_a = {"sensor_index": 0, "stream_type": rs.stream.color, "stream_index": 1,
              "format": rs.format.bgr8, "width": 1280, "height": 720, "fps": 30}
    pick_b = {"sensor_index": 0, "stream_type": rs.stream.color, "stream_index": 2,
              "format": rs.format.bgr8, "width": 1280, "height": 720, "fps": 30}

    groups = resolve_and_group(device, pick_a, pick_b)

    assert len(groups) == 1  # one shared sensor -> one group
    sensor, profiles = groups[0]
    assert sensor is shared_sensor
    assert len(profiles) == 2
```

Note: the test calls a `list_video_stream_options_from_device(device)` helper — this is
the device-arg-only half of `list_video_stream_options(ctx, serial)` (which itself must
call `find_device_by_serial(ctx, serial)` then delegate), split out so it's directly
testable against a `FakeDevice` without needing a `FakeRsContext` too. Export both.

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: FAIL (functions don't exist yet).

- [ ] **Step 3: Implement in `engine/streams.py`**

```python
def list_video_stream_options_from_device(device):
    options = []
    for sensor_index, sensor in enumerate(device.query_sensors()):
        for p in sensor.profiles:
            if not p.is_video_stream_profile():
                continue
            if p.stream_type() not in (rs.stream.infrared, rs.stream.color):
                continue
            vp = p.as_video_stream_profile()
            options.append({
                "sensor_index": sensor_index,
                "stream_type": p.stream_type(),
                "stream_index": p.stream_index(),
                "format": p.format(),
                "width": vp.width(),
                "height": vp.height(),
                "fps": p.fps(),
            })
    return options


def list_video_stream_options(ctx, serial):
    device = find_device_by_serial(ctx, serial)
    return list_video_stream_options_from_device(device)


def _pick_matches(profile, pick):
    if profile.stream_type() != pick["stream_type"] or profile.stream_index() != pick["stream_index"]:
        return False
    if profile.format() != pick["format"] or profile.fps() != pick["fps"]:
        return False
    vp = profile.as_video_stream_profile()
    return vp.width() == pick["width"] and vp.height() == pick["height"]


def resolve_and_group(device, pick_a, pick_b):
    sensors = list(device.query_sensors())

    def sensor_and_profile_for(pick):
        sensor = sensors[pick["sensor_index"]]
        profile = next(p for p in sensor.profiles if _pick_matches(p, pick))
        return sensor, profile

    sensor_a, profile_a = sensor_and_profile_for(pick_a)
    sensor_b, profile_b = sensor_and_profile_for(pick_b)

    if sensor_a is sensor_b:
        return [(sensor_a, [profile_a, profile_b])]
    return [(sensor_a, [profile_a]), (sensor_b, [profile_b])]
```

Add `find_device_by_serial(ctx, serial)` too if not already present (mirrors the D585
fork's helper of the same name — reuse that implementation verbatim if convenient).

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/streams.py tests/engine/test_streams.py
git commit -m "feat: add generic stream discovery and sensor-grouping to streams.py"
```

---

### Task 3: `engine/streams.py` — generalize `list_supported_profiles`/`match_profile`, drop the old sensor-name filter

**Files:**
- Modify: `engine/streams.py`
- Test: `tests/engine/test_streams.py`

**Interfaces:**
- Produces: `list_devices(ctx) -> list[DeviceInfo]` (no sensor-name filter),
  `list_supported_profiles(sensor, stream_type, fmt, stream_index) -> list[(w,h,fps)]`,
  `match_profile(sensor, stream_type, fmt, width, height, fps, stream_index) -> profile`.

- [ ] **Step 1: Write the failing test**

```python
def test_list_devices_lists_any_device_regardless_of_sensor_names():
    # A device whose sensors are named things other than "Stereo Module"/"RGB Camera"
    # (e.g. a D500-series device with different sensor naming) must still be listed.
    ...  # fake ctx.query_devices() returning a device with arbitrarily-named sensors


def test_list_supported_profiles_filters_by_stream_index():
    sensor = FakeSensor(profiles=[
        FakeProfile(rs.stream.color, 1, rs.format.bgr8, 1280, 720, 30),
        FakeProfile(rs.stream.color, 2, rs.format.bgr8, 1280, 720, 30),
    ])
    result = list_supported_profiles(sensor, rs.stream.color, rs.format.bgr8, stream_index=1)
    assert result == [(1280, 720, 30)]


def test_match_profile_finds_exact_match_for_given_stream_index():
    target = FakeProfile(rs.stream.color, 2, rs.format.bgr8, 1280, 720, 30)
    sensor = FakeSensor(profiles=[FakeProfile(rs.stream.color, 1, rs.format.bgr8, 1280, 720, 30), target])
    matched = match_profile(sensor, rs.stream.color, rs.format.bgr8, 1280, 720, 30, stream_index=2)
    assert matched is target
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: FAIL (`list_devices` still filters by sensor name; `list_supported_profiles`/
`match_profile` don't accept `stream_index`).

- [ ] **Step 3: Modify `engine/streams.py`**

Remove the `"Stereo Module" in names and "RGB Camera" in names` filter from `list_devices`
— list every device `ctx.query_devices()` returns. Add a `stream_index` parameter to
`list_supported_profiles`/`match_profile`, filtering/matching on it alongside
`stream_type`/`format` (mirrors the change the D585 fork's own spec already made to these
two functions — copy that reasoning here).

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/streams.py tests/engine/test_streams.py
git commit -m "feat: list any device, add stream_index to profile matching"
```

---

### Task 4: `engine/streams.py` — generalize `capture_synced_frame_pair`

**Files:**
- Modify: `engine/streams.py`
- Test: `tests/engine/test_streams.py`

**Interfaces:**
- Consumes: `resolve_and_group`'s `groups` shape (Task 2)
- Produces: `capture_synced_frame_pair(groups, on_both_streaming=None, settle_frames=15,
  timeout_s=10.0) -> dict[(stream_type, stream_index), bytes]`

- [ ] **Step 1: Write the failing test**

Adapt the existing `_FakeStreamingSensor`-style fake (both existing projects already have
one — copy the pattern) to deliver frames for an arbitrary set of `(stream_type,
stream_index)` keys on a background thread, so the reset-then-wait-for-fresh-frames
control flow is genuinely exercised:

```python
def test_capture_synced_frame_pair_with_two_distinct_sensors():
    ir_sensor = _FakeStreamingSensor(keys=[(rs.stream.infrared, 1)])
    color_sensor = _FakeStreamingSensor(keys=[(rs.stream.color, 0)])
    groups = [(ir_sensor, ["ir_profile"]), (color_sensor, ["color_profile"])]
    triggered = {"count": 0}

    frames = capture_synced_frame_pair(groups, on_both_streaming=lambda: triggered.__setitem__("count", triggered["count"] + 1), settle_frames=5, timeout_s=5.0)

    assert triggered["count"] == 1
    assert (rs.stream.infrared, 1) in frames
    assert (rs.stream.color, 0) in frames


def test_capture_synced_frame_pair_with_one_shared_sensor_two_stream_indices():
    shared_sensor = _FakeStreamingSensor(keys=[(rs.stream.color, 1), (rs.stream.color, 2)])
    groups = [(shared_sensor, ["left_profile", "right_profile"])]

    frames = capture_synced_frame_pair(groups, settle_frames=5, timeout_s=5.0)

    assert (rs.stream.color, 1) in frames
    assert (rs.stream.color, 2) in frames
    assert frames[(rs.stream.color, 1)] != frames[(rs.stream.color, 2)]  # distinguishable, not accidentally aliased


def test_capture_synced_frame_pair_raises_on_timeout_when_no_frames_arrive():
    sensor = _FakeNonDeliveringSensor()
    groups = [(sensor, ["profile"])]
    with pytest.raises(RuntimeError):
        capture_synced_frame_pair(groups, settle_frames=5, timeout_s=0.2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
def capture_synced_frame_pair(groups, on_both_streaming=None, settle_frames=15, timeout_s=10.0):
    state = {}
    for _, profiles in groups:
        for _ in profiles:
            pass  # keys populated by the callback itself, first time it sees each (stream_type, stream_index)

    def callback(frame):
        key = (frame.get_profile().stream_type(), frame.get_profile().stream_index())
        s = state.setdefault(key, {"count": 0, "frame": None})
        s["count"] += 1
        s["frame"] = bytes(frame.get_data())

    for sensor, profiles in groups:
        sensor.open(profiles)
    try:
        for sensor, _ in groups:
            sensor.start(callback)

        all_keys = [(p.stream_type(), p.stream_index()) for _, profiles in groups for p in profiles]

        def wait_until(predicate, label):
            start = time.time()
            while not predicate():
                if time.time() - start > timeout_s:
                    raise RuntimeError(f"Timed out ({label}) waiting for frames on {all_keys}")
                time.sleep(0.05)

        wait_until(lambda: all(state.get(k, {}).get("count", 0) >= 1 for k in all_keys), "waiting for initial frames")
        if on_both_streaming is not None:
            on_both_streaming()
        for k in all_keys:
            state[k]["count"] = 0
        wait_until(lambda: all(state[k]["count"] >= settle_frames for k in all_keys), "waiting for post-trigger settled frames")

        return {k: state[k]["frame"] for k in all_keys}
    finally:
        for sensor, _ in groups:
            sensor.stop()
            sensor.close()
```

Same open-both/start-both/wait-for-streaming/trigger/reset-counters/wait-for-settled/
stop-both flow both existing projects already use — generalized to N sensors (in
practice 1 or 2) and keyed by `(stream_type, stream_index)` instead of `stream_type()`
alone, so two same-`stream_type` picks (e.g. two infrared, or two color) don't collide.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/streams.py tests/engine/test_streams.py
git commit -m "feat: generalize capture_synced_frame_pair to arbitrary sensor groups"
```

---

### Task 5: `engine/streams.py` — emitter/exposure control functions + `ContinuousCapture`

**Files:**
- Modify: `engine/streams.py`
- Test: `tests/engine/test_streams.py`

**Interfaces:**
- Produces: `set_emitter_enabled(sensor, enabled: bool) -> bool`,
  `set_manual_exposure(sensor, exposure: int, gain: int) -> bool`,
  `ContinuousCapture(pick_a: dict, pick_b: dict)` with `.start()/.frames()/
  .frames_with_diagnostics()/.stop()`.

- [ ] **Step 1: Write the failing test**

```python
def test_set_emitter_enabled_true_when_supported():
    sensor = FakeOptionSensor(supported_options={rs.option.emitter_enabled})
    assert set_emitter_enabled(sensor, True) is True
    assert sensor.set_options[rs.option.emitter_enabled] == 1


def test_set_emitter_enabled_false_when_supported():
    sensor = FakeOptionSensor(supported_options={rs.option.emitter_enabled})
    assert set_emitter_enabled(sensor, False) is True
    assert sensor.set_options[rs.option.emitter_enabled] == 0


def test_set_emitter_enabled_returns_false_when_unsupported():
    sensor = FakeOptionSensor(supported_options=set())
    assert set_emitter_enabled(sensor, False) is False


def test_set_manual_exposure_sets_exposure_and_gain_and_disables_auto():
    sensor = FakeOptionSensor(supported_options={rs.option.enable_auto_exposure, rs.option.exposure, rs.option.gain})
    assert set_manual_exposure(sensor, exposure=150, gain=16) is True
    assert sensor.set_options[rs.option.enable_auto_exposure] == 0
    assert sensor.set_options[rs.option.exposure] == 150
    assert sensor.set_options[rs.option.gain] == 16
```

`FakeOptionSensor` already exists in this file's test suite (used for the existing
`enable_auto_exposure` tests) — reuse it, just add `rs.option.exposure`/`rs.option.gain`
to whichever fakes need them.

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
def set_emitter_enabled(sensor, enabled):
    if sensor.supports(rs.option.emitter_enabled):
        sensor.set_option(rs.option.emitter_enabled, 1 if enabled else 0)
        return True
    return False


def set_manual_exposure(sensor, exposure, gain):
    if not (sensor.supports(rs.option.enable_auto_exposure) and sensor.supports(rs.option.exposure) and sensor.supports(rs.option.gain)):
        return False
    sensor.set_option(rs.option.enable_auto_exposure, 0)
    sensor.set_option(rs.option.exposure, exposure)
    sensor.set_option(rs.option.gain, gain)
    return True
```

`ContinuousCapture` generalizes to:

```python
class ContinuousCapture:
    def __init__(self, pick_a, pick_b):
        self.pick_a = pick_a
        self.pick_b = pick_b
        self._pipeline = None

    def start(self):
        config = rs.config()
        for pick in (self.pick_a, self.pick_b):
            config.enable_stream(pick["stream_type"], pick["stream_index"], pick["width"], pick["height"], pick["format"], pick["fps"])
        self._pipeline = rs.pipeline()
        self._pipeline.start(config)

    def _get_frame(self, frameset, pick):
        if pick["stream_type"] == rs.stream.infrared:
            return frameset.get_infrared_frame(pick["stream_index"])
        return frameset.get_color_frame(pick["stream_index"])

    def frames(self):
        for stream_a_image, stream_b_image, stream_a_ts_us, stream_b_ts_us, _, _ in self.frames_with_diagnostics():
            yield stream_a_image, stream_b_image, stream_a_ts_us, stream_b_ts_us

    def frames_with_diagnostics(self):
        from domain.realsense_utils import decode_frame

        while True:
            frameset = self._pipeline.wait_for_frames()
            frame_a = self._get_frame(frameset, self.pick_a)
            frame_b = self._get_frame(frameset, self.pick_b)
            if not frame_a or not frame_b:
                continue

            metadata = rs.frame_metadata_value.frame_timestamp
            if not (frame_a.supports_frame_metadata(metadata) and frame_b.supports_frame_metadata(metadata)):
                raise RuntimeError(
                    "This camera/driver does not expose per-frame HW timestamp metadata "
                    "(frame_metadata_value.frame_timestamp), which the sync metrics require. "
                    "On Windows, RealSense per-frame metadata is often disabled by default at "
                    "the OS/driver level and needs a one-time enablement step (see Intel's "
                    "librealsense documentation on Windows metadata support) - reconnect the "
                    "camera after enabling it and retry."
                )

            image_a = decode_frame(bytes(frame_a.get_data()), self.pick_a["format"], self.pick_a["width"], self.pick_a["height"])
            image_b = decode_frame(bytes(frame_b.get_data()), self.pick_b["format"], self.pick_b["width"], self.pick_b["height"])
            ts_a = frame_a.get_frame_metadata(metadata)
            ts_b = frame_b.get_frame_metadata(metadata)
            num_a = frame_a.get_frame_number()
            num_b = frame_b.get_frame_number()

            yield image_a, image_b, ts_a, ts_b, num_a, num_b

    def stop(self):
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/streams.py tests/engine/test_streams.py
git commit -m "feat: add emitter/manual-exposure controls and generalize ContinuousCapture"
```

---

### Task 6: `engine/rgb_mode.py` — copy verbatim from `optical_sync_gui_d585`

**Files:**
- Create: `engine/rgb_mode.py` (copied, not written from scratch)
- Test: `tests/engine/test_rgb_mode.py` (copied)

- [ ] **Step 1: Copy both files unchanged**

```bash
cp /path/to/optical_sync_gui_d585/engine/rgb_mode.py engine/rgb_mode.py
cp /path/to/optical_sync_gui_d585/tests/engine/test_rgb_mode.py tests/engine/test_rgb_mode.py
```

No changes needed — this module is entirely about the D585/D535 firmware mode-switch
mechanism, which has nothing to do with which two streams the wizard lets you pick.

- [ ] **Step 2: Run the copied test**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_rgb_mode.py -v`
Expected: PASS (3 tests, unchanged from the D585 fork)

- [ ] **Step 3: Commit**

```bash
git add engine/rgb_mode.py tests/engine/test_rgb_mode.py
git commit -m "feat: reuse D585 Dedicated/Dual RGB firmware mode switching verbatim"
```

---

### Task 7: `engine/stream_preview_thread.py` — generic pick_a/pick_b preview

**Files:**
- Modify: `engine/stream_preview_thread.py`

**Interfaces:**
- Consumes: `engine.streams.ContinuousCapture(pick_a, pick_b)`,
  `get_color_sensor_for_device`-style sensor lookup — actually needs
  `resolve_and_group`/emitter/exposure setup done by the caller (Stream Select page),
  not by this thread itself; this thread's job is just streaming + overlay.
- Produces: `StreamPreviewThread(ctx, device_serial, pick_a, pick_b, display_stride=10, parent=None)`.

- [ ] **Step 1: Rewrite `engine/stream_preview_thread.py`**

```python
"""QThread wrapper for Stream Select's live pairing-quality preview:
streams the two picked streams continuously via ContinuousCapture, burns
a bundle/frame-number/timestamp/delta overlay onto Stream A's frame, and
prints the same info to the console."""

from PySide6.QtCore import QThread, Signal

from engine.streams import ContinuousCapture
from domain.realsense_utils import draw_bundle_overlay


class StreamPreviewThread(QThread):
    frame_ready = Signal(object)
    error = Signal(str)

    def __init__(self, ctx, device_serial, pick_a, pick_b, display_stride=10, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.device_serial = device_serial
        self.pick_a = pick_a
        self.pick_b = pick_b
        self.display_stride = display_stride
        self._stop_requested = False
        self._capture = None

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            self._capture = ContinuousCapture(self.pick_a, self.pick_b)
            self._capture.start()

            bundle_index = 0
            for image_a, image_b, ts_a, ts_b, num_a, num_b in self._capture.frames_with_diagnostics():
                if self._stop_requested:
                    break

                if bundle_index % self.display_stride == 0:
                    delta_us = ts_a - ts_b
                    print(
                        "Bundle {:>6} | Stream A Frame {:>6} | Stream B Frame {:>6} | "
                        "Stream A Timestamp {:>14.0f} | Stream B Timestamp {:>14.0f} | Delta {:>7.1f} us".format(
                            bundle_index, num_a, num_b, ts_a, ts_b, delta_us,
                        )
                    )
                    overlay_image = draw_bundle_overlay(image_a, bundle_index, num_a, num_b, ts_a, ts_b, delta_us)
                    self.frame_ready.emit(overlay_image)

                bundle_index += 1
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if self._capture is not None:
                self._capture.stop()
```

Note: emitter-disable/exposure-mode setup is now the caller's (Stream Select page's)
responsibility, applied once per distinct resolved sensor before starting the preview —
this thread no longer calls `disable_ir_emitter`/`enable_auto_exposure` itself, since
those are now user choices made earlier in the wizard, not hardcoded defaults this
lightweight preview thread should silently re-apply.

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing, matches project convention)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from engine.stream_preview_thread import StreamPreviewThread"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add engine/stream_preview_thread.py
git commit -m "feat: generalize stream preview thread to pick_a/pick_b"
```

---

### Task 8: `domain/realsense_utils.py` — decode dispatch + `draw_bundle_overlay` rename

**Files:**
- Modify: `domain/realsense_utils.py`
- Test: `tests/domain/test_realsense_utils.py`

**Interfaces:**
- Produces: `DECODERS: dict[rs.format, Callable]`, `decode_frame(raw_bytes, fmt, width,
  height) -> np.ndarray`, `draw_bundle_overlay(image, bundle_index,
  stream_a_frame_number, stream_b_frame_number, stream_a_ts_us, stream_b_ts_us, delta_us)`.

- [ ] **Step 1: Write the failing test**

```python
import pyrealsense2 as rs
from domain.realsense_utils import decode_frame, DECODERS, draw_bundle_overlay


def test_decode_frame_y8_reshapes_correctly():
    raw = bytes(range(6))  # 2x3, 1 byte/pixel
    image = decode_frame(raw, rs.format.y8, width=3, height=2)
    assert image.shape == (2, 3)
    assert image[0].tolist() == [0, 1, 2]


def test_decode_frame_bgr8_reshapes_correctly():
    raw = bytes(range(12))  # 2x2 bgr8, 3 bytes/pixel
    image = decode_frame(raw, rs.format.bgr8, width=2, height=2)
    assert image.shape == (2, 2, 3)


def test_decode_frame_yuyv_returns_bgr_shape():
    width, height = 4, 2
    raw = bytes([128] * (width * height * 2))
    image = decode_frame(raw, rs.format.yuyv, width, height)
    assert image.shape == (height, width, 3)


def test_decode_frame_raises_for_unsupported_format():
    import pytest
    with pytest.raises(RuntimeError):
        decode_frame(b"", rs.format.z16, width=4, height=4)


def test_draw_bundle_overlay_uses_stream_a_stream_b_naming():
    import numpy as np
    image = np.zeros((100, 300), dtype=np.uint8)
    result = draw_bundle_overlay(
        image, bundle_index=1, stream_a_frame_number=10, stream_b_frame_number=11,
        stream_a_ts_us=1000.0, stream_b_ts_us=1005.0, delta_us=-5.0,
    )
    assert result.shape == (100, 300, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_realsense_utils.py -v`
Expected: FAIL

- [ ] **Step 3: Modify `domain/realsense_utils.py`**

Remove `ir_bytes_to_image`/`yuyv_to_bgr`. Add the `DECODERS` dict and `decode_frame`
function exactly as specified in the design spec's `domain/realsense_utils.py` section
(covers y8, y16, yuyv, uyvy, bgr8, rgb8, bgra8, rgba8, mjpeg). Rename
`draw_bundle_overlay`'s params `ir_frame_number/color_frame_number/ir_ts_us/color_ts_us`
to `stream_a_frame_number/stream_b_frame_number/stream_a_ts_us/stream_b_ts_us`, and its
printed labels to "Stream A"/"Stream B". Everything else in the file is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_realsense_utils.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add domain/realsense_utils.py tests/domain/test_realsense_utils.py
git commit -m "feat: add format-driven decode dispatch, rename overlay to stream_a/stream_b"
```

---

### Task 9: `engine/metrics.py`, `engine/test_session.py`, `engine/acquisition_loop.py` — rename to `stream_a`/`stream_b`

**Files:**
- Modify: `engine/metrics.py`, `engine/test_session.py`, `engine/acquisition_loop.py`
- Test: `tests/engine/test_metrics.py`, `tests/engine/test_test_session.py`, `tests/engine/test_acquisition_loop.py`

**Interfaces:**
- Produces: `FramePairSample(pair_index, stream_a_ts_us, stream_b_ts_us,
  stream_a_bright=None, stream_b_bright=None)`, `PairingGapMetric(outlier_threshold_us)`,
  `PositionGapMetric(stream_a_threshold, stream_b_threshold, num_leds, switch_time_ms,
  stream_a_fps, stream_b_fps, frame_drop_threshold_factor, warmup_pairs_to_skip)` with
  `.last_stream_a_on_mask`/`.last_stream_b_on_mask`, `TestSession.process_pair()` rows
  keyed `stream_a_ts_us`/`stream_b_ts_us`, `AcquisitionCallbacks.on_frames(stream_a_image,
  stream_b_image, pair_index)`.

- [ ] **Step 1: Write the failing test files**

Mirror `optical_sync_gui_d585`'s already-rewritten `tests/engine/test_metrics.py`,
`tests/engine/test_test_session.py`, `tests/engine/test_acquisition_loop.py` line for
line, renaming `left_`/`right_` to `stream_a_`/`stream_b_` throughout (that fork already
proved this exact rename pattern works and every edge case it covers — wrap-around
position gap, warmup pairs, frame-drop flagging, last-on-mask tracking, stride
throttling, stop-request mid-stream, duration auto-stop).

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_metrics.py tests/engine/test_test_session.py tests/engine/test_acquisition_loop.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite the three implementation files**

Same rename `optical_sync_gui_d585` already applied (`ir_`/`rgb_` → `left_`/`right_`),
applied here as `ir_`/`rgb_` → `stream_a_`/`stream_b_` instead. `PairingGapMetric.update`'s
gap becomes `sample.stream_a_ts_us - sample.stream_b_ts_us`. Logic is otherwise identical.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_metrics.py tests/engine/test_test_session.py tests/engine/test_acquisition_loop.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/metrics.py engine/test_session.py engine/acquisition_loop.py \
        tests/engine/test_metrics.py tests/engine/test_test_session.py tests/engine/test_acquisition_loop.py
git commit -m "feat: rename ir/rgb to stream_a/stream_b in metrics, test session, acquisition loop"
```

---

### Task 10: `domain/calibration.py` + `config.yaml` — per-stream slug keys

**Files:**
- Modify: `domain/calibration.py`
- Test: `tests/domain/test_calibration.py`

**Interfaces:**
- Produces: `update_config_leds(config_path, camera_name, stream_a_slug,
  stream_a_positions, stream_a_res, stream_b_slug, stream_b_positions, stream_b_res)`,
  `load_led_positions(config_path, camera_name, stream_a_slug, stream_b_slug) ->
  (stream_a_positions, stream_b_positions)`.

- [ ] **Step 1: Write the failing test**

```python
def test_update_config_leds_writes_per_stream_slugs(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"leds": {"Other Camera": {"color": {}}}}))

    update_config_leds(
        str(config_path), camera_name="Test Camera",
        stream_a_slug="infrared1", stream_a_positions={"0": [1.0, 2.0, 255.0, 100.0, 177.5]}, stream_a_res=(1280, 720),
        stream_b_slug="color", stream_b_positions={"0": [3.0, 4.0, 250.0, 90.0, 170.0]}, stream_b_res=(1280, 720),
    )

    written = yaml.safe_load(config_path.read_text())
    assert "Other Camera" in written["leds"]  # untouched sibling block preserved
    assert written["leds"]["Test Camera"]["infrared1"]["positions"]["0"] == [1.0, 2.0, 255.0, 100.0, 177.5]
    assert written["leds"]["Test Camera"]["color"]["frame_width"] == 1280


def test_load_led_positions_returns_slug_keyed_dicts(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "leds": {"Test Camera": {
            "infrared1": {"positions": {"0": [1.0, 2.0, 255.0, 100.0, 177.5]}},
            "infrared2": {"positions": {"0": [3.0, 4.0, 250.0, 90.0, 170.0]}},
        }}
    }))
    stream_a_positions, stream_b_positions = load_led_positions(str(config_path), "Test Camera", "infrared1", "infrared2")
    assert stream_a_positions["0"] == [1.0, 2.0, 255.0, 100.0, 177.5]
    assert stream_b_positions["0"] == [3.0, 4.0, 250.0, 90.0, 170.0]


def test_load_led_positions_raises_for_uncalibrated_stream_pair(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"leds": {"Test Camera": {"color": {}}}}))
    with pytest.raises(KeyError):
        load_led_positions(str(config_path), "Test Camera", "infrared1", "infrared2")
```

`assign_grid_ids`/`build_positions_with_thresholds` tests carry over from the existing
suite unchanged (pure pixel math, no rename needed).

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_calibration.py -v`
Expected: FAIL

- [ ] **Step 3: Modify `domain/calibration.py`**

```python
def update_config_leds(config_path, camera_name, stream_a_slug, stream_a_positions, stream_a_res,
                        stream_b_slug, stream_b_positions, stream_b_res):
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("leds", {})
    cfg["leds"].setdefault(camera_name, {})
    cfg["leds"][camera_name][stream_a_slug] = {
        "frame_width": stream_a_res[0], "frame_height": stream_a_res[1], "positions": stream_a_positions,
    }
    cfg["leds"][camera_name][stream_b_slug] = {
        "frame_width": stream_b_res[0], "frame_height": stream_b_res[1], "positions": stream_b_positions,
    }
    with open(config_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


def load_led_positions(config_path, camera_name, stream_a_slug, stream_b_slug):
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)
    leds_by_camera = cfg.get("leds", {})
    camera_entry = leds_by_camera.get(camera_name, {})
    if stream_a_slug not in camera_entry or stream_b_slug not in camera_entry:
        raise KeyError(
            "No LED calibration yet for camera {!r} streams {!r}/{!r} - run calibration with "
            "this exact stream pair first.".format(camera_name, stream_a_slug, stream_b_slug)
        )
    return camera_entry[stream_a_slug]["positions"], camera_entry[stream_b_slug]["positions"]
```

Note `update_config_leds` uses `setdefault(camera_name, {})` rather than overwriting the
whole camera entry (unlike the original/D585 versions, which always replace the full
per-camera dict) — required now so that calibrating one stream pair on a camera doesn't
wipe out a different stream pair already calibrated for the same camera.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_calibration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add domain/calibration.py tests/domain/test_calibration.py
git commit -m "feat: key config.yaml LED calibration by per-stream slugs, not fixed ir/rgb"
```

---

### Task 11: `state/gui_state.py` + `settings.yaml` — stream-pick + camera-control persistence

**Files:**
- Modify: `state/gui_state.py`, `settings.yaml`
- Test: `tests/state/test_gui_state.py`

**Interfaces:**
- Produces: `GuiState` with `stream_a_type, stream_a_index, stream_a_width,
  stream_a_height, stream_a_fps, stream_a_roi, stream_a_emitter_enabled,
  stream_a_auto_exposure, stream_a_exposure, stream_a_gain` + the `stream_b_*` equivalents.

- [ ] **Step 1: Write the failing test**

```python
def test_save_then_load_round_trips_stream_picks_and_camera_controls(tmp_path):
    path = tmp_path / "gui_state.json"
    original = GuiState(
        device_serial="123456",
        stream_a_type="infrared", stream_a_index=1, stream_a_width=1280, stream_a_height=720,
        stream_a_fps=30, stream_a_roi=[10, 20, 100, 100],
        stream_a_emitter_enabled=False, stream_a_auto_exposure=True, stream_a_exposure=None, stream_a_gain=None,
        stream_b_type="color", stream_b_index=0, stream_b_width=1280, stream_b_height=720,
        stream_b_fps=30, stream_b_roi=[5, 15, 90, 90],
        stream_b_emitter_enabled=None, stream_b_auto_exposure=False, stream_b_exposure=150, stream_b_gain=16,
    )
    save_gui_state(original, str(path))
    loaded = load_gui_state(str(path))
    assert loaded == original
```

`test_load_gui_state_missing_file_returns_defaults`/`test_load_gui_state_ignores_corrupt_file`
carry over unchanged from the existing suite.

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/state/test_gui_state.py -v`
Expected: FAIL

- [ ] **Step 3: Modify `state/gui_state.py` and `settings.yaml`**

Add the fields listed in the Interfaces section above to `GuiState`. `load_gui_state`/
`save_gui_state` need zero code changes (already generic via `dataclasses.fields`/
`dataclasses.asdict`). In `settings.yaml`, rename the `camera:` block's `ir:`/`color:`
keys to `stream_a:`/`stream_b:` (each `{stream_type, stream_index, width, height, fps}`).

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/state/test_gui_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add state/gui_state.py settings.yaml tests/state/test_gui_state.py
git commit -m "feat: persist arbitrary stream picks and camera-control choices"
```

---

### Task 12: `gui/pages/device_select_page.py` — no rename needed, confirm and extend for mode-switch

**Files:**
- Modify: `gui/pages/device_select_page.py` (verify only — copy the D585 fork's mode-switch integration pattern)
- Test: `tests/gui/pages/test_device_select_page.py` (new, mirrors D585 fork's)

**Interfaces:**
- Consumes: `engine.rgb_mode.ensure_dual_rgb_mode`/`get_mode` (Task 6)
- Produces: `_device_label(device_info) -> str` (copy from D585 fork), device_chosen signal unchanged.

- [ ] **Step 1: Copy the D585 fork's device_select_page.py mode-switch integration pattern**

This project's Device Select has no ir_/rgb_ naming to rename (confirmed in the design
spec). Its only change is the same one the D585 fork made: show each device's
Dedicated/Dual RGB mode (via `engine.rgb_mode.get_mode`) and offer to switch it before
proceeding, using `ensure_dual_rgb_mode`. Copy that page's logic and its `_device_label`
test verbatim (see `optical_sync_gui_d585`'s `docs/superpowers/plans/
2026-07-28-d585-color-vs-color-fork.md` Task 8 for the exact code) — the only difference
here is that this generic project's device listing isn't restricted to D535/D585 PIDs the
way the D585 fork's `list_devices` was; keep this project's `list_devices` (Task 3) as the
generic any-device listing, and only *layer* the mode-switch offer on top when
`get_mode(device)` returns non-`None` (i.e. only for devices that actually have this
firmware quirk).

- [ ] **Step 2: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_device_select_page.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add gui/pages/device_select_page.py tests/gui/pages/test_device_select_page.py
git commit -m "feat: offer D585 mode switch in Device Select when applicable"
```

---

### Task 13: `gui/pages/stream_config_page.py` → Stream Select — two generic pickers + camera controls

**Files:**
- Modify: `gui/pages/stream_config_page.py` (rename file/class to `StreamSelectPage` if desired, or keep the name — the plan doesn't mandate a rename, just the behavior change)
- Test: `tests/gui/pages/test_stream_config_page.py`

**Interfaces:**
- Consumes: `engine.streams.list_video_stream_options`, `resolve_and_group`,
  `set_emitter_enabled`, `set_manual_exposure` (Tasks 2, 5)
- Produces: `.populate(ctx, device_serial, stream_options: list[dict], preferred_a=None,
  preferred_b=None)`, `.pick_a`/`.pick_b` (currently-selected dicts), `config_chosen`
  signal payload `(pick_a: dict, pick_b: dict, camera_controls: dict)` where
  `camera_controls` carries whatever emitter/exposure choices apply to each distinct
  resolved sensor.

- [ ] **Step 1: Write the failing test**

```python
def test_populate_lists_every_stream_option(qapp):
    page = StreamConfigPage()
    options = [
        {"sensor_index": 0, "stream_type": rs.stream.infrared, "stream_index": 1, "format": rs.format.y8, "width": 1280, "height": 720, "fps": 30},
        {"sensor_index": 0, "stream_type": rs.stream.infrared, "stream_index": 2, "format": rs.format.y8, "width": 1280, "height": 720, "fps": 30},
        {"sensor_index": 1, "stream_type": rs.stream.color, "stream_index": 0, "format": rs.format.bgr8, "width": 1280, "height": 720, "fps": 30},
    ]
    page.populate(ctx=None, device_serial="123", stream_options=options)
    assert page.combo_a.count() == 3
    assert page.combo_b.count() == 3


def test_selecting_streams_on_the_same_sensor_shows_one_camera_control_group(qapp):
    page = StreamConfigPage()
    shared = [
        {"sensor_index": 0, "stream_type": rs.stream.color, "stream_index": 1, "format": rs.format.bgr8, "width": 1280, "height": 720, "fps": 30},
        {"sensor_index": 0, "stream_type": rs.stream.color, "stream_index": 2, "format": rs.format.bgr8, "width": 1280, "height": 720, "fps": 30},
    ]
    page.populate(ctx=None, device_serial="123", stream_options=shared)
    page.combo_a.setCurrentIndex(0)
    page.combo_b.setCurrentIndex(1)
    page._refresh_camera_control_groups()  # recomputes resolve_and_group-based grouping for UI layout
    assert page.camera_control_group_count() == 1  # same sensor -> one control group, not two
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_stream_config_page.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite the page**

Two `QComboBox`es (Stream A, Stream B), each populated with one entry per option from
`list_video_stream_options`, labeled e.g. `"Infrared 1 - 1280x720@30fps (y8)"` /
`"Color - 1280x720@30fps (bgr8)"`, `userData` = the option dict. Once both are picked,
call a (fake-injectable, device-independent) grouping helper mirroring
`resolve_and_group`'s logic purely on the two picks' `sensor_index` values (same
sensor_index → one control group; different → two) to decide how many emitter/exposure
control groups to show — the real `resolve_and_group` (which needs a live `device`
handle) is only called later, at capture time in `gui/main_window.py`, not here. Each
control group: a checkbox "Disable IR emitter" (shown only if the group's streams include
Infrared) and a radio choice Auto/Manual exposure with two spin boxes (exposure, gain)
shown when Manual is selected. `config_chosen.emit((pick_a, pick_b, camera_controls))`
where `camera_controls` is a list of per-group choice dicts.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_stream_config_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gui/pages/stream_config_page.py tests/gui/pages/test_stream_config_page.py
git commit -m "feat: generalize Stream Select to any two picks plus camera controls"
```

---

### Task 14: `gui/pages/roi_select_page.py` — generic pick_a/pick_b capture

**Files:**
- Modify: `gui/pages/roi_select_page.py` (no test file — hardware-facing, matches project convention)

**Interfaces:**
- Consumes: `resolve_and_group`, `capture_synced_frame_pair`, `decode_frame` (Tasks 2, 4, 8)
- Produces: `RoiSelectPage.set_context(ctx, device_serial, pick_a, pick_b, camera_controls, settle_frames=15)`, `roi_chosen` signal payload `(stream_a_roi, stream_b_roi)`.

- [ ] **Step 1: Rewrite the page**

Resolve the device, call `resolve_and_group(device, pick_a, pick_b)`, apply
`camera_controls` (emitter/exposure) to each distinct sensor in the groups before
capturing, call `capture_synced_frame_pair(groups, on_both_streaming=turn_on_all_leds,
settle_frames=settle_frames)`, decode both frames via `decode_frame`, run
`cv2.selectROI` for each with a window title from a `stream_label(pick)` helper (e.g.
`"Infrared 1 - drag ROI, Enter=OK, C=Cancel"`).

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from gui.pages.roi_select_page import RoiSelectPage; RoiSelectPage()"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add gui/pages/roi_select_page.py
git commit -m "feat: adapt ROI Select page for generic stream-pair capture"
```

---

### Task 15: `gui/pages/calibration_page.py` — generic pick_a/pick_b calibration

**Files:**
- Modify: `gui/pages/calibration_page.py` (no test file — hardware-facing, matches project convention)

**Interfaces:**
- Consumes: same as Task 14, plus `domain.calibration.update_config_leds`/`stream_label` (Task 10)

- [ ] **Step 1: Rewrite the page**

Same capture/decode adaptation as ROI Select. Debug detection image filenames become
`debug_stream_a_detection.png`/`debug_stream_b_detection.png` (or, better, incorporate the
actual slug, e.g. `debug_infrared1_detection.png`, since with per-stream calibration keys
now possible, filenames that reflect the real stream identity avoid ambiguity across
different stream-pair runs on the same camera). `update_config_leds(...)` called with
each stream's slug (computed via a small `stream_slug(pick) -> str` helper in
`engine/streams.py`, e.g. `f"{pick['stream_type'].name}{pick['stream_index'] or ''}"`).

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from gui.pages.calibration_page import CalibrationPage; CalibrationPage()"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add gui/pages/calibration_page.py
git commit -m "feat: adapt Calibration page for generic stream-pair capture and slug-keyed config"
```

---

### Task 16: `engine/session_engine.py` — generic live-session hardware thread

**Files:**
- Modify: `engine/session_engine.py` (no test file — hardware-facing, matches project convention)

**Interfaces:**
- Produces: `SessionEngineThread(ctx, device_serial, pick_a, pick_b, camera_controls,
  test_session, stream_a_xy=None, stream_b_xy=None, neighborhood_size=5,
  scan_direction=None, switch_time_ms=None, display_stride=10, position_gap_metric=None,
  parent=None)`. `frame_ready` signal emits `"stream_a"`/`"stream_b"` as `stream_name`.

- [ ] **Step 1: Rewrite `engine/session_engine.py`**

Resolve the device once at `run()` start via `resolve_and_group`, apply
`camera_controls`, construct `ContinuousCapture(pick_a, pick_b)`, and otherwise keep the
exact same `AcquisitionLoop`/`TestSession` wiring both existing projects already use,
renamed `ir_`/`rgb_` → `stream_a_`/`stream_b_` throughout (mirrors the D585 fork's Task 12
rename exactly, one more name-swap applied).

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from engine.session_engine import SessionEngineThread"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add engine/session_engine.py
git commit -m "feat: generalize session engine thread to pick_a/pick_b"
```

---

### Task 17: `gui/pages/live_session_page.py` — generic stream_a/stream_b rename

**Files:**
- Modify: `gui/pages/live_session_page.py`
- Test: `tests/gui/pages/test_live_session_page.py`

**Interfaces:**
- Produces: `LiveSessionPage.set_context(ctx, device_serial, pick_a, pick_b,
  camera_controls, switch_time_ms, scan_direction, stream_a_threshold,
  stream_b_threshold, stream_a_xy, stream_b_xy, num_leds, neighborhood_size,
  frame_drop_threshold_factor, warmup_pairs_to_skip, pairing_gap_outlier_threshold_us,
  kept_csv_path, dropped_csv_path, output_dir, snapshot_every_n_pairs, max_snapshots,
  stream_a_roi, stream_b_roi, camera_name, stream_a_label, stream_b_label)` — the last two
  (`stream_a_label`/`stream_b_label`) are new: precomputed human-readable labels (e.g.
  `"Infrared 1"`, `"Color"`) from `stream_label(pick)`, passed in rather than derived
  inside this page, since this page has no access to `pick_a`/`pick_b`'s raw dicts by the
  time `set_context` is usually called in the existing two projects' equivalent pages
  (confirm this against how `gui/main_window.py` actually wires it in Task 18 — pass
  whichever is more convenient there).

- [ ] **Step 1: Write the failing test**

Mirror the D585 fork's already-rewritten `tests/gui/pages/test_live_session_page.py`
line for line (same 15 tests: `_short_camera_name`, periodic-snapshot save/skip/cap
behavior, ROI-crop behavior, toolbar switch-time/frame-sample-interval wiring), renaming
`left_`/`right_` to `stream_a_`/`stream_b_` throughout, plus updating `_minimal_context`'s
fixture dict to include the two new `stream_a_label`/`stream_b_label` kwargs.

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_live_session_page.py -v`
Expected: FAIL

- [ ] **Step 3: Apply the rename throughout the file**

Same exhaustive rename table the D585 fork's Task 13 applied (`ir_`/`rgb_` →
`left_`/`right_`), applied here as `ir_`/`rgb_` → `stream_a_`/`stream_b_` instead —
video panel titles use `stream_a_label`/`stream_b_label` (passed in via `set_context`,
not derived from `camera_name` alone the way `_short_camera_name` does today, since the
stream identity is now independent of the camera model). Checkbox/plot/stat-tile labels,
snapshot filenames, frame-drop counters all follow the same pattern.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_live_session_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gui/pages/live_session_page.py tests/gui/pages/test_live_session_page.py
git commit -m "feat: rename Live Session page to stream_a/stream_b with dynamic labels"
```

---

### Task 18: `gui/main_window.py` — rewire the whole wizard

**Files:**
- Modify: `gui/main_window.py` (no test file — top-level hardware-facing wiring, matches project convention)

**Interfaces:**
- Consumes: every renamed page's `populate`/`set_context` signature (Tasks 12-17),
  `resolve_and_group`, `set_emitter_enabled`/`set_manual_exposure`,
  `stream_slug`/`stream_label` helpers (Tasks 2, 5, 10)

- [ ] **Step 1: Rewrite `gui/main_window.py`**

`_on_device_chosen`: call `list_video_stream_options(ctx, serial)` instead of
`get_sensors_for_device`; pass the flat option list plus `settings["camera"]["stream_a"]`/
`["stream_b"]` preferred defaults to `stream_config_page.populate(...)`.
`_on_config_chosen`: receive `(pick_a, pick_b, camera_controls)` from `config_chosen`;
persist each pick's full identity (`stream_a_type`, `stream_a_index`, `stream_a_width`,
etc.) plus `camera_controls` fields into `GuiState`; call `roi_page.set_context(ctx,
device_serial, pick_a, pick_b, camera_controls, settle_frames=...)`.
`_on_roi_chosen`/`_on_calibration_done`: same destructure-and-rewire pattern as the
D585 fork's Task 14, renamed to `stream_a_`/`stream_b_`, with `camera_name` +
`stream_slug(pick_a)`/`stream_slug(pick_b)` used for `load_led_positions`/
`update_config_leds` calls, and the LED-count-mismatch warning message using
`stream_label(pick_a)`/`stream_label(pick_b)` instead of literal "IR"/"RGB" text.

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing top-level wiring)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from gui.main_window import MainWindow"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add gui/main_window.py
git commit -m "feat: rewire MainWindow for generic stream-pair wizard flow"
```

---

### Task 19: Docs — `CLAUDE.md` and `README.md`

**Files:**
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Rewrite `CLAUDE.md`**

Describe the stream-a/stream-b wizard-choice architecture, the `resolve_and_group`
same-sensor-vs-different-sensor unification (with the Mermaid diagram from the design
spec, or a prose equivalent), the camera-control options (emitter/exposure, shown once
per distinct resolved sensor), and reference `optical_sync_gui`/`optical_sync_gui_d585`
as the two topologies this project subsumes rather than forks. Describe the per-stream
`config.yaml` slug keying and why it's simpler than a joined pair-key.

- [ ] **Step 2: Rewrite `README.md`**

Update the feature list, prerequisites, and wizard walkthrough to describe picking any
two streams instead of a fixed IR/RGB pair — Stream Select's two pickers, the
camera-control options, and that ROI Select/Calibration/Live Session all adapt to
whichever two streams were picked.

- [ ] **Step 3: Full test suite sanity check**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -v`
Expected: PASS (all tests — docs changes don't affect test collection).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: rewrite CLAUDE.md and README.md for generic stream-pair architecture"
```

---

### Task 20: Final full-suite verification + real-hardware open risks

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test suite from a clean venv**

```bash
rm -rf .venv
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -v
```

Expected: PASS (every test across `tests/domain/`, `tests/engine/`, `tests/state/`,
`tests/gui/`).

- [ ] **Step 2: Grep for any remaining `ir_`/`rgb_` leftovers**

```bash
grep -rn "ir_\|rgb_\|_ir\b\|_rgb\b" --include="*.py" --include="*.yaml" . \
  | grep -v ".git/" | grep -v "\.venv/" | grep -v "pair_" | grep -v "rgb_mode"
```

Expected: no matches (the `pair_` and `rgb_mode` exclusions are known false-positive
sources per the D585 fork's own Task 16 — `pair_index` contains the substring `ir_`, and
`rgb_mode`/`ensure_dual_rgb_mode` name the D585 firmware concept, not stream naming).

- [ ] **Step 3: Manual hardware verification (the actual proof of genericity)**

Against real devices (this is the step this docs-only planning pass could not perform):

1. A D400-series device (D435/D455): pick Infrared vs. Color — confirm it behaves
   equivalently to `optical_sync_gui`'s hardcoded IR-vs-RGB flow.
2. The same D400-series device: pick Infrared (index 1) vs. Infrared (index 2) — the
   stereo module's own two imagers, a combination neither existing project supports today.
3. A D585/D535 in Dual RGB mode: pick Color (index 1) vs. Color (index 2) — confirm it
   behaves equivalently to `optical_sync_gui_d585`'s hardcoded color-vs-color flow.

All three must work via different Stream Select picks in the **same, unmodified** app —
this is the concrete proof the genericity goal was met. Resolve the design spec's three
"Open risks" (stream discovery correctly reflecting the D585's current firmware mode;
`get_infrared_frame`/`get_color_frame` behaving correctly for same-`stream_type` picks;
manual-exposure ranges via `get_option_range` rather than a hardcoded slider range)
during this pass, updating `engine/streams.py`/the Stream Select page as needed if any
assumption doesn't hold.

- [ ] **Step 4: Commit any fixes found during hardware verification**

```bash
git add -A
git commit -m "fix: address findings from real-hardware verification pass"
```

If Step 3 found nothing needing a fix, no commit is needed here.
