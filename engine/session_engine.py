"""Thin QThread adapter: wires real hardware (engine.streams,
engine.led_panel) into engine.acquisition_loop.AcquisitionLoop and
translates its plain-Python callbacks into Qt signals.

Deliberately as small as possible - all the actual logic (frame-pair
processing, metric computation, session buffering) already lives in
AcquisitionLoop/TestSession/Metric, which are unit-tested without Qt or
hardware. This class exists only so that logic can run on a background
thread and reach the UI safely.
"""

from PySide6.QtCore import QThread, Signal

from engine.acquisition_loop import AcquisitionLoop, AcquisitionCallbacks
from engine.streams import ContinuousCapture, disable_ir_emitter, enable_auto_exposure, get_sensors_for_device
from engine.led_panel import LEDPanel
from domain.realsense_utils import sample_all_neighborhood_brightness


class SessionEngineThread(QThread):
    frame_ready = Signal(str, object)
    row_ready = Signal(dict)
    stats_ready = Signal(dict)
    session_finished = Signal(list)
    error = Signal(str)

    def __init__(self, ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps,
                 test_session, ir_xy=None, rgb_xy=None, neighborhood_size=5,
                 scan_direction=None, switch_time_ms=None,
                 display_stride=10, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.device_serial = device_serial
        self.ir_resolution = ir_resolution
        self.ir_fps = ir_fps
        self.color_resolution = color_resolution
        self.color_fps = color_fps
        self.test_session = test_session
        self.ir_xy = ir_xy
        self.rgb_xy = rgb_xy
        self.neighborhood_size = neighborhood_size
        self.scan_direction = scan_direction
        self.switch_time_ms = switch_time_ms
        self.display_stride = display_stride
        self._stop_requested = False
        self._capture = None
        self._start_time = None

    def request_stop(self):
        self._stop_requested = True

    def _frame_pairs_with_brightness(self):
        """Adapts ContinuousCapture.frames()'s 4-tuple (image, image, ts, ts)
        into the 6-tuple AcquisitionLoop/FramePairSample need, by sampling
        brightness at each calibrated LED position. This is deliberately done
        here, not inside ContinuousCapture itself: ContinuousCapture is a
        generic hardware-capture primitive with no notion of LED positions or
        metrics (gui/pages/calibration_page.py, a later task, consumes its raw
        4-tuple directly for exactly that reason)."""
        for ir_image, rgb_image, ir_ts_us, rgb_ts_us in self._capture.frames():
            ir_bright = (
                sample_all_neighborhood_brightness(ir_image, self.ir_xy, self.neighborhood_size)
                if self.ir_xy is not None else None
            )
            rgb_bright = (
                sample_all_neighborhood_brightness(rgb_image, self.rgb_xy, self.neighborhood_size)
                if self.rgb_xy is not None else None
            )
            yield ir_image, rgb_image, ir_ts_us, rgb_ts_us, ir_bright, rgb_bright

    def run(self):
        import time

        try:
            stereo_sensor, rgb_sensor = get_sensors_for_device(self.ctx, self.device_serial)
            if not disable_ir_emitter(stereo_sensor):
                self.error.emit("This sensor/firmware does not expose emitter_enabled - confirm the IR projector is off manually.")
            enable_auto_exposure(rgb_sensor)

            # Puts the panel into single-LED scanning mode at the configured
            # speed/direction and actually starts it moving - ported from
            # pipeline_sync_test_diff.py's main(), which does this immediately
            # before its capture loop. Without this the panel never scans at
            # all during a live session (it's left in whatever mode
            # calibration/ROI selection last put it in, typically off), so
            # PositionGapMetric would only ever see misses.
            if self.switch_time_ms is not None:
                LEDPanel.stop()
                LEDPanel.response_time_measurement_mode()
                LEDPanel.set_direction_single(self.scan_direction if self.scan_direction is not None else 1)
                LEDPanel.set_speed_ms(self.switch_time_ms)
                LEDPanel.start()

            self._capture = ContinuousCapture(self.ir_resolution, self.ir_fps, self.color_resolution, self.color_fps)
            self._capture.start()
            self._start_time = time.time()

            def on_frames(ir_image, rgb_image, pair_index):
                self.frame_ready.emit("ir", ir_image)
                self.frame_ready.emit("rgb", rgb_image)

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
        except Exception as exc:  # surfaced to the UI rather than crashing the worker thread silently
            self.error.emit(str(exc))
        finally:
            if self._capture is not None:
                self._capture.stop()
            LEDPanel.stop()
