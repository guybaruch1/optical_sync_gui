# D585 Color-vs-Color Fork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fork `optical_sync_gui` into a new sibling project, `optical_sync_gui_d585`, that measures optical sync between the Intel RealSense D585's two on-device color sensors (left = stream index 1, right = stream index 2, via its Dual RGB firmware mode) instead of IR vs RGB.

**Architecture:** Same 5-step wizard (Device Select → Stream Config → ROI Select → Calibration → Live Session), same `domain`/`engine`/`gui`/`state` layering. Every `ir_`/`rgb_` name becomes `left_`/`right_`. A new `engine/rgb_mode.py` module handles the Dedicated↔Dual RGB firmware mode switch (debug-protocol register write + `hardware_reset()`), invoked from Device Select. `capture_synced_frame_pair` (Calibration/ROI Select) opens ONE color sensor with two stream-index profiles instead of two separate sensor objects; `ContinuousCapture` (Live Session/Stream Config preview) keeps using `rs.pipeline()`, just with color index 1+2 instead of infrared+color.

**Tech Stack:** Python 3.10+, PySide6, pyrealsense2, opencv-python, numpy, pyyaml, pyqtgraph, matplotlib, pytest.

## Global Constraints

- Full spec: `docs/superpowers/specs/2026-07-28-d585-color-vs-color-fork-design.md` (this repo, committed).
- Reference for D585 mechanics: `C:\Users\gbaruch\scripts\TS_Sync\d585_dual_rgb_mode.py`.
- New project root: `C:\Users\gbaruch\scripts\Optical Sync\optical_sync_gui_d585` (sibling of the current repo, fresh git history).
- Naming: **left**/**right** everywhere `ir`/`rgb` appears today (variables, params, `config.yaml` keys, CSV columns, UI labels). No `ir_`/`rgb_` names survive in the fork.
- Color format: `rs.format.bgr8` for both streams (matches `d585_dual_rgb_mode.py`'s default; directly OpenCV-compatible, no conversion step).
- Every task's tests must pass with `QT_QPA_PLATFORM=offscreen` and no hardware connected (this project's existing convention — see its `CLAUDE.md`).
- Hardware-facing modules (`engine/rgb_mode.py`'s `switch_mode`/`wait_for_reenumeration`/`ensure_dual_rgb_mode`, `engine/session_engine.py`, `gui/pages/roi_select_page.py`, `gui/pages/calibration_page.py`, `engine/stream_preview_thread.py`, `gui/main_window.py`) stay untested by design, matching this project's existing convention for `engine/session_engine.py`/`engine/led_panel.py` — only their pure sub-parts (e.g. `engine/rgb_mode.get_mode`, `gui/pages/device_select_page._device_label`) get unit tests.

---

### Task 1: Fork the repository into a new sibling directory

**Files:**
- Create: `C:\Users\gbaruch\scripts\Optical Sync\optical_sync_gui_d585\` (full copy of the current tree)
- Modify: `config.yaml` (reset to `leds: {}` — no carried-over D435/D415/D455 calibration data)

- [ ] **Step 1: Copy the tree, excluding build/VCS artifacts**

```bash
SRC="/c/Users/gbaruch/scripts/Optical Sync/optical_sync_gui"
DST="/c/Users/gbaruch/scripts/Optical Sync/optical_sync_gui_d585"
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
cd "/c/Users/gbaruch/scripts/Optical Sync/optical_sync_gui_d585"
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -v
```

Expected: all tests PASS (this is still the unmodified IR/RGB codebase at this point — a baseline check that the copy itself is sound before any renames begin).

- [ ] **Step 4: git init and first commit**

```bash
git init
git add -A
git commit -m "Initial import: fork of optical_sync_gui for D585 color-vs-color sync testing"
```

---

### Task 2: `engine/rgb_mode.py` — D585 Dedicated/Dual RGB firmware mode switching

**Files:**
- Create: `engine/rgb_mode.py`
- Test: `tests/engine/test_rgb_mode.py`

**Interfaces:**
- Produces: `DUAL_RGB_PIDS: set[str]`, `DEDICATED_RGB_PIDS: set[str]`, `get_mode(device) -> "dual" | "dedicated" | None`, `switch_mode(device, target_mode) -> str`, `wait_for_reenumeration(ctx, serial, timeout_s=15) -> device`, `ensure_dual_rgb_mode(ctx, device) -> device`.

- [ ] **Step 1: Write the failing test (the only pure part of this module)**

```python
# tests/engine/test_rgb_mode.py
from engine.rgb_mode import get_mode


class FakeDevice:
    def __init__(self, pid):
        self._pid = pid

    def get_info(self, info):
        return self._pid


def test_get_mode_returns_dual_for_dual_pid():
    assert get_mode(FakeDevice("0C04")) == "dual"


def test_get_mode_returns_dedicated_for_dedicated_pid():
    assert get_mode(FakeDevice("0C05")) == "dedicated"


def test_get_mode_returns_none_for_unrecognized_pid():
    assert get_mode(FakeDevice("FFFF")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_rgb_mode.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.rgb_mode'`

- [ ] **Step 3: Implement `engine/rgb_mode.py`**

```python
"""D585/D535 Dedicated-RGB <-> Dual-RGB firmware mode switching.

Ported from the standalone d585_dual_rgb_mode.py script (mechanism
verified against real D585 hardware). Mode is identified by USB product
ID (PID), not device name - see librealsense's d500-factory.cpp /
d500-private.h for the PID tables.

get_mode() is pure (a PID lookup) and unit-tested. switch_mode()/
wait_for_reenumeration()/ensure_dual_rgb_mode() talk to real hardware
(debug-protocol register write + hardware_reset(), which disconnects/
reconnects the device over USB) and are untested by design, the same
convention this project already uses for engine/session_engine.py and
engine/led_panel.py.
"""

import time

import pyrealsense2 as rs

MWD_OPCODE = 0x02
MODE_REG_START_ADDR = 0x80000064
MODE_REG_END_ADDR = 0x80000068
MODE_DEDICATED_RGB = 0
MODE_DUAL_RGB = 1

DUAL_RGB_PIDS = {"0C01", "0C04", "0C07"}
DEDICATED_RGB_PIDS = {"0C02", "0C05", "0C08"}

REENUMERATION_TIMEOUT_S = 15
REENUMERATION_POLL_INTERVAL_S = 0.5


def get_mode(device):
    """Returns 'dual', 'dedicated', or None (PID not recognized as either)."""
    pid = device.get_info(rs.camera_info.product_id)
    if pid in DUAL_RGB_PIDS:
        return "dual"
    if pid in DEDICATED_RGB_PIDS:
        return "dedicated"
    return None


def switch_mode(device, target_mode):
    """Writes the mode register via debug protocol, hardware-resets the
    device, and returns the serial number to re-enumerate against."""
    if not device.supports(rs.camera_info.product_id):
        raise RuntimeError("Device does not report a product ID - cannot determine RGB mode.")
    if not device.is_debug_protocol():
        raise RuntimeError("Device does not support the debug protocol - cannot switch RGB mode.")

    serial = device.get_info(rs.camera_info.serial_number)
    value = MODE_DUAL_RGB if target_mode == "dual" else MODE_DEDICATED_RGB
    data = [
        value & 0xFF,
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF,
    ]

    dp = device.as_debug_protocol()
    cmd = dp.build_command(MWD_OPCODE, MODE_REG_START_ADDR, MODE_REG_END_ADDR, 0, 0, data)
    dp.send_and_receive_raw_data(cmd)
    device.hardware_reset()

    return serial


def wait_for_reenumeration(ctx, serial, timeout_s=REENUMERATION_TIMEOUT_S):
    """Polls rs.context() until a device with the given serial number
    reappears (the PID may have changed - that's expected)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for dev in ctx.query_devices():
            if dev.get_info(rs.camera_info.serial_number) == serial:
                return dev
        time.sleep(REENUMERATION_POLL_INTERVAL_S)
    raise RuntimeError(
        "Device {!r} did not re-enumerate within {}s after hardware reset.".format(serial, timeout_s)
    )


def ensure_dual_rgb_mode(ctx, device):
    """Checks the device's current RGB mode and switches it to Dual RGB if
    it's currently Dedicated. Returns a device handle guaranteed to be in
    Dual RGB mode (possibly re-enumerated, if a switch happened)."""
    mode = get_mode(device)
    if mode is None:
        pid = device.get_info(rs.camera_info.product_id)
        raise RuntimeError(
            "Product ID {!r} is not a recognized D535/D585 Dual/Dedicated RGB variant.".format(pid)
        )
    if mode == "dual":
        return device

    serial = switch_mode(device, "dual")
    new_device = wait_for_reenumeration(ctx, serial)

    new_mode = get_mode(new_device)
    if new_mode != "dual":
        new_pid = new_device.get_info(rs.camera_info.product_id)
        raise RuntimeError(
            "Mode switch did not take effect - device re-enumerated with PID={!r} "
            "(expected a Dual RGB PID).".format(new_pid)
        )
    return new_device
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_rgb_mode.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/rgb_mode.py tests/engine/test_rgb_mode.py
git commit -m "feat: add D585 Dedicated/Dual RGB firmware mode switching"
```

---

### Task 3: `engine/streams.py` — left/right color stream + capture helpers

**Files:**
- Modify: `engine/streams.py` (full rewrite)
- Test: `tests/engine/test_streams.py` (full rewrite)

**Interfaces:**
- Consumes: `engine.rgb_mode.get_mode` (Task 2)
- Produces: `DeviceInfo(name, serial, mode)`, `list_devices(ctx) -> list[DeviceInfo]`, `find_device_by_serial(ctx, serial) -> device`, `get_color_sensor_for_device(ctx, serial) -> sensor`, `list_supported_profiles(sensor, stream_type, fmt, stream_index) -> list[(w,h,fps)]`, `match_profile(sensor, stream_type, fmt, width, height, fps, stream_index) -> profile`, `capture_synced_frame_pair(color_sensor, left_profile, right_profile, on_both_streaming=None, settle_frames=15, timeout_s=10.0) -> (left_bytes, right_bytes)`, `enable_auto_exposure(sensor) -> bool`, `ContinuousCapture(left_resolution, left_fps, right_resolution, right_fps)`.

- [ ] **Step 1: Write the failing test file**

```python
# tests/engine/test_streams.py
import threading
import time

import pytest
import pyrealsense2 as rs
from engine.streams import (
    list_supported_profiles, match_profile, capture_synced_frame_pair, enable_auto_exposure,
    find_device_by_serial,
)


class FakeOptionSensor:
    def __init__(self, supported_options):
        self._supported_options = set(supported_options)
        self.set_options = {}

    def supports(self, option):
        return option in self._supported_options

    def set_option(self, option, value):
        self.set_options[option] = value


def test_enable_auto_exposure_sets_option_on_when_supported():
    sensor = FakeOptionSensor(supported_options={rs.option.enable_auto_exposure})
    assert enable_auto_exposure(sensor) is True
    assert sensor.set_options[rs.option.enable_auto_exposure] == 1


def test_enable_auto_exposure_returns_false_when_unsupported():
    sensor = FakeOptionSensor(supported_options=set())
    assert enable_auto_exposure(sensor) is False
    assert sensor.set_options == {}


class FakeVideoProfile:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeProfile:
    def __init__(self, stream_type, fmt, width, height, fps, stream_index):
        self._stream_type = stream_type
        self._fmt = fmt
        self._fps = fps
        self._stream_index = stream_index
        self._video = FakeVideoProfile(width, height)

    def stream_type(self):
        return self._stream_type

    def format(self):
        return self._fmt

    def fps(self):
        return self._fps

    def stream_index(self):
        return self._stream_index

    def as_video_stream_profile(self):
        return self._video


class FakeSensor:
    def __init__(self, profiles):
        self.profiles = profiles


def test_list_supported_profiles_filters_by_stream_format_and_index():
    sensor = FakeSensor(profiles=[
        FakeProfile("color", "bgr8", 1280, 720, 30, stream_index=1),
        FakeProfile("color", "bgr8", 640, 480, 60, stream_index=1),
        FakeProfile("color", "bgr8", 1280, 720, 30, stream_index=2),
    ])
    result = list_supported_profiles(sensor, "color", "bgr8", stream_index=1)
    assert set(result) == {(1280, 720, 30), (640, 480, 60)}


def test_match_profile_finds_exact_match_for_the_given_stream_index():
    target = FakeProfile("color", "bgr8", 1280, 720, 30, stream_index=2)
    sensor = FakeSensor(profiles=[
        FakeProfile("color", "bgr8", 1280, 720, 30, stream_index=1),
        target,
    ])
    matched = match_profile(sensor, "color", "bgr8", 1280, 720, 30, stream_index=2)
    assert matched is target


def test_match_profile_raises_when_nothing_matches():
    sensor = FakeSensor(profiles=[FakeProfile("color", "bgr8", 640, 480, 60, stream_index=1)])
    with pytest.raises(RuntimeError):
        match_profile(sensor, "color", "bgr8", 1280, 720, 30, stream_index=1)


class FakeRsDevice:
    def __init__(self, serial):
        self._serial = serial

    def get_info(self, info):
        return self._serial


class FakeRsContext:
    def __init__(self, devices):
        self._devices = devices

    def query_devices(self):
        return self._devices


def test_find_device_by_serial_returns_matching_device():
    target = FakeRsDevice("222")
    ctx = FakeRsContext([FakeRsDevice("111"), target])
    assert find_device_by_serial(ctx, "222") is target


def test_find_device_by_serial_raises_when_not_found():
    ctx = FakeRsContext([FakeRsDevice("111")])
    with pytest.raises(RuntimeError):
        find_device_by_serial(ctx, "999")


class _FakeFrame:
    def __init__(self, stream_index, data):
        self._stream_index = stream_index
        self._data = data

    def get_profile(self):
        return self

    def stream_index(self):
        return self._stream_index

    def get_data(self):
        return self._data


class _FakeStreamingColorSensor:
    """Delivers frames for BOTH stream indices continuously on a
    background thread once started, like the real shared color sensor -
    unlike a synchronous fake, this doesn't deliver everything before
    capture_synced_frame_pair's counter reset happens, so it actually
    exercises the reset-then-wait-for-fresh-frames control flow."""

    def __init__(self):
        self._running = False
        self._thread = None

    def open(self, profiles):
        pass

    def start(self, callback):
        self._running = True

        def deliver_loop():
            counter = 0
            while self._running:
                counter += 1
                callback(_FakeFrame(1, "left-{}".format(counter).encode()))
                callback(_FakeFrame(2, "right-{}".format(counter).encode()))
                time.sleep(0.001)

        self._thread = threading.Thread(target=deliver_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def close(self):
        pass


class _FakeNonDeliveringSensor:
    def open(self, profiles):
        pass

    def start(self, callback):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def test_capture_synced_frame_pair_calls_trigger_once_and_returns_frames():
    color_sensor = _FakeStreamingColorSensor()
    triggered = {"count": 0}

    def on_both_streaming():
        triggered["count"] += 1

    left_frame, right_frame = capture_synced_frame_pair(
        color_sensor, None, None,
        on_both_streaming=on_both_streaming, settle_frames=5, timeout_s=5.0,
    )

    assert triggered["count"] == 1
    assert left_frame is not None
    assert right_frame is not None


def test_capture_synced_frame_pair_works_without_a_trigger_callback():
    color_sensor = _FakeStreamingColorSensor()

    left_frame, right_frame = capture_synced_frame_pair(
        color_sensor, None, None, on_both_streaming=None, settle_frames=5, timeout_s=5.0,
    )

    assert left_frame is not None
    assert right_frame is not None


def test_capture_synced_frame_pair_raises_on_timeout_when_no_frames_arrive():
    color_sensor = _FakeNonDeliveringSensor()

    with pytest.raises(RuntimeError):
        capture_synced_frame_pair(color_sensor, None, None, settle_frames=5, timeout_s=0.2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: FAIL (`list_supported_profiles`/`match_profile` still take the old signature without `stream_index`; `find_device_by_serial` doesn't exist yet).

- [ ] **Step 3: Rewrite `engine/streams.py`**

```python
"""Hardware-facing RealSense device/sensor helpers for the D585's Dual RGB
(left/right color stream) topology.

Both color streams here come off ONE sensor object (two stream indices:
1=left, 2=right), unlike a Dedicated-RGB device's separate Stereo
Module/RGB Camera sensors - so capture_synced_frame_pair opens one
sensor with two profiles instead of two sensors with one profile each,
keyed by stream_index() instead of stream_type() (both frames report
stream_type()==COLOR here).

ContinuousCapture uses rs.pipeline() (proven for continuous streaming);
capture_synced_frame_pair uses the raw per-sensor open/start/callback
mechanism (proven for one-shot settled-frame capture in Calibration/ROI
Select - see those pages' own comments for why rs.pipeline() was
deliberately avoided there before, on the original IR-vs-RGB codebase
this was forked from).
"""

import time
from dataclasses import dataclass

import pyrealsense2 as rs

from engine.rgb_mode import get_mode


@dataclass
class DeviceInfo:
    name: str
    serial: str
    mode: str  # "dual" or "dedicated" - see engine.rgb_mode.get_mode


def list_devices(ctx):
    devices = []
    for d in ctx.query_devices():
        mode = get_mode(d)
        if mode is None:
            continue
        devices.append(DeviceInfo(
            name=d.get_info(rs.camera_info.name),
            serial=d.get_info(rs.camera_info.serial_number),
            mode=mode,
        ))
    return devices


def find_device_by_serial(ctx, serial):
    for d in ctx.query_devices():
        if d.get_info(rs.camera_info.serial_number) == serial:
            return d
    raise RuntimeError("No connected device with serial {!r}".format(serial))


def get_color_sensor_for_device(ctx, serial):
    """Returns the single sensor exposing both color stream indices (1 and
    2) - in Dual RGB mode, both live on one sensor object, not two."""
    device = find_device_by_serial(ctx, serial)
    for sensor in device.query_sensors():
        indices = {p.stream_index() for p in sensor.profiles if p.stream_type() == rs.stream.color}
        if {1, 2}.issubset(indices):
            return sensor
    raise RuntimeError(
        "No sensor on device {!r} exposes both color stream index 1 and 2 - "
        "is it actually in Dual RGB mode?".format(serial)
    )


def list_supported_profiles(sensor, stream_type, fmt, stream_index):
    results = set()
    for p in sensor.profiles:
        if p.stream_type() != stream_type or p.format() != fmt or p.stream_index() != stream_index:
            continue
        vp = p.as_video_stream_profile()
        results.add((vp.width(), vp.height(), p.fps()))
    return sorted(results)


def match_profile(sensor, stream_type, fmt, width, height, fps, stream_index):
    for p in sensor.profiles:
        vp = p.as_video_stream_profile()
        if (
            p.stream_type() == stream_type
            and p.format() == fmt
            and p.stream_index() == stream_index
            and vp.width() == width
            and vp.height() == height
            and p.fps() == fps
        ):
            return p
    raise RuntimeError(
        "No matching profile for {} index={} {}x{}@{}fps ({})".format(
            stream_type, stream_index, width, height, fps, fmt
        )
    )


def capture_synced_frame_pair(
    color_sensor, left_profile, right_profile,
    on_both_streaming=None, settle_frames=15, timeout_s=10.0,
):
    """
    Opens ONE color sensor with both stream-index profiles (left=index 1,
    right=index 2), keyed by frame.get_profile().stream_index() instead of
    stream_type() (both frames report stream_type()==COLOR here).

    Flow: open both profiles on the one sensor, start, wait until both
    indices are confirmed streaming, trigger on_both_streaming, reset
    counters, wait for settle_frames fresh frames per index, stop+close.

    Returns (left_bytes, right_bytes) - both bgr8 raw bytes; caller
    converts with domain.realsense_utils.color_bytes_to_image.
    """
    state = {
        1: {"count": 0, "frame": None},
        2: {"count": 0, "frame": None},
    }

    def callback(frame):
        stream_index = frame.get_profile().stream_index()
        if stream_index not in state:
            return
        s = state[stream_index]
        s["count"] += 1
        s["frame"] = bytes(frame.get_data())

    color_sensor.open([left_profile, right_profile])
    color_sensor.start(callback)

    def wait_until(predicate, label):
        start = time.time()
        while not predicate():
            elapsed = time.time() - start
            if elapsed > timeout_s:
                color_sensor.stop(); color_sensor.close()
                raise RuntimeError(
                    "Timed out ({}) - left={} right={} frames received in {}s".format(
                        label, state[1]["count"], state[2]["count"], timeout_s,
                    )
                )
            time.sleep(0.05)

    wait_until(
        lambda: state[1]["count"] >= 1 and state[2]["count"] >= 1,
        "waiting for initial frames",
    )

    if on_both_streaming is not None:
        on_both_streaming()

    state[1]["count"] = 0
    state[2]["count"] = 0
    wait_until(
        lambda: state[1]["count"] >= settle_frames and state[2]["count"] >= settle_frames,
        "waiting for post-trigger settled frames",
    )

    left_frame = state[1]["frame"]
    right_frame = state[2]["frame"]

    color_sensor.stop(); color_sensor.close()

    return left_frame, right_frame


def enable_auto_exposure(sensor):
    """Returns True/False so callers can warn the operator when the sensor
    doesn't support the option instead of silently proceeding with
    auto-exposure left however it was."""
    if sensor.supports(rs.option.enable_auto_exposure):
        sensor.set_option(rs.option.enable_auto_exposure, 1)
        return True
    return False


class ContinuousCapture:
    """Open-ended left+right color capture via rs.pipeline() - enables
    color stream index 1+2 instead of infrared+color."""

    def __init__(self, left_resolution, left_fps, right_resolution, right_fps):
        self.left_resolution = left_resolution
        self.left_fps = left_fps
        self.right_resolution = right_resolution
        self.right_fps = right_fps
        self._pipeline = None

    def start(self):
        config = rs.config()
        config.enable_stream(rs.stream.color, 1, *self.left_resolution, rs.format.bgr8, self.left_fps)
        config.enable_stream(rs.stream.color, 2, *self.right_resolution, rs.format.bgr8, self.right_fps)
        self._pipeline = rs.pipeline()
        self._pipeline.start(config)

    def frames(self):
        for left_image, right_image, left_ts_us, right_ts_us, _, _ in self.frames_with_diagnostics():
            yield left_image, right_image, left_ts_us, right_ts_us

    def frames_with_diagnostics(self):
        """Like frames(), but also yields each stream's own HW frame-number
        counter - used by Stream Config's live pairing-quality preview."""
        from domain.realsense_utils import color_bytes_to_image

        while True:
            frameset = self._pipeline.wait_for_frames()
            left_frame = frameset.get_color_frame(1)
            right_frame = frameset.get_color_frame(2)
            if not left_frame or not right_frame:
                continue

            metadata = rs.frame_metadata_value.frame_timestamp
            if not (left_frame.supports_frame_metadata(metadata) and right_frame.supports_frame_metadata(metadata)):
                raise RuntimeError(
                    "This camera/driver does not expose per-frame HW timestamp metadata "
                    "(frame_metadata_value.frame_timestamp), which the sync metrics require."
                )

            left_image = color_bytes_to_image(bytes(left_frame.get_data()), *self.left_resolution)
            right_image = color_bytes_to_image(bytes(right_frame.get_data()), *self.right_resolution)
            left_ts_us = left_frame.get_frame_metadata(metadata)
            right_ts_us = right_frame.get_frame_metadata(metadata)
            left_frame_number = left_frame.get_frame_number()
            right_frame_number = right_frame.get_frame_number()

            yield left_image, right_image, left_ts_us, right_ts_us, left_frame_number, right_frame_number

    def stop(self):
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_streams.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add engine/streams.py tests/engine/test_streams.py
git commit -m "feat: rework streams.py for D585 left/right color stream capture"
```

---

### Task 4: `domain/realsense_utils.py` — single color decode, left/right overlay params

**Files:**
- Modify: `domain/realsense_utils.py`
- Test: `tests/domain/test_realsense_utils.py`

**Interfaces:**
- Produces: `color_bytes_to_image(raw_bytes, width, height) -> np.ndarray` (replaces `ir_bytes_to_image`/`yuyv_to_bgr`), `draw_bundle_overlay(image, bundle_index, left_frame_number, right_frame_number, left_ts_us, right_ts_us, delta_us)`.

- [ ] **Step 1: Write the failing test file**

```python
# tests/domain/test_realsense_utils.py
import numpy as np
from domain.realsense_utils import (
    sample_neighborhood_brightness,
    sample_all_neighborhood_brightness,
    apply_roi_mask,
    crop_to_roi,
    merge_close_centroids,
    detect_led_centroids,
    color_bytes_to_image,
    save_debug_detection_image,
    draw_bundle_overlay,
    draw_led_state_overlay,
)


def test_sample_neighborhood_brightness_center_patch():
    image = np.zeros((20, 20), dtype=np.uint8)
    image[8:13, 8:13] = 200
    value = sample_neighborhood_brightness(image, x=10, y=10, size=5)
    assert value == 200.0


def test_sample_neighborhood_brightness_clamps_at_edge():
    image = np.full((10, 10), 100, dtype=np.uint8)
    value = sample_neighborhood_brightness(image, x=0, y=0, size=5)
    assert value == 100.0


def test_sample_all_neighborhood_brightness_samples_each_position():
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    image[8:13, 8:13] = 200
    result = sample_all_neighborhood_brightness(image, [(10, 10), (2, 2)], size=5)
    assert result.tolist() == [200.0, 0.0]


def test_sample_all_neighborhood_brightness_grayscale_input_not_reconverted():
    image = np.zeros((20, 20), dtype=np.uint8)
    image[8:13, 8:13] = 150
    result = sample_all_neighborhood_brightness(image, [(10, 10)], size=5)
    assert result.tolist() == [150.0]


def test_apply_roi_mask_zeroes_outside_box():
    image = np.full((10, 10, 3), 255, dtype=np.uint8)
    masked = apply_roi_mask(image, (2, 2, 3, 3))
    assert masked[0, 0].tolist() == [0, 0, 0]
    assert masked[3, 3].tolist() == [255, 255, 255]
    assert masked.shape == image.shape


def test_crop_to_roi_returns_only_the_roi_region():
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    image[2:5, 2:5] = 255
    cropped = crop_to_roi(image, (2, 2, 3, 3))
    assert cropped.shape == (3, 3, 3)
    assert (cropped == 255).all()


def test_merge_close_centroids_merges_nearby_points():
    centroids = [(10.0, 10.0), (11.0, 10.0), (50.0, 50.0)]
    merged = merge_close_centroids(centroids, distance_fraction=1.5)
    assert len(merged) == 2


def test_merge_close_centroids_passthrough_below_two_points():
    assert merge_close_centroids([(1.0, 1.0)]) == [(1.0, 1.0)]


def test_detect_led_centroids_finds_bright_blob():
    image = np.zeros((50, 50), dtype=np.uint8)
    image[20:30, 20:30] = 255
    centroids, chosen_threshold = detect_led_centroids(image, None, min_area=20)
    assert len(centroids) == 1
    cx, cy = centroids[0]
    assert 20 <= cx <= 30
    assert 20 <= cy <= 30


def test_color_bytes_to_image_reshapes_correctly():
    width, height = 2, 2
    raw = bytes(range(width * height * 3))  # 2x2 bgr8 image, 3 bytes/pixel
    image = color_bytes_to_image(raw, width, height)
    assert image.shape == (2, 2, 3)
    assert image[0, 0].tolist() == [0, 1, 2]
    assert image[0, 1].tolist() == [3, 4, 5]
    assert image[1, 0].tolist() == [6, 7, 8]


def test_save_debug_detection_image_writes_file_and_marks_centroids(tmp_path):
    image = np.zeros((50, 50), dtype=np.uint8)
    path = str(tmp_path / "debug.png")
    save_debug_detection_image(image, [(25, 25)], path)
    import cv2
    assert (tmp_path / "debug.png").exists()
    saved = cv2.imread(path)
    assert saved is not None
    assert saved.shape == (50, 50, 3)
    ring_pixel = saved[25, 25 + 8]
    assert ring_pixel.tolist() == [0, 255, 0]


def test_draw_bundle_overlay_converts_grayscale_and_draws_text():
    image = np.zeros((100, 300), dtype=np.uint8)
    result = draw_bundle_overlay(
        image, bundle_index=1690, left_frame_number=1950, right_frame_number=1958,
        left_ts_us=4287559946, right_ts_us=4287559980, delta_us=-34.0,
    )
    assert result.shape == (100, 300, 3)
    assert result is not image
    assert (result > 0).any()


def test_draw_bundle_overlay_does_not_mutate_bgr_input():
    image = np.zeros((100, 300, 3), dtype=np.uint8)
    result = draw_bundle_overlay(
        image, bundle_index=0, left_frame_number=0, right_frame_number=0,
        left_ts_us=0.0, right_ts_us=0.0, delta_us=0.0,
    )
    assert (image == 0).all()
    assert (result > 0).any()


def test_draw_led_state_overlay_marks_on_led_green_and_off_led_red():
    image = np.zeros((50, 50), dtype=np.uint8)
    result = draw_led_state_overlay(image, [(10, 10), (40, 40)], [True, False])
    assert result.shape == (50, 50, 3)
    assert result is not image
    assert result[10, 10 + 8].tolist() == [0, 255, 0]
    assert result[40, 40 + 8].tolist() == [0, 0, 255]


def test_draw_led_state_overlay_does_not_mutate_bgr_input():
    image = np.zeros((50, 50, 3), dtype=np.uint8)
    result = draw_led_state_overlay(image, [(25, 25)], [True])
    assert (image == 0).all()
    assert (result > 0).any()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_realsense_utils.py -v`
Expected: FAIL (`color_bytes_to_image` doesn't exist; `draw_bundle_overlay` still takes `ir_frame_number`/`color_frame_number`/`ir_ts_us`/`color_ts_us`).

- [ ] **Step 3: Modify `domain/realsense_utils.py`**

Remove `ir_bytes_to_image` and `yuyv_to_bgr`. Add in their place:

```python
def color_bytes_to_image(raw_bytes, width, height):
    return np.frombuffer(raw_bytes, dtype=np.uint8).reshape((height, width, 3)).copy()
```

Replace the `draw_bundle_overlay` signature and body:

```python
def draw_bundle_overlay(image, bundle_index, left_frame_number, right_frame_number, left_ts_us, right_ts_us, delta_us):
    """Burns a live pairing-quality diagnostic overlay onto a copy of the
    given frame - used by Stream Config's live preview."""
    debug_img = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if len(image.shape) == 2 else image.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    lines = [
        ("Bundle: {}".format(bundle_index), (0, 255, 0)),
        ("Left Frame: {}  |  Right Frame: {}".format(left_frame_number, right_frame_number), (0, 255, 255)),
        ("Left Timestamp: {:.0f}  |  Right Timestamp: {:.0f}".format(left_ts_us, right_ts_us), (0, 255, 255)),
        ("Delta: {:.1f} us".format(delta_us), (255, 255, 0)),
    ]
    y = 25
    for text, color in lines:
        cv2.putText(debug_img, text, (10, y), font, 0.6, color, 2)
        y += 25
    return debug_img
```

Update the module docstring to describe the D585 left/right context (drop the `optical_sync_poc_` porting note). All other functions (`sample_neighborhood_brightness`, `sample_all_neighborhood_brightness`, `apply_roi_mask`, `crop_to_roi`, `merge_close_centroids`, `detect_led_centroids`, `save_debug_detection_image`, `draw_led_state_overlay`) are unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_realsense_utils.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add domain/realsense_utils.py tests/domain/test_realsense_utils.py
git commit -m "feat: single bgr8 color decode, left/right overlay params"
```

---

### Task 5: `engine/metrics.py`, `engine/test_session.py`, `engine/acquisition_loop.py` — left/right rename

**Files:**
- Modify: `engine/metrics.py`, `engine/test_session.py`, `engine/acquisition_loop.py`
- Test: `tests/engine/test_metrics.py`, `tests/engine/test_test_session.py`, `tests/engine/test_acquisition_loop.py`

**Interfaces:**
- Produces: `FramePairSample(pair_index, left_ts_us, right_ts_us, left_bright=None, right_bright=None)`, `PairingGapMetric(outlier_threshold_us)`, `PositionGapMetric(left_threshold, right_threshold, num_leds, switch_time_ms, left_fps, right_fps, frame_drop_threshold_factor, warmup_pairs_to_skip)` with `.last_left_on_mask`/`.last_right_on_mask`, `TestSession.process_pair()` rows keyed `left_ts_us`/`right_ts_us`, `AcquisitionCallbacks.on_frames(left_image, right_image, pair_index)`.

- [ ] **Step 1: Write the failing test files**

```python
# tests/engine/test_metrics.py
import numpy as np
from engine.metrics import (
    FramePairSample,
    find_last_on_led,
    compute_position_gap,
    PairingGapMetric,
    PositionGapMetric,
    _is_frame_drop,
)


def test_is_frame_drop_false_when_fps_is_zero():
    assert _is_frame_drop(prev_ts=0.0, curr_ts=100_000.0, fps=0, threshold_factor=1.5) is False


def test_is_frame_drop_false_when_fps_is_negative():
    assert _is_frame_drop(prev_ts=0.0, curr_ts=100_000.0, fps=-30, threshold_factor=1.5) is False


def test_is_frame_drop_still_detects_a_real_drop_with_valid_fps():
    assert _is_frame_drop(prev_ts=0.0, curr_ts=500_000.0, fps=30, threshold_factor=1.5) is True


def test_find_last_on_led_plain_block():
    on = np.zeros(10, dtype=bool)
    on[3:6] = True
    last, length = find_last_on_led(on)
    assert last == 5
    assert length == 3


def test_find_last_on_led_wrap_around():
    on = np.zeros(10, dtype=bool)
    on[[8, 9, 0, 1]] = True
    last, length = find_last_on_led(on)
    assert last == 1
    assert length == 4


def test_find_last_on_led_nothing_on():
    on = np.zeros(10, dtype=bool)
    last, length = find_last_on_led(on)
    assert last is None
    assert length == 0


def test_compute_position_gap_wraps_to_shortest_path():
    diff = compute_position_gap(left_last=2, right_last=98, n=100)
    assert diff == 4


def test_pairing_gap_metric_flags_outlier():
    metric = PairingGapMetric(outlier_threshold_us=100_000)
    sample = FramePairSample(pair_index=0, left_ts_us=1_000_000.0, right_ts_us=1_500_000.0)
    result = metric.update(sample)
    assert result.name == "pairing_gap_us"
    assert result.value == -500_000.0
    assert result.excluded is True
    assert result.exclude_reason == "syncer_outlier"


def test_pairing_gap_metric_accepts_close_pair():
    metric = PairingGapMetric(outlier_threshold_us=100_000)
    sample = FramePairSample(pair_index=0, left_ts_us=1_000_000.0, right_ts_us=1_000_050.0)
    result = metric.update(sample)
    assert result.excluded is False
    assert result.exclude_reason is None


def test_position_gap_metric_reports_miss_when_nothing_on():
    threshold = np.full(10, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=10,
        switch_time_ms=1.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=0,
    )
    sample = FramePairSample(
        pair_index=0, left_ts_us=0.0, right_ts_us=0.0,
        left_bright=np.full(10, 50.0), right_bright=np.full(10, 50.0),
    )
    result = metric.update(sample)
    assert result.excluded is True
    assert result.exclude_reason == "miss"


def test_position_gap_metric_computes_gap_ms():
    threshold = np.full(10, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=10,
        switch_time_ms=2.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=0,
    )
    left_bright = np.full(10, 50.0); left_bright[5] = 200.0
    right_bright = np.full(10, 50.0); right_bright[3] = 200.0
    sample = FramePairSample(pair_index=0, left_ts_us=0.0, right_ts_us=0.0, left_bright=left_bright, right_bright=right_bright)
    result = metric.update(sample)
    assert result.excluded is False
    assert result.value == 4.0  # (5 - 3) LED steps * 2.0 ms


def test_position_gap_metric_flags_warmup_pairs():
    threshold = np.full(10, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=10,
        switch_time_ms=1.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=2,
    )
    bright = np.full(10, 200.0)
    first = metric.update(FramePairSample(0, 0.0, 0.0, bright, bright))
    second = metric.update(FramePairSample(1, 33333.0, 33333.0, bright, bright))
    third = metric.update(FramePairSample(2, 66666.0, 66666.0, bright, bright))
    assert first.exclude_reason == "warmup"
    assert second.exclude_reason == "warmup"
    assert third.exclude_reason is None


def test_position_gap_metric_flags_frame_drop():
    threshold = np.full(10, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=10,
        switch_time_ms=1.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=0,
    )
    bright = np.full(10, 200.0)
    metric.update(FramePairSample(0, 0.0, 0.0, bright, bright))
    result = metric.update(FramePairSample(1, 500_000.0, 33333.0, bright, bright))
    assert result.exclude_reason == "frame_drop"


def test_position_gap_metric_extra_reports_no_drop_when_clean():
    threshold = np.full(10, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=10,
        switch_time_ms=1.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=0,
    )
    left_bright = np.full(10, 50.0); left_bright[5] = 200.0
    right_bright = np.full(10, 50.0); right_bright[3] = 200.0
    metric.update(FramePairSample(0, 0.0, 0.0, left_bright, right_bright))
    result = metric.update(FramePairSample(1, 33333.0, 33333.0, left_bright, right_bright))
    assert result.extra == {"left_frame_drop": False, "right_frame_drop": False}


def test_position_gap_metric_extra_flags_which_stream_dropped():
    threshold = np.full(10, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=10,
        switch_time_ms=1.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=0,
    )
    bright = np.full(10, 200.0)
    metric.update(FramePairSample(0, 0.0, 0.0, bright, bright))
    result = metric.update(FramePairSample(1, 500_000.0, 33333.0, bright, bright))
    assert result.extra == {"left_frame_drop": True, "right_frame_drop": False}


def test_position_gap_metric_extra_present_even_when_miss():
    threshold = np.full(10, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=10,
        switch_time_ms=1.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=0,
    )
    sample = FramePairSample(
        pair_index=0, left_ts_us=0.0, right_ts_us=0.0,
        left_bright=np.full(10, 50.0), right_bright=np.full(10, 50.0),
    )
    result = metric.update(sample)
    assert result.exclude_reason == "miss"
    assert result.extra == {"left_frame_drop": False, "right_frame_drop": False}


def test_position_gap_metric_tracks_last_on_masks_for_debug_snapshots():
    threshold = np.full(4, 150.0)
    metric = PositionGapMetric(
        left_threshold=threshold, right_threshold=threshold, num_leds=4,
        switch_time_ms=1.0, left_fps=30, right_fps=30,
        frame_drop_threshold_factor=1.5, warmup_pairs_to_skip=0,
    )
    assert metric.last_left_on_mask is None
    assert metric.last_right_on_mask is None

    left_bright = np.array([50.0, 200.0, 50.0, 50.0])
    right_bright = np.array([200.0, 50.0, 50.0, 50.0])
    metric.update(FramePairSample(0, 0.0, 0.0, left_bright, right_bright))

    assert metric.last_left_on_mask.tolist() == [False, True, False, False]
    assert metric.last_right_on_mask.tolist() == [True, False, False, False]
```

```python
# tests/engine/test_test_session.py
from engine.metrics import FramePairSample, MetricResult, Metric
from engine.test_session import TestSession, TestSessionConfig


class FakeMetric(Metric):
    name = "fake_metric"

    def update(self, sample):
        return MetricResult(name=self.name, value=float(sample.pair_index), excluded=False, exclude_reason=None)


class FakeMetricWithExtra(Metric):
    name = "fake_with_extra"

    def update(self, sample):
        return MetricResult(
            name=self.name, value=1.0, excluded=False, exclude_reason=None,
            extra={"custom_flag": True},
        )


def test_start_sets_running_true():
    session = TestSession(TestSessionConfig(metrics=[FakeMetric()]))
    assert session.is_running is False
    session.start()
    assert session.is_running is True


def test_process_pair_returns_flat_row_and_buffers_it():
    session = TestSession(TestSessionConfig(metrics=[FakeMetric()]))
    session.start()
    row = session.process_pair(FramePairSample(pair_index=0, left_ts_us=100.0, right_ts_us=100.0))
    assert row["pair_index"] == 0
    assert row["left_ts_us"] == 100.0
    assert row["fake_metric"] == 0.0
    assert row["fake_metric_excluded"] is False
    assert row["fake_metric_exclude_reason"] is None


def test_process_pair_folds_extra_dict_into_row():
    session = TestSession(TestSessionConfig(metrics=[FakeMetricWithExtra()]))
    session.start()
    row = session.process_pair(FramePairSample(pair_index=0, left_ts_us=0.0, right_ts_us=0.0))
    assert row["custom_flag"] is True


def test_stop_returns_all_buffered_rows_and_sets_running_false():
    session = TestSession(TestSessionConfig(metrics=[FakeMetric()]))
    session.start()
    session.process_pair(FramePairSample(0, 0.0, 0.0))
    session.process_pair(FramePairSample(1, 1.0, 1.0))
    rows = session.stop()
    assert len(rows) == 2
    assert session.is_running is False


def test_should_auto_stop_respects_configured_duration():
    session = TestSession(TestSessionConfig(metrics=[], duration_s=5.0))
    assert session.should_auto_stop(elapsed_s=4.9) is False
    assert session.should_auto_stop(elapsed_s=5.0) is True


def test_should_auto_stop_never_true_when_duration_is_none():
    session = TestSession(TestSessionConfig(metrics=[], duration_s=None))
    assert session.should_auto_stop(elapsed_s=1_000_000.0) is False
```

```python
# tests/engine/test_acquisition_loop.py
import numpy as np
from engine.acquisition_loop import AcquisitionLoop, AcquisitionCallbacks
from engine.metrics import Metric, MetricResult
from engine.test_session import TestSession, TestSessionConfig


class CountingMetric(Metric):
    name = "count"

    def update(self, sample):
        return MetricResult(name=self.name, value=float(sample.pair_index), excluded=False, exclude_reason=None)


def fake_frame_source(n_pairs):
    for i in range(n_pairs):
        left_image = np.full((4, 4, 3), i, dtype=np.uint8)
        right_image = np.full((4, 4, 3), i, dtype=np.uint8)
        yield left_image, right_image, float(i), float(i), None, None


def test_run_until_stopped_processes_every_frame_and_calls_on_row():
    session = TestSession(TestSessionConfig(metrics=[CountingMetric()]))
    session.start()
    rows_seen = []
    callbacks = AcquisitionCallbacks(
        on_frames=lambda left, right, idx: None,
        on_row=lambda row: rows_seen.append(row),
        on_stats=lambda stats: None,
    )
    loop = AcquisitionLoop(fake_frame_source(5), session, callbacks, display_stride=2)

    stop_after = {"count": 0}

    def is_stop_requested():
        stop_after["count"] += 1
        return stop_after["count"] > 5

    rows = loop.run_until_stopped(is_stop_requested, elapsed_s_fn=lambda: 0.0)

    assert len(rows) == 5
    assert [row["pair_index"] for row in rows] == [0, 1, 2, 3, 4]
    assert len(rows_seen) == 5


def test_run_until_stopped_throttles_frame_display_by_stride():
    session = TestSession(TestSessionConfig(metrics=[CountingMetric()]))
    session.start()
    frames_seen = []
    callbacks = AcquisitionCallbacks(
        on_frames=lambda left, right, idx: frames_seen.append(idx),
        on_row=lambda row: None,
        on_stats=lambda stats: None,
    )
    loop = AcquisitionLoop(fake_frame_source(10), session, callbacks, display_stride=3)
    loop.run_until_stopped(is_stop_requested=lambda: False, elapsed_s_fn=lambda: 0.0)

    assert frames_seen == [0, 3, 6, 9]


def test_run_until_stopped_honors_stop_request_mid_stream():
    session = TestSession(TestSessionConfig(metrics=[CountingMetric()]))
    session.start()
    callbacks = AcquisitionCallbacks(on_frames=lambda *a: None, on_row=lambda r: None, on_stats=lambda s: None)
    loop = AcquisitionLoop(fake_frame_source(100), session, callbacks, display_stride=10)

    seen = {"n": 0}

    def is_stop_requested():
        seen["n"] += 1
        return seen["n"] > 3

    rows = loop.run_until_stopped(is_stop_requested, elapsed_s_fn=lambda: 0.0)
    assert len(rows) == 3


def test_run_until_stopped_honors_session_auto_stop_duration():
    session = TestSession(TestSessionConfig(metrics=[CountingMetric()], duration_s=2.0))
    session.start()
    callbacks = AcquisitionCallbacks(on_frames=lambda *a: None, on_row=lambda r: None, on_stats=lambda s: None)
    loop = AcquisitionLoop(fake_frame_source(100), session, callbacks, display_stride=10)

    elapsed = {"t": 0.0}

    def elapsed_s_fn():
        elapsed["t"] += 1.0
        return elapsed["t"]

    rows = loop.run_until_stopped(is_stop_requested=lambda: False, elapsed_s_fn=elapsed_s_fn)
    assert len(rows) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_metrics.py tests/engine/test_test_session.py tests/engine/test_acquisition_loop.py -v`
Expected: FAIL (`FramePairSample`/`PositionGapMetric` still use `ir_`/`rgb_` kwargs).

- [ ] **Step 3: Rewrite the three implementation files**

`engine/metrics.py` — rename throughout: `ir_ts_us`→`left_ts_us`, `rgb_ts_us`→`right_ts_us`, `ir_bright`→`left_bright`, `rgb_bright`→`right_bright`, `ir_threshold`→`left_threshold`, `rgb_threshold`→`right_threshold`, `ir_fps`→`left_fps`, `rgb_fps`→`right_fps`, `ir_last`/`rgb_last`→`left_last`/`right_last`, `last_ir_on_mask`/`last_rgb_on_mask`→`last_left_on_mask`/`last_right_on_mask`, `ir_frame_drop`/`rgb_frame_drop`→`left_frame_drop`/`right_frame_drop`, `_prev_ir_ts`/`_prev_rgb_ts`→`_prev_left_ts`/`_prev_right_ts`. `PairingGapMetric.update`'s gap becomes `sample.left_ts_us - sample.right_ts_us`. Logic is otherwise byte-for-byte identical to the original.

`engine/test_session.py` — in `process_pair`, change the row dict's `"ir_ts_us": sample.ir_ts_us, "rgb_ts_us": sample.rgb_ts_us` to `"left_ts_us": sample.left_ts_us, "right_ts_us": sample.right_ts_us`. Nothing else changes.

`engine/acquisition_loop.py` — in `run_until_stopped`, rename the unpacked tuple `ir_image, rgb_image, ir_ts_us, rgb_ts_us, ir_bright, rgb_bright` to `left_image, right_image, left_ts_us, right_ts_us, left_bright, right_bright`, and update the `FramePairSample(...)` call and `self.callbacks.on_frames(left_image, right_image, pair_index)` accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/engine/test_metrics.py tests/engine/test_test_session.py tests/engine/test_acquisition_loop.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add engine/metrics.py engine/test_session.py engine/acquisition_loop.py \
        tests/engine/test_metrics.py tests/engine/test_test_session.py tests/engine/test_acquisition_loop.py
git commit -m "feat: rename ir/rgb to left/right in metrics, test session, acquisition loop"
```

---

### Task 6: `domain/calibration.py` — left/right config.yaml keys

**Files:**
- Modify: `domain/calibration.py`
- Test: `tests/domain/test_calibration.py`

**Interfaces:**
- Produces: `update_config_leds(config_path, camera_name, left_positions, left_res, right_positions, right_res)`, `load_led_positions(config_path, camera_name) -> (left_positions, right_positions)`.

- [ ] **Step 1: Write the failing test file**

```python
# tests/domain/test_calibration.py
import numpy as np
import yaml
from domain.calibration import (
    assign_grid_ids,
    build_positions_with_thresholds,
    update_config_leds,
    load_led_positions,
)


def test_assign_grid_ids_orders_row_major():
    centroids = [(20, 10), (10, 10), (30, 10), (20, 30), (10, 30), (30, 30)]
    positions, row_layout = assign_grid_ids(centroids, row_gap_px=15)
    assert row_layout == [3, 3]
    assert positions["0"] == [10.0, 10.0]
    assert positions["1"] == [20.0, 10.0]
    assert positions["2"] == [30.0, 10.0]
    assert positions["3"] == [10.0, 30.0]


def test_assign_grid_ids_raises_on_empty_input():
    try:
        assign_grid_ids([])
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_build_positions_with_thresholds_computes_midpoint():
    on_frame = np.full((20, 20), 200, dtype=np.uint8)
    off_frame = np.full((20, 20), 100, dtype=np.uint8)
    xy_positions = {"0": (10, 10)}
    result = build_positions_with_thresholds(xy_positions, on_frame, off_frame, neighborhood_size=5)
    x, y, on_value, off_value, threshold = result["0"]
    assert (x, y) == (10, 10)
    assert on_value == 200.0
    assert off_value == 100.0
    assert threshold == 150.0


def test_update_config_leds_writes_camera_subblock(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"leds": {"Other Camera": {"left": {}, "right": {}}}}))

    update_config_leds(
        str(config_path),
        camera_name="Test Camera",
        left_positions={"0": [1.0, 2.0, 255.0, 100.0, 177.5]},
        left_res=(1280, 720),
        right_positions={"0": [3.0, 4.0, 250.0, 90.0, 170.0]},
        right_res=(1280, 720),
    )

    written = yaml.safe_load(config_path.read_text())
    assert "Other Camera" in written["leds"]  # untouched sibling block preserved
    assert written["leds"]["Test Camera"]["left"]["positions"]["0"] == [1.0, 2.0, 255.0, 100.0, 177.5]
    assert written["leds"]["Test Camera"]["right"]["frame_width"] == 1280


def test_load_led_positions_returns_left_and_right_dicts(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "leds": {
            "Test Camera": {
                "left": {"positions": {"0": [1.0, 2.0, 255.0, 100.0, 177.5]}},
                "right": {"positions": {"0": [3.0, 4.0, 250.0, 90.0, 170.0]}},
            }
        }
    }))
    left_positions, right_positions = load_led_positions(str(config_path), "Test Camera")
    assert left_positions["0"] == [1.0, 2.0, 255.0, 100.0, 177.5]
    assert right_positions["0"] == [3.0, 4.0, 250.0, 90.0, 170.0]


def test_load_led_positions_raises_for_uncalibrated_camera(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"leds": {"Other Camera": {"left": {}, "right": {}}}}))
    try:
        load_led_positions(str(config_path), "Never Calibrated Camera")
        assert False, "expected KeyError"
    except KeyError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_calibration.py -v`
Expected: FAIL (`update_config_leds`/`load_led_positions` still use `ir_positions`/`rgb_positions` kwargs and `"ir"`/`"rgb"` config keys).

- [ ] **Step 3: Modify `domain/calibration.py`**

In `update_config_leds`, rename the signature to `(config_path, camera_name, left_positions, left_res, right_positions, right_res)` and the written dict's `"ir"`/`"rgb"` keys to `"left"`/`"right"` (using `left_positions`/`left_res`/`right_positions`/`right_res` in place of the old `ir_*`/`rgb_*` locals). In `load_led_positions`, read `leds_by_camera[camera_name]["left"]["positions"]`/`["right"]["positions"]` instead of `["ir"]`/`["rgb"]`. `assign_grid_ids` and `build_positions_with_thresholds` are unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/domain/test_calibration.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add domain/calibration.py tests/domain/test_calibration.py
git commit -m "feat: rename config.yaml ir/rgb keys to left/right"
```

---

### Task 7: `settings.yaml` + `state/gui_state.py` — left/right camera settings and persisted state

**Files:**
- Modify: `settings.yaml`, `state/gui_state.py`
- Test: `tests/state/test_gui_state.py`

**Interfaces:**
- Produces: `GuiState(device_serial, left_fps, left_width, left_height, right_fps, right_width, right_height, left_roi, right_roi)`.

- [ ] **Step 1: Write the failing test file**

```python
# tests/state/test_gui_state.py
from state.gui_state import GuiState, load_gui_state, save_gui_state


def test_load_gui_state_missing_file_returns_defaults(tmp_path):
    path = tmp_path / "gui_state.json"
    state = load_gui_state(str(path))
    assert state == GuiState()


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "gui_state.json"
    original = GuiState(
        device_serial="123456",
        left_fps=30, left_width=1280, left_height=720,
        right_fps=30, right_width=1280, right_height=720,
        left_roi=[10, 20, 100, 100], right_roi=[5, 15, 90, 90],
    )
    save_gui_state(original, str(path))
    loaded = load_gui_state(str(path))
    assert loaded == original


def test_load_gui_state_ignores_corrupt_file(tmp_path):
    path = tmp_path / "gui_state.json"
    path.write_text("{not valid json")
    state = load_gui_state(str(path))
    assert state == GuiState()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/state/test_gui_state.py -v`
Expected: FAIL (`GuiState` still has `ir_fps`/`ir_width`/etc. fields, not `left_fps`/`left_width`/etc.)

- [ ] **Step 3: Modify `state/gui_state.py` and `settings.yaml`**

In `state/gui_state.py`, rename the `GuiState` dataclass fields: `ir_fps`→`left_fps`, `ir_width`→`left_width`, `ir_height`→`left_height`, `rgb_fps`→`right_fps`, `rgb_width`→`right_width`, `rgb_height`→`right_height`, `ir_roi`→`left_roi`, `rgb_roi`→`right_roi`. `load_gui_state`/`save_gui_state` bodies are unchanged (they already work generically off `dataclasses.fields`/`dataclasses.asdict`).

In `settings.yaml`, rename the `camera:` block's `ir:`/`color:` keys to `left:`/`right:`:

```yaml
camera:
  left: {width: 1280, height: 720, fps: 30}
  right: {width: 1280, height: 720, fps: 30}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/state/test_gui_state.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add state/gui_state.py settings.yaml tests/state/test_gui_state.py
git commit -m "feat: rename persisted state and settings.yaml camera keys to left/right"
```

---

### Task 8: `gui/pages/device_select_page.py` — mode display + Dual RGB switch

**Files:**
- Modify: `gui/pages/device_select_page.py`
- Test: `tests/gui/pages/test_device_select_page.py` (new)

**Interfaces:**
- Consumes: `engine.streams.list_devices`, `find_device_by_serial`, `DeviceInfo` (Task 3); `engine.rgb_mode.ensure_dual_rgb_mode` (Task 2)
- Produces: `_device_label(device_info) -> str`, `DeviceSelectPage.device_chosen` signal unchanged: `(serial: str, name: str)`.

- [ ] **Step 1: Write the failing test file**

```python
# tests/gui/pages/test_device_select_page.py
from gui.pages.device_select_page import _device_label
from engine.streams import DeviceInfo


def test_device_label_shows_dual_rgb_mode():
    info = DeviceInfo(name="Intel RealSense D585", serial="123456789", mode="dual")
    assert _device_label(info) == "Intel RealSense D585 - Dual RGB (123456789)"


def test_device_label_shows_dedicated_rgb_mode():
    info = DeviceInfo(name="Intel RealSense D585", serial="123456789", mode="dedicated")
    assert _device_label(info) == "Intel RealSense D585 - Dedicated RGB (123456789)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_device_select_page.py -v`
Expected: FAIL (`_device_label` doesn't exist yet).

- [ ] **Step 3: Rewrite `gui/pages/device_select_page.py`**

```python
"""Wizard step 1: pick which connected D585/D535 device to use, switching
it into Dual RGB firmware mode first if it isn't already there."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QApplication

from engine.streams import list_devices, find_device_by_serial
from engine.rgb_mode import ensure_dual_rgb_mode


def _device_label(device_info):
    mode_label = "Dual RGB" if device_info.mode == "dual" else "Dedicated RGB"
    return "{} - {} ({})".format(device_info.name, mode_label, device_info.serial)


class DeviceSelectPage(QWidget):
    device_chosen = Signal(str, str)  # (serial, name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices = []
        self.ctx = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a connected D585/D535 device:"))
        self.combo = QComboBox()
        layout.addWidget(self.combo)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._on_next_clicked)
        layout.addWidget(self.next_button)

    def refresh_devices(self, ctx):
        self.ctx = ctx
        self._devices = list_devices(ctx)
        self.combo.clear()
        for device in self._devices:
            self.combo.addItem(_device_label(device), userData=device.serial)

    def _on_next_clicked(self):
        serial = self.combo.currentData()
        if serial is None:
            return
        device_info = next((d for d in self._devices if d.serial == serial), None)
        if device_info is None:
            return
        name = device_info.name

        if device_info.mode == "dedicated":
            self.status_label.setText("Switching to Dual RGB mode - this takes a few seconds...")
            self.next_button.setEnabled(False)
            self.combo.setEnabled(False)
            QApplication.processEvents()
            try:
                device = find_device_by_serial(self.ctx, serial)
                ensure_dual_rgb_mode(self.ctx, device)
            except Exception as exc:
                self.status_label.setText("Failed to switch to Dual RGB mode: {}".format(exc))
                self.next_button.setEnabled(True)
                self.combo.setEnabled(True)
                return
            self.status_label.setText("")
            self.next_button.setEnabled(True)
            self.combo.setEnabled(True)

        self.device_chosen.emit(serial, name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_device_select_page.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add gui/pages/device_select_page.py tests/gui/pages/test_device_select_page.py
git commit -m "feat: show RGB mode in Device Select and auto-switch to Dual RGB"
```

---

### Task 9: `gui/pages/stream_config_page.py` + `engine/stream_preview_thread.py` — left/right combo boxes

**Files:**
- Modify: `gui/pages/stream_config_page.py`, `engine/stream_preview_thread.py`
- Test: `tests/gui/pages/test_stream_config_page.py`

**Interfaces:**
- Consumes: `engine.streams.list_supported_profiles(sensor, stream_type, fmt, stream_index)`, `get_color_sensor_for_device` (Task 3)
- Produces: `StreamConfigPage.populate(ctx, device_serial, color_sensor, preferred_left=None, preferred_right=None)`, `.left_combo`/`.right_combo`, `config_chosen` signal payload `(left_width, left_height, left_fps, right_width, right_height, right_fps)`.

- [ ] **Step 1: Write the failing test file**

```python
# tests/gui/pages/test_stream_config_page.py
from gui.pages.stream_config_page import StreamConfigPage


def test_preselect_sets_current_index_when_preferred_combo_exists(qapp):
    page = StreamConfigPage()
    page.left_combo.addItem("640x480@30fps", userData=(640, 480, 30))
    page.left_combo.addItem("1280x720@30fps", userData=(1280, 720, 30))

    page._preselect(page.left_combo, (1280, 720, 30))

    assert page.left_combo.currentData() == (1280, 720, 30)


def test_preselect_leaves_default_selection_when_preferred_combo_unavailable(qapp):
    page = StreamConfigPage()
    page.left_combo.addItem("640x480@30fps", userData=(640, 480, 30))
    page.left_combo.addItem("320x240@60fps", userData=(320, 240, 60))

    page._preselect(page.left_combo, (1280, 720, 30))  # not in the list

    assert page.left_combo.currentData() == (640, 480, 30)  # unchanged, first item


def test_preselect_does_nothing_when_no_preferred_combo_given(qapp):
    page = StreamConfigPage()
    page.right_combo.addItem("640x480@30fps", userData=(640, 480, 30))

    page._preselect(page.right_combo, None)

    assert page.right_combo.currentData() == (640, 480, 30)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_stream_config_page.py -v`
Expected: FAIL (`page.left_combo`/`page.right_combo` don't exist yet - the page still has `ir_combo`/`rgb_combo`).

- [ ] **Step 3: Rewrite `gui/pages/stream_config_page.py`**

```python
"""Wizard step 2: pick FPS/resolution for the left and right color
streams, and preview live pairing quality for the currently selected
combo before committing to it."""

import pyrealsense2 as rs
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox, QPushButton,
)

from engine.streams import list_supported_profiles
from engine.stream_preview_thread import StreamPreviewThread
from gui.widgets.video_panel import VideoPanel


class StreamConfigPage(QWidget):
    config_chosen = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = None
        self.device_serial = None
        self.preview_thread = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.left_combo = QComboBox()
        self.right_combo = QComboBox()
        form.addRow(QLabel("Left resolution/fps:"), self.left_combo)
        form.addRow(QLabel("Right resolution/fps:"), self.right_combo)
        layout.addLayout(form)

        preview_row = QHBoxLayout()
        self.start_preview_button = QPushButton("Start Preview")
        self.start_preview_button.clicked.connect(self._on_start_preview_clicked)
        self.stop_preview_button = QPushButton("Stop Preview")
        self.stop_preview_button.clicked.connect(self._on_stop_preview_clicked)
        self.stop_preview_button.setEnabled(False)
        preview_row.addWidget(self.start_preview_button)
        preview_row.addWidget(self.stop_preview_button)
        layout.addLayout(preview_row)

        self.preview_panel = VideoPanel()
        layout.addWidget(self.preview_panel, stretch=1)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._on_next_clicked)
        layout.addWidget(self.next_button)

    def populate(self, ctx, device_serial, color_sensor, preferred_left=None, preferred_right=None):
        self.ctx = ctx
        self.device_serial = device_serial

        left_profiles = list_supported_profiles(color_sensor, rs.stream.color, rs.format.bgr8, stream_index=1)
        right_profiles = list_supported_profiles(color_sensor, rs.stream.color, rs.format.bgr8, stream_index=2)

        self.left_combo.clear()
        for width, height, fps in left_profiles:
            self.left_combo.addItem("{}x{}@{}fps".format(width, height, fps), userData=(width, height, fps))
        self._preselect(self.left_combo, preferred_left)

        self.right_combo.clear()
        for width, height, fps in right_profiles:
            self.right_combo.addItem("{}x{}@{}fps".format(width, height, fps), userData=(width, height, fps))
        self._preselect(self.right_combo, preferred_right)

    def _preselect(self, combo, preferred):
        if preferred is None:
            return
        width, height, fps = preferred
        index = combo.findText("{}x{}@{}fps".format(width, height, fps))
        if index != -1:
            combo.setCurrentIndex(index)

    def _on_start_preview_clicked(self):
        left_choice = self.left_combo.currentData()
        right_choice = self.right_combo.currentData()
        if left_choice is None or right_choice is None:
            return
        left_width, left_height, left_fps = left_choice
        right_width, right_height, right_fps = right_choice

        self.status_label.setText("")
        self.preview_thread = StreamPreviewThread(
            self.ctx, self.device_serial, (left_width, left_height), left_fps, (right_width, right_height), right_fps,
        )
        self.preview_thread.frame_ready.connect(self.preview_panel.set_frame)
        self.preview_thread.error.connect(self._on_preview_error)
        self.preview_thread.start()

        self.start_preview_button.setEnabled(False)
        self.stop_preview_button.setEnabled(True)
        self.left_combo.setEnabled(False)
        self.right_combo.setEnabled(False)

    def _on_stop_preview_clicked(self):
        self._stop_preview()

    def _stop_preview(self):
        if self.preview_thread is not None:
            self.preview_thread.request_stop()
            self.preview_thread.wait()
            self.preview_thread = None
        self.start_preview_button.setEnabled(True)
        self.stop_preview_button.setEnabled(False)
        self.left_combo.setEnabled(True)
        self.right_combo.setEnabled(True)

    def _on_preview_error(self, message):
        self.status_label.setText("Error: {}".format(message))
        self._stop_preview()

    def _on_next_clicked(self):
        left_choice = self.left_combo.currentData()
        right_choice = self.right_combo.currentData()
        if left_choice is not None and right_choice is not None:
            self._stop_preview()
            left_width, left_height, left_fps = left_choice
            right_width, right_height, right_fps = right_choice
            self.config_chosen.emit((left_width, left_height, left_fps, right_width, right_height, right_fps))
```

Also rewrite `engine/stream_preview_thread.py` (hardware-facing, untested by design):

```python
"""QThread wrapper for the Stream Config page's live pairing-quality
preview: streams left+right color continuously via ContinuousCapture,
burns a bundle/frame-number/timestamp/delta overlay onto the left frame,
and prints the same info to the console."""

from PySide6.QtCore import QThread, Signal

from engine.streams import ContinuousCapture, enable_auto_exposure, get_color_sensor_for_device
from domain.realsense_utils import draw_bundle_overlay


class StreamPreviewThread(QThread):
    frame_ready = Signal(object)
    error = Signal(str)

    def __init__(self, ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps,
                 display_stride=10, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.device_serial = device_serial
        self.left_resolution = left_resolution
        self.left_fps = left_fps
        self.right_resolution = right_resolution
        self.right_fps = right_fps
        self.display_stride = display_stride
        self._stop_requested = False
        self._capture = None

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            color_sensor = get_color_sensor_for_device(self.ctx, self.device_serial)
            if not enable_auto_exposure(color_sensor):
                self.error.emit(
                    "This sensor/firmware does not expose enable_auto_exposure - confirm auto-exposure is on manually."
                )

            self._capture = ContinuousCapture(self.left_resolution, self.left_fps, self.right_resolution, self.right_fps)
            self._capture.start()

            bundle_index = 0
            for left_image, right_image, left_ts_us, right_ts_us, left_frame_number, right_frame_number \
                    in self._capture.frames_with_diagnostics():
                if self._stop_requested:
                    break

                if bundle_index % self.display_stride == 0:
                    delta_us = left_ts_us - right_ts_us
                    print(
                        "Bundle {:>6} | Left Frame {:>6} | Right Frame {:>6} | "
                        "Left Timestamp {:>14.0f} | Right Timestamp {:>14.0f} | Delta {:>7.1f} us".format(
                            bundle_index, left_frame_number, right_frame_number, left_ts_us, right_ts_us, delta_us,
                        )
                    )
                    overlay_image = draw_bundle_overlay(
                        left_image, bundle_index, left_frame_number, right_frame_number,
                        left_ts_us, right_ts_us, delta_us,
                    )
                    self.frame_ready.emit(overlay_image)

                bundle_index += 1
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if self._capture is not None:
                self._capture.stop()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_stream_config_page.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add gui/pages/stream_config_page.py engine/stream_preview_thread.py tests/gui/pages/test_stream_config_page.py
git commit -m "feat: rename Stream Config page combos and preview thread to left/right"
```

---

### Task 10: `gui/pages/roi_select_page.py` — left/right capture and ROI labels

**Files:**
- Modify: `gui/pages/roi_select_page.py` (no test file — hardware-facing, matches this project's existing convention)

**Interfaces:**
- Consumes: `engine.streams.get_color_sensor_for_device`, `match_profile(..., stream_index)`, `capture_synced_frame_pair(color_sensor, left_profile, right_profile, ...)` (Task 3); `domain.realsense_utils.color_bytes_to_image` (Task 4)
- Produces: `RoiSelectPage.set_context(ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps, settle_frames=15)`, `roi_chosen` signal payload `(left_roi, right_roi)`.

- [ ] **Step 1: Rewrite `gui/pages/roi_select_page.py`**

```python
"""Wizard step 3: capture one settled frame per color stream index with
all LEDs lit (for visibility), then use cv2.selectROI's native popup
window to draw each box directly in image pixel space."""

import time

import cv2
import pyrealsense2 as rs
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from domain.realsense_utils import color_bytes_to_image
from engine.streams import (
    match_profile, enable_auto_exposure, get_color_sensor_for_device, capture_synced_frame_pair,
)
from engine.led_panel import LEDPanel


def _select_roi(image, window_title):
    x, y, w, h = map(int, cv2.selectROI(window_title, image, showCrosshair=True, fromCenter=False))
    cv2.destroyWindow(window_title)
    if w == 0 or h == 0:
        return None
    return x, y, w, h


class RoiSelectPage(QWidget):
    roi_chosen = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending_args = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Click below to light all LEDs and capture a frame, then drag a box "
            "on each popup window (Enter=confirm, C=cancel)."
        ))
        self.capture_button = QPushButton("Capture && Select ROI")
        self.capture_button.clicked.connect(self._on_capture_clicked)
        layout.addWidget(self.capture_button)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def set_context(self, ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps,
                    settle_frames=15):
        self._pending_args = dict(
            ctx=ctx, device_serial=device_serial, left_resolution=left_resolution, left_fps=left_fps,
            right_resolution=right_resolution, right_fps=right_fps, settle_frames=settle_frames,
        )
        self.status_label.setText("")

    def _on_capture_clicked(self):
        if self._pending_args is None:
            return
        self.capture_button.setEnabled(False)
        try:
            self._capture_and_select(**self._pending_args)
        except Exception as exc:
            self.status_label.setText("Error: {}".format(exc))
        finally:
            self.capture_button.setEnabled(True)

    def _capture_and_select(self, ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps,
                            settle_frames):
        color_sensor = get_color_sensor_for_device(ctx, device_serial)
        left_profile = match_profile(color_sensor, rs.stream.color, rs.format.bgr8, *left_resolution, left_fps, stream_index=1)
        right_profile = match_profile(color_sensor, rs.stream.color, rs.format.bgr8, *right_resolution, right_fps, stream_index=2)

        if not enable_auto_exposure(color_sensor):
            self.status_label.setText(
                "WARNING: enable_auto_exposure not supported - confirm auto-exposure is on manually."
            )

        def turn_on_all_leds():
            LEDPanel.stop()
            LEDPanel.all_leds_on()
            time.sleep(0.5)

        try:
            left_raw, right_raw = capture_synced_frame_pair(
                color_sensor, left_profile, right_profile,
                on_both_streaming=turn_on_all_leds,
                settle_frames=settle_frames,
            )
        finally:
            try:
                LEDPanel.all_leds_off()
            except Exception as exc:
                self.status_label.setText("Warning: failed to turn LEDs off during cleanup: {}".format(exc))

        left_image = color_bytes_to_image(left_raw, *left_resolution)
        right_image = color_bytes_to_image(right_raw, *right_resolution)

        left_roi = _select_roi(left_image, "Left - drag ROI, Enter=OK, C=Cancel")
        if left_roi is None:
            self.status_label.setText("Left ROI selection cancelled - try again.")
            return

        right_roi = _select_roi(right_image, "Right - drag ROI, Enter=OK, C=Cancel")
        if right_roi is None:
            self.status_label.setText("Right ROI selection cancelled - try again.")
            return

        self.status_label.setText("ROI selected: Left={} Right={}".format(left_roi, right_roi))
        self.roi_chosen.emit((left_roi, right_roi))
```

Note: `_select_roi` no longer needs the grayscale-to-BGR conversion branch — both streams are already bgr8 color images.

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing)**

Confirm the module imports cleanly and the wizard's later wiring (Task 14) can call `set_context`/read `roi_chosen`'s payload shape without errors:

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from gui.pages.roi_select_page import RoiSelectPage; RoiSelectPage()"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add gui/pages/roi_select_page.py
git commit -m "feat: adapt ROI Select page for left/right color stream capture"
```

---

### Task 11: `gui/pages/calibration_page.py` — left/right calibration flow

**Files:**
- Modify: `gui/pages/calibration_page.py` (no test file — hardware-facing, matches convention)

**Interfaces:**
- Consumes: same as Task 10, plus `domain.calibration.update_config_leds(config_path, camera_name, left_positions, left_res, right_positions, right_res)` (Task 6)
- Produces: `CalibrationPage.set_context(ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps, left_roi, right_roi, config_path, camera_name, output_dir, settle_frames=15, min_blob_area=20, neighborhood_size=5, row_gap_px=15, min_acceptable_contrast=20)`.

- [ ] **Step 1: Rewrite `gui/pages/calibration_page.py`**

```python
"""Wizard step 4: runs LED calibration in-app, logging progress into a
QPlainTextEdit instead of print()."""

import os
import time

import pyrealsense2 as rs
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QPushButton, QApplication

from domain.calibration import assign_grid_ids, build_positions_with_thresholds, update_config_leds
from domain.realsense_utils import (
    detect_led_centroids, merge_close_centroids, apply_roi_mask, save_debug_detection_image,
    color_bytes_to_image,
)
from engine.streams import (
    match_profile, enable_auto_exposure, get_color_sensor_for_device, capture_synced_frame_pair,
)
from engine.led_panel import LEDPanel


class CalibrationPage(QWidget):
    calibration_done = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        self.run_button = QPushButton("Run Calibration")
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)
        self._pending_args = None

    def _log(self, message):
        self.log_view.appendPlainText(message)
        QApplication.processEvents()

    def set_context(self, ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps,
                    left_roi, right_roi, config_path, camera_name, output_dir,
                    settle_frames=15, min_blob_area=20, neighborhood_size=5, row_gap_px=15,
                    min_acceptable_contrast=20):
        self._pending_args = dict(
            ctx=ctx, device_serial=device_serial, left_resolution=left_resolution, left_fps=left_fps,
            right_resolution=right_resolution, right_fps=right_fps, left_roi=left_roi, right_roi=right_roi,
            config_path=config_path, camera_name=camera_name, output_dir=output_dir,
            settle_frames=settle_frames, min_blob_area=min_blob_area,
            neighborhood_size=neighborhood_size, row_gap_px=row_gap_px,
            min_acceptable_contrast=min_acceptable_contrast,
        )

    def _on_run_clicked(self):
        if self._pending_args is None:
            return
        self.run_button.setEnabled(False)
        try:
            self._run_calibration(**self._pending_args)
        except Exception as exc:
            self._log("Calibration failed: {}".format(exc))
        finally:
            self.run_button.setEnabled(True)

    def _run_calibration(self, ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps,
                          left_roi, right_roi, config_path, camera_name, output_dir, settle_frames,
                          min_blob_area, neighborhood_size, row_gap_px, min_acceptable_contrast):
        color_sensor = get_color_sensor_for_device(ctx, device_serial)
        left_profile = match_profile(color_sensor, rs.stream.color, rs.format.bgr8, *left_resolution, left_fps, stream_index=1)
        right_profile = match_profile(color_sensor, rs.stream.color, rs.format.bgr8, *right_resolution, right_fps, stream_index=2)

        if not enable_auto_exposure(color_sensor):
            self._log("WARNING: enable_auto_exposure not supported - confirm auto-exposure is on manually.")

        def turn_on_all_leds():
            self._log("Turning on all LEDs...")
            LEDPanel.stop()
            LEDPanel.all_leds_on()
            time.sleep(0.5)

        try:
            left_on_raw, right_on_raw = capture_synced_frame_pair(
                color_sensor, left_profile, right_profile,
                on_both_streaming=turn_on_all_leds,
                settle_frames=settle_frames,
            )
        finally:
            try:
                LEDPanel.all_leds_off()
            except Exception as exc:
                self._log("WARNING: failed to turn LEDs off during cleanup: {}".format(exc))

        self._log("Turning LED panel off, capturing OFF-state frames...")
        left_off_raw, right_off_raw = capture_synced_frame_pair(
            color_sensor, left_profile, right_profile,
            on_both_streaming=None,
            settle_frames=settle_frames,
        )

        left_on_image = color_bytes_to_image(left_on_raw, *left_resolution)
        right_on_image = color_bytes_to_image(right_on_raw, *right_resolution)
        left_off_image = color_bytes_to_image(left_off_raw, *left_resolution)
        right_off_image = color_bytes_to_image(right_off_raw, *right_resolution)

        left_masked = apply_roi_mask(left_on_image, left_roi)
        right_masked = apply_roi_mask(right_on_image, right_roi)

        self._log("Detecting LEDs in Left frame...")
        left_centroids, left_otsu = detect_led_centroids(left_masked, None, min_blob_area)
        left_centroids = merge_close_centroids(left_centroids)
        self._log("Detected {} LED(s) in Left (Otsu threshold {}).".format(len(left_centroids), left_otsu))
        left_debug_path = os.path.join(output_dir, "debug_left_detection.png")
        save_debug_detection_image(left_masked, left_centroids, left_debug_path)
        self._log("Saved debug image (masked frame + detected LEDs circled): {}".format(left_debug_path))
        left_positions, left_row_layout = assign_grid_ids(left_centroids, row_gap_px)

        self._log("Detecting LEDs in Right frame...")
        right_centroids, right_otsu = detect_led_centroids(right_masked, None, min_blob_area)
        right_centroids = merge_close_centroids(right_centroids)
        self._log("Detected {} LED(s) in Right (Otsu threshold {}).".format(len(right_centroids), right_otsu))
        right_debug_path = os.path.join(output_dir, "debug_right_detection.png")
        save_debug_detection_image(right_masked, right_centroids, right_debug_path)
        self._log("Saved debug image (masked frame + detected LEDs circled): {}".format(right_debug_path))
        right_positions, right_row_layout = assign_grid_ids(right_centroids, row_gap_px)

        if left_row_layout != right_row_layout:
            self._log(
                "WARNING: Left row layout {} != Right row layout {} - led_id may not match the same "
                "physical LED in both dicts.".format(left_row_layout, right_row_layout)
            )

        self._log("Computing per-LED on/off/threshold values...")
        left_positions = build_positions_with_thresholds(left_positions, left_on_image, left_off_image, neighborhood_size)
        right_positions = build_positions_with_thresholds(right_positions, right_on_image, right_off_image, neighborhood_size)

        for label, positions in (("Left", left_positions), ("Right", right_positions)):
            weakest_id, weakest_contrast = min(
                ((led_id, vals[2] - vals[3]) for led_id, vals in positions.items()),
                key=lambda pair: pair[1],
            )
            self._log("{} weakest LED contrast: led_id={} on-off={:.2f}".format(label, weakest_id, weakest_contrast))
            if weakest_contrast < min_acceptable_contrast:
                self._log("  WARNING: this LED's on/off gap is small - its threshold may be unreliable.")

        update_config_leds(config_path, camera_name, left_positions, left_resolution, right_positions, right_resolution)
        self._log("Saved {} LED positions per sensor to {}".format(len(left_positions), config_path))
        self.calibration_done.emit()
```

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from gui.pages.calibration_page import CalibrationPage; CalibrationPage()"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add gui/pages/calibration_page.py
git commit -m "feat: adapt Calibration page for left/right color stream capture"
```

---

### Task 12: `engine/session_engine.py` — left/right live-session hardware thread

**Files:**
- Modify: `engine/session_engine.py` (no test file — hardware-facing, matches convention)

**Interfaces:**
- Consumes: `engine.streams.ContinuousCapture(left_resolution, left_fps, right_resolution, right_fps)`, `get_color_sensor_for_device`, `enable_auto_exposure` (Task 3); `domain.realsense_utils.sample_all_neighborhood_brightness` (unchanged)
- Produces: `SessionEngineThread(ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps, test_session, left_xy=None, right_xy=None, neighborhood_size=5, scan_direction=None, switch_time_ms=None, display_stride=10, position_gap_metric=None, parent=None)`. `frame_ready` signal now emits `"left"`/`"right"` as `stream_name` instead of `"ir"`/`"rgb"`.

- [ ] **Step 1: Rewrite `engine/session_engine.py`**

```python
"""Thin QThread adapter: wires real hardware (engine.streams,
engine.led_panel) into engine.acquisition_loop.AcquisitionLoop and
translates its plain-Python callbacks into Qt signals."""

from PySide6.QtCore import QThread, Signal

from engine.acquisition_loop import AcquisitionLoop, AcquisitionCallbacks
from engine.streams import ContinuousCapture, enable_auto_exposure, get_color_sensor_for_device
from engine.led_panel import LEDPanel
from domain.realsense_utils import sample_all_neighborhood_brightness


class SessionEngineThread(QThread):
    frame_ready = Signal(str, object, int, object)
    row_ready = Signal(dict)
    stats_ready = Signal(dict)
    session_finished = Signal(list)
    error = Signal(str)

    def __init__(self, ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps,
                 test_session, left_xy=None, right_xy=None, neighborhood_size=5,
                 scan_direction=None, switch_time_ms=None,
                 display_stride=10, position_gap_metric=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.device_serial = device_serial
        self.left_resolution = left_resolution
        self.left_fps = left_fps
        self.right_resolution = right_resolution
        self.right_fps = right_fps
        self.test_session = test_session
        self.left_xy = left_xy
        self.right_xy = right_xy
        self.neighborhood_size = neighborhood_size
        self.scan_direction = scan_direction
        self.switch_time_ms = switch_time_ms
        self.display_stride = display_stride
        self.position_gap_metric = position_gap_metric
        self._stop_requested = False
        self._capture = None
        self._start_time = None

    def request_stop(self):
        self._stop_requested = True

    def _frame_pairs_with_brightness(self):
        for left_image, right_image, left_ts_us, right_ts_us in self._capture.frames():
            left_bright = (
                sample_all_neighborhood_brightness(left_image, self.left_xy, self.neighborhood_size)
                if self.left_xy is not None else None
            )
            right_bright = (
                sample_all_neighborhood_brightness(right_image, self.right_xy, self.neighborhood_size)
                if self.right_xy is not None else None
            )
            yield left_image, right_image, left_ts_us, right_ts_us, left_bright, right_bright

    def run(self):
        import time

        try:
            color_sensor = get_color_sensor_for_device(self.ctx, self.device_serial)
            if not enable_auto_exposure(color_sensor):
                self.error.emit("This sensor/firmware does not expose enable_auto_exposure - confirm auto-exposure is on manually.")

            if self.switch_time_ms is not None:
                LEDPanel.stop()
                LEDPanel.response_time_measurement_mode()
                LEDPanel.set_direction_single(self.scan_direction if self.scan_direction is not None else 1)
                LEDPanel.set_speed_ms(self.switch_time_ms)
                LEDPanel.start()

            self._capture = ContinuousCapture(self.left_resolution, self.left_fps, self.right_resolution, self.right_fps)
            self._capture.start()
            self._start_time = time.time()

            def on_frames(left_image, right_image, pair_index):
                if self.position_gap_metric is not None:
                    left_mask = self.position_gap_metric.last_left_on_mask
                    right_mask = self.position_gap_metric.last_right_on_mask
                    left_mask = left_mask.copy() if left_mask is not None else None
                    right_mask = right_mask.copy() if right_mask is not None else None
                else:
                    left_mask = right_mask = None
                self.frame_ready.emit("left", left_image, pair_index, left_mask)
                self.frame_ready.emit("right", right_image, pair_index, right_mask)

            def on_row(row):
                self.row_ready.emit(row)

            def on_stats(stats):
                self.stats_ready.emit(stats)

            callbacks = AcquisitionCallbacks(on_frames=on_frames, on_row=on_row, on_stats=on_stats)
            loop = AcquisitionLoop(
                self._frame_pairs_with_brightness(), self.test_session, callbacks,
                display_stride=self.display_stride,
            )
            rows = loop.run_until_stopped(
                is_stop_requested=lambda: self._stop_requested,
                elapsed_s_fn=lambda: time.time() - self._start_time,
            )
            self.session_finished.emit(rows)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if self._capture is not None:
                self._capture.stop()
            try:
                LEDPanel.stop()
            except Exception as exc:
                self.error.emit("Failed to stop LED panel during cleanup: {}".format(exc))
```

- [ ] **Step 2: Manual sanity check (no automated test — hardware-facing)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from engine.session_engine import SessionEngineThread"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add engine/session_engine.py
git commit -m "feat: rename session engine thread to left/right"
```

---

### Task 13: `gui/pages/live_session_page.py` — left/right video panels, plots, stats

**Files:**
- Modify: `gui/pages/live_session_page.py`
- Test: `tests/gui/pages/test_live_session_page.py`

**Interfaces:**
- Consumes: `engine.session_engine.SessionEngineThread` (Task 12), `engine.metrics.PairingGapMetric`/`PositionGapMetric` (Task 5), `domain.realsense_utils.draw_led_state_overlay`/`crop_to_roi` (unchanged)
- Produces: `LiveSessionPage.set_context(ctx, device_serial, left_resolution, left_fps, right_resolution, right_fps, switch_time_ms, scan_direction, left_threshold, right_threshold, left_xy, right_xy, num_leds, neighborhood_size, frame_drop_threshold_factor, warmup_pairs_to_skip, pairing_gap_outlier_threshold_us, kept_csv_path, dropped_csv_path, output_dir, snapshot_every_n_pairs, max_snapshots, left_roi, right_roi, camera_name)`, `.left_panel`/`.right_panel`, `_short_camera_name` unchanged.

This is a systematic rename of every `ir_`/`rgb_` identifier to `left_`/`right_` throughout the file — the frame-drop/stats/plot logic itself is unchanged. Apply this exact mapping everywhere it appears in `gui/pages/live_session_page.py`:

| Old | New |
|---|---|
| `self.ir_panel` / `self.rgb_panel` | `self.left_panel` / `self.right_panel` |
| `self.ir_title_label` / `self.rgb_title_label` | `self.left_title_label` / `self.right_title_label` |
| `"IR Camera"` / `"RGB Camera"` (placeholder text) | `"Left Camera"` / `"Right Camera"` |
| `"{} - IR"` / `"{} - RGB"` (in `set_context`) | `"{} - Left"` / `"{} - Right"` |
| `self._ir_drop_count` / `self._rgb_drop_count` | `self._left_drop_count` / `self._right_drop_count` |
| `self._ir_drop_since_last_plot` / `self._rgb_drop_since_last_plot` | `self._left_drop_since_last_plot` / `self._right_drop_since_last_plot` |
| `self._last_ir_image` / `self._last_rgb_image` | `self._last_left_image` / `self._last_right_image` |
| `self._last_ir_on_mask` / `self._last_rgb_on_mask` | `self._last_left_on_mask` / `self._last_right_on_mask` |
| `"Frame drops (IR/RGB)"` checkbox label | `"Frame drops (Left/Right)"` |
| `"ir_frame_drops"` / `"rgb_frame_drops"` series keys | `"left_frame_drops"` / `"right_frame_drops"` |
| `"Frame Drops (IR up / RGB down)"` axis label | `"Frame Drops (Left up / Right down)"` |
| `"IR Frame Drops"` / `"RGB Frame Drops"` stat tile labels | `"Left Frame Drops"` / `"Right Frame Drops"` |
| `set_context(..., ir_resolution, ir_fps, color_resolution, color_fps, ..., ir_threshold, rgb_threshold, ir_xy, rgb_xy, ..., ir_roi, rgb_roi, ...)` | `set_context(..., left_resolution, left_fps, right_resolution, right_fps, ..., left_threshold, right_threshold, left_xy, right_xy, ..., left_roi, right_roi, ...)` |
| `ctx["ir_fps"]` / `ctx["color_fps"]` (in `start_session`'s `PositionGapMetric(...)` call) | `ctx["left_fps"]` / `ctx["right_fps"]` |
| `stream_name == "ir"` checks in `_on_frame_ready`/`_crop_to_roi_if_available`/`_overlay_xy` | `stream_name == "left"` |
| `row.get("ir_frame_drop")` / `row.get("rgb_frame_drop")` | `row.get("left_frame_drop")` / `row.get("right_frame_drop")` |
| `"periodic_led_state_ir_pair{:05d}.png"` / `"...rgb_pair..."` | `"periodic_led_state_left_pair{:05d}.png"` / `"...right_pair..."` |
| `"live_led_state_ir.png"` / `"live_led_state_rgb.png"` | `"live_led_state_left.png"` / `"live_led_state_right.png"` |
| `SessionEngineThread(ctx["ctx"], ..., ctx["ir_resolution"], ctx["ir_fps"], ctx["color_resolution"], ctx["color_fps"], ..., ir_xy=ctx["ir_xy"], rgb_xy=ctx["rgb_xy"], ...)` | `SessionEngineThread(ctx["ctx"], ..., ctx["left_resolution"], ctx["left_fps"], ctx["right_resolution"], ctx["right_fps"], ..., left_xy=ctx["left_xy"], right_xy=ctx["right_xy"], ...)` |

`pairing_gap_us`/`position_gap_ms` metric names, `_hw_ts_latency_stats`/`_optical_sync_stats`, `_short_camera_name`, `_build_copy_icon`, `_make_chart_header`, `_copy_chart_image`, `_export_chart_csv`, `_reexport_last_session_csvs`, `_push_running_stats`, `_on_stats_ready`, `_on_session_finished`, `_on_engine_thread_finished`, `_on_error` are **unchanged** — none of them reference `ir`/`rgb` naming.

- [ ] **Step 1: Write the failing test file**

```python
# tests/gui/pages/test_live_session_page.py
import os
from unittest.mock import MagicMock, patch

import numpy as np

from gui.pages.live_session_page import LiveSessionPage, _short_camera_name


def test_short_camera_name_returns_model_designator():
    assert _short_camera_name("Intel RealSense D585") == "D585"


def test_short_camera_name_handles_single_word_input():
    assert _short_camera_name("D585") == "D585"


def test_short_camera_name_handles_empty_string():
    assert _short_camera_name("") == ""


def _minimal_context(tmp_path, **overrides):
    ctx = dict(
        ctx=None, device_serial="123456", left_resolution=(4, 4), left_fps=30,
        right_resolution=(4, 4), right_fps=30, switch_time_ms=1.0, scan_direction=1,
        left_threshold=np.full(2, 150.0), right_threshold=np.full(2, 150.0),
        left_xy=np.array([(1, 1), (2, 2)]), right_xy=np.array([(1, 1), (2, 2)]),
        num_leds=2, neighborhood_size=5, frame_drop_threshold_factor=1.5,
        warmup_pairs_to_skip=0, pairing_gap_outlier_threshold_us=100000,
        kept_csv_path=str(tmp_path / "kept.csv"), dropped_csv_path=str(tmp_path / "dropped.csv"),
        output_dir=str(tmp_path), snapshot_every_n_pairs=20, max_snapshots=2,
        left_roi=(0, 0, 4, 4), right_roi=(0, 0, 4, 4), camera_name="Intel RealSense D585",
    )
    ctx.update(overrides)
    return ctx


def _page_with_frame_data(qapp, tmp_path, **context_overrides):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, **context_overrides))
    page._last_left_image = np.zeros((4, 4, 3), dtype=np.uint8)
    page._last_right_image = np.zeros((4, 4, 3), dtype=np.uint8)
    page._last_left_on_mask = np.array([True, False])
    page._last_right_on_mask = np.array([True, False])
    return page


def test_maybe_save_periodic_snapshot_skips_when_pair_index_not_a_multiple(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path)

    page._maybe_save_periodic_snapshot(pair_index=7)  # 7 % 20 != 0

    assert page._periodic_snapshot_count == 0
    assert not os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_left_pair00007.png"))


def test_maybe_save_periodic_snapshot_saves_on_multiple_of_every_n(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path)

    page._maybe_save_periodic_snapshot(pair_index=20)

    assert page._periodic_snapshot_count == 1
    assert os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_left_pair00020.png"))
    assert os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_right_pair00020.png"))


def test_maybe_save_periodic_snapshot_stops_after_max_snapshots(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path, max_snapshots=1)

    page._maybe_save_periodic_snapshot(pair_index=0)
    page._maybe_save_periodic_snapshot(pair_index=20)

    assert page._periodic_snapshot_count == 1
    assert not os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_left_pair00020.png"))


def test_maybe_save_periodic_snapshot_noop_without_context(qapp):
    page = LiveSessionPage()

    page._maybe_save_periodic_snapshot(pair_index=0)

    assert page._periodic_snapshot_count == 0


def test_maybe_save_periodic_snapshot_noop_when_every_n_is_zero(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path, snapshot_every_n_pairs=0)

    page._maybe_save_periodic_snapshot(pair_index=0)

    assert page._periodic_snapshot_count == 0


def test_crop_to_roi_if_available_returns_image_unchanged_without_context(qapp):
    page = LiveSessionPage()
    image = np.zeros((4, 4, 3), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "left")

    assert result is image


def test_crop_to_roi_if_available_returns_image_unchanged_for_zero_size_roi(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, left_roi=(0, 0, 0, 0)))
    image = np.zeros((4, 4, 3), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "left")

    assert result is image


def test_crop_to_roi_if_available_crops_when_roi_present(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, left_roi=(1, 1, 2, 2)))
    image = np.zeros((4, 4, 3), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "left")

    assert result.shape == (2, 2, 3)


def test_crop_to_roi_if_available_uses_right_roi_for_right_stream(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, left_roi=(0, 0, 0, 0), right_roi=(1, 1, 3, 3)))
    image = np.zeros((4, 4, 3), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "right")

    assert result.shape == (3, 3, 3)


class _FakeEngineThread:
    last_kwargs = None

    def __init__(self, *args, **kwargs):
        _FakeEngineThread.last_kwargs = kwargs
        self.frame_ready = MagicMock()
        self.row_ready = MagicMock()
        self.stats_ready = MagicMock()
        self.session_finished = MagicMock()
        self.error = MagicMock()
        self.finished = MagicMock()

    def start(self):
        pass

    def wait(self):
        pass


def test_set_context_prefills_switch_time_spinbox_from_settings_value(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, switch_time_ms=7))
    assert page.switch_time_spinbox.value() == 7


def test_start_session_passes_toolbar_switch_time_and_frame_sample_interval(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, switch_time_ms=1))
    page.switch_time_spinbox.setValue(42)
    page.frame_sample_interval_spinbox.setValue(99)

    with patch("gui.pages.live_session_page.SessionEngineThread", _FakeEngineThread):
        page.start_session()

    assert _FakeEngineThread.last_kwargs["switch_time_ms"] == 42
    assert _FakeEngineThread.last_kwargs["display_stride"] == 99


def test_start_session_locks_duration_switch_time_and_frame_sample_interval(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path))

    with patch("gui.pages.live_session_page.SessionEngineThread", _FakeEngineThread):
        page.start_session()

    assert not page.duration_spinbox.isEnabled()
    assert not page.switch_time_spinbox.isEnabled()
    assert not page.frame_sample_interval_spinbox.isEnabled()

    page._on_engine_thread_finished()

    assert page.duration_spinbox.isEnabled()
    assert page.switch_time_spinbox.isEnabled()
    assert page.frame_sample_interval_spinbox.isEnabled()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_live_session_page.py -v`
Expected: FAIL (`set_context` still takes `ir_resolution`/`rgb_roi`/etc.; `page._last_left_image` doesn't exist yet).

- [ ] **Step 3: Apply the rename table above throughout `gui/pages/live_session_page.py`**

Apply every row of the mapping table exactly (including the docstring's `"IR Camera"`/`"RGB Camera"` region, `_on_frame_ready`, `_crop_to_roi_if_available`, `_overlay_xy`, `_maybe_save_periodic_snapshot`, `_save_led_state_debug_images`, `start_session`, `set_context`, `__init__`'s instance attributes, and the video-row/checkbox/plot construction in `__init__`). No other logic changes.

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/gui/pages/test_live_session_page.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add gui/pages/live_session_page.py tests/gui/pages/test_live_session_page.py
git commit -m "feat: rename Live Session page to left/right video panels, plots, stats"
```

---

### Task 14: `gui/main_window.py` — rewire the whole wizard

**Files:**
- Modify: `gui/main_window.py` (no test file — top-level hardware-facing wiring, matches convention)

**Interfaces:**
- Consumes: `engine.streams.get_color_sensor_for_device` (Task 3), `state.gui_state.GuiState` with left/right fields (Task 7), `settings.yaml`'s `camera.left`/`camera.right` (Task 7), every page's renamed `populate`/`set_context` signatures (Tasks 8-13)

- [ ] **Step 1: Rewrite `gui/main_window.py`**

```python
"""Wizard shell: Device select -> Stream config -> ROI select ->
Calibration -> Live session, in a QStackedWidget, persisting choices to
state.gui_state as the user moves through the wizard."""

import os

import numpy as np
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QMessageBox

from gui.pages.device_select_page import DeviceSelectPage
from gui.pages.stream_config_page import StreamConfigPage
from gui.pages.roi_select_page import RoiSelectPage
from gui.pages.calibration_page import CalibrationPage
from gui.pages.live_session_page import LiveSessionPage
from state.gui_state import GuiState, save_gui_state
from engine.streams import get_color_sensor_for_device
from domain.calibration import load_led_positions
from settings import ensure_output_dir


class MainWindow(QMainWindow):
    def __init__(self, ctx, gui_state: GuiState, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Optical Sync GUI - D585")
        self.ctx = ctx
        self.gui_state = gui_state
        self.settings = settings

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.device_page = DeviceSelectPage()
        self.stream_config_page = StreamConfigPage()
        self.roi_page = RoiSelectPage()
        self.calibration_page = CalibrationPage()
        self.live_session_page = LiveSessionPage()
        self._device_name = None

        for page in (self.device_page, self.stream_config_page, self.roi_page,
                     self.calibration_page, self.live_session_page):
            self.stack.addWidget(page)

        self.device_page.device_chosen.connect(self._on_device_chosen)
        self.stream_config_page.config_chosen.connect(self._on_config_chosen)
        self.roi_page.roi_chosen.connect(self._on_roi_chosen)
        self.calibration_page.calibration_done.connect(self._on_calibration_done)

        self.device_page.refresh_devices(self.ctx)
        self.stack.setCurrentWidget(self.device_page)

    def _on_device_chosen(self, serial, name):
        self.gui_state.device_serial = serial
        self._device_name = name
        save_gui_state(self.gui_state)
        color_sensor = get_color_sensor_for_device(self.ctx, serial)
        camera_settings = self.settings["camera"]
        preferred_left = (camera_settings["left"]["width"], camera_settings["left"]["height"], camera_settings["left"]["fps"])
        preferred_right = (
            camera_settings["right"]["width"], camera_settings["right"]["height"], camera_settings["right"]["fps"],
        )
        self.stream_config_page.populate(self.ctx, serial, color_sensor, preferred_left, preferred_right)
        self.stack.setCurrentWidget(self.stream_config_page)

    def _on_config_chosen(self, config):
        left_width, left_height, left_fps, right_width, right_height, right_fps = config
        self.gui_state.left_width, self.gui_state.left_height, self.gui_state.left_fps = left_width, left_height, left_fps
        self.gui_state.right_width, self.gui_state.right_height, self.gui_state.right_fps = right_width, right_height, right_fps
        save_gui_state(self.gui_state)
        self.roi_page.set_context(
            self.ctx, self.gui_state.device_serial,
            (left_width, left_height), left_fps, (right_width, right_height), right_fps,
            settle_frames=self.settings["calibration"]["settle_frames"],
        )
        self.stack.setCurrentWidget(self.roi_page)

    def _on_roi_chosen(self, rois):
        left_roi, right_roi = rois
        self.gui_state.left_roi = list(left_roi)
        self.gui_state.right_roi = list(right_roi)
        save_gui_state(self.gui_state)
        calib_settings = self.settings["calibration"]
        self.calibration_page.set_context(
            self.ctx, self.gui_state.device_serial,
            (self.gui_state.left_width, self.gui_state.left_height), self.gui_state.left_fps,
            (self.gui_state.right_width, self.gui_state.right_height), self.gui_state.right_fps,
            left_roi, right_roi,
            config_path=self.settings["paths"]["config_path"],
            camera_name=self._current_device_name(),
            output_dir=ensure_output_dir(self.settings),
            settle_frames=calib_settings["settle_frames"],
            min_blob_area=calib_settings["min_blob_area"],
            neighborhood_size=calib_settings["neighborhood_size"],
            row_gap_px=calib_settings["row_gap_px"],
            min_acceptable_contrast=calib_settings["min_acceptable_contrast"],
        )
        self.stack.setCurrentWidget(self.calibration_page)

    def _on_calibration_done(self):
        camera_name = self._current_device_name()
        config_path = self.settings["paths"]["config_path"]
        left_positions, right_positions = load_led_positions(config_path, camera_name)

        left_ids = list(left_positions.keys())
        right_ids = list(right_positions.keys())
        left_xy = np.array([left_positions[i][:2] for i in left_ids])
        right_xy = np.array([right_positions[i][:2] for i in right_ids])

        num_leds = self.settings["test"]["num_leds"]
        if len(left_ids) != len(right_ids) or len(left_ids) != num_leds:
            QMessageBox.warning(
                self,
                "LED count mismatch",
                "Calibration detected {} Left LED(s) and {} Right LED(s), but settings.yaml's "
                "test.num_leds is {}. The live session's position-gap math assumes all three "
                "match - proceeding anyway, but treat position-gap results with caution until "
                "this is resolved (re-run calibration, or fix test.num_leds).".format(
                    len(left_ids), len(right_ids), num_leds
                ),
            )

        left_on = np.array([left_positions[i][2] for i in left_ids])
        left_off = np.array([left_positions[i][3] for i in left_ids])
        right_on = np.array([right_positions[i][2] for i in right_ids])
        right_off = np.array([right_positions[i][3] for i in right_ids])

        threshold_fraction = self.settings["test"]["threshold_fraction"]
        left_threshold = left_off + threshold_fraction * (left_on - left_off)
        right_threshold = right_off + threshold_fraction * (right_on - right_off)

        output_dir = ensure_output_dir(self.settings)
        self.live_session_page.set_context(
            self.ctx, self.gui_state.device_serial,
            (self.gui_state.left_width, self.gui_state.left_height), self.gui_state.left_fps,
            (self.gui_state.right_width, self.gui_state.right_height), self.gui_state.right_fps,
            switch_time_ms=self.settings["test"]["switch_time_ms"],
            scan_direction=self.settings["test"]["scan_direction"],
            left_threshold=left_threshold, right_threshold=right_threshold, left_xy=left_xy, right_xy=right_xy,
            num_leds=num_leds, neighborhood_size=self.settings["test"]["neighborhood_size"],
            frame_drop_threshold_factor=self.settings["test"]["frame_drop_threshold_factor"],
            warmup_pairs_to_skip=self.settings["test"]["warmup_pairs_to_skip"],
            pairing_gap_outlier_threshold_us=self.settings["test"]["pairing_gap_outlier_threshold_us"],
            kept_csv_path=os.path.join(output_dir, self.settings["paths"]["raw_csv_path"]),
            dropped_csv_path=os.path.join(output_dir, self.settings["paths"]["frame_drop_csv_path"]),
            output_dir=output_dir,
            snapshot_every_n_pairs=self.settings["test"]["snapshot_every_n_pairs"],
            max_snapshots=self.settings["test"]["max_snapshots"],
            left_roi=self.gui_state.left_roi, right_roi=self.gui_state.right_roi, camera_name=camera_name,
        )
        self.stack.setCurrentWidget(self.live_session_page)

    def _current_device_name(self):
        return self._device_name
```

- [ ] **Step 2: Manual sanity check (no automated test — top-level wiring)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "from gui.main_window import MainWindow"`
Expected: no exception.

- [ ] **Step 3: Commit**

```bash
git add gui/main_window.py
git commit -m "feat: rewire MainWindow for left/right pages and D585 device flow"
```

---

### Task 15: Docs — `CLAUDE.md` and `README.md`

**Files:**
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Rewrite `CLAUDE.md`**

Replace the "What this is" section to describe D585 left/right color-vs-color sync measurement instead of IR/RGB, referencing `engine/rgb_mode.py`'s Dedicated/Dual RGB PID distinction and why it exists. Update the "Architecture" section's layering description to name `engine/rgb_mode.py` alongside `engine/streams.py`/`engine/led_panel.py`, and update the "Naming" section to state that `left`/`right` are used consistently at every layer now (no UI-label/data-key split needed, since there's no IR-vs-RGB naming mismatch left to paper over). Update "Configuration files" to describe `config.yaml`'s `left`/`right` keys and `settings.yaml`'s `camera.left`/`camera.right`. Remove the "Live Session pipeline" section's IR/RGB-specific references (`ir_panel`/`rgb_panel` → `left_panel`/`right_panel`) and the `gui/widgets/live_plot.py` gotcha section stays as-is (unrelated to this rename).

- [ ] **Step 2: Rewrite `README.md`**

Replace "A PySide6 desktop app for measuring IR/RGB timing sync..." with a description of measuring sync between the D585's left/right color sensors via Dual RGB mode. Update the Features list's "Device selection" bullet to describe D535/D585 PID-based listing and the automatic Dedicated→Dual RGB switch. Update "Stream configuration"/"ROI selection"/"LED calibration"/"Live sync session" bullets to say Left/Right instead of IR/RGB. Update the wizard walkthrough steps 2-5 similarly. Add a new prerequisite bullet: "The device must support Dual RGB mode (D535/D585 PID) — Device Select switches it automatically if it's currently in Dedicated RGB mode." Reference `d585_dual_rgb_mode.py` as prior art for the mode-switch mechanism, without re-describing the PID/register details already covered in `CLAUDE.md`.

- [ ] **Step 3: Full test suite sanity check**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -v`
Expected: PASS (all tests — docs changes don't affect test collection, this just confirms nothing else broke).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: rewrite CLAUDE.md and README.md for D585 left/right architecture"
```

---

### Task 16: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test suite from a clean venv**

```bash
cd "/c/Users/gbaruch/scripts/Optical Sync/optical_sync_gui_d585"
rm -rf .venv
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -v
```

Expected: PASS (every test across `tests/domain/`, `tests/engine/`, `tests/state/`, `tests/gui/` — including the new `test_rgb_mode.py` and `test_device_select_page.py`).

- [ ] **Step 2: Grep for any remaining `ir_`/`rgb_` leftovers**

```bash
grep -rn "ir_\|rgb_\|_ir\b\|_rgb\b" --include="*.py" --include="*.yaml" . \
  | grep -v ".git/" | grep -v "\.venv/"
```

Expected: no matches outside of comments/docstrings referencing the original `optical_sync_gui` project by name (e.g. a "forked from" note) — if any real code/config identifier still uses `ir_`/`rgb_`, go back and rename it in the relevant task above.

- [ ] **Step 3: Commit final verification note (only if Step 2 found and fixed something)**

```bash
git add -A
git commit -m "fix: catch remaining ir/rgb naming leftovers"
```

If Step 2 found nothing, no commit is needed — the fork is complete as of Task 15's commit.
