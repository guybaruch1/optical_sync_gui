"""Wizard step 3: same ROI-selection approach as
optical_sync_poc_/roi_picker.py - capture one settled frame per sensor
with all LEDs lit (for visibility), then use cv2.selectROI's native popup
window to draw each box directly in image pixel space.

Chosen over an embedded Qt drag-and-drop over a live QLabel preview: that
approach required converting a rubber-band selection from on-screen widget
pixels back to native image pixels (the widget is stretched to whatever
size the layout gives it), and that conversion turned out to be a real
source of bugs in practice. cv2.selectROI sidesteps the whole problem -
it returns coordinates in the same array passed to it, regardless of how
its own window is sized/zoomed on screen, exactly like the original
standalone script relied on.
"""

import time

import cv2
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from engine.streams import (
    ContinuousCapture, disable_ir_emitter, enable_auto_exposure, get_sensors_for_device,
    capture_settled_frame_pair,
)
from engine.led_panel import LEDPanel


def _select_roi(image, window_title):
    """Interactive ROI selection via a native OpenCV popup window. Returns
    (x, y, w, h) in the given image's own pixel coordinates, or None if
    cancelled (Enter=confirm, C=cancel, matching the original script)."""
    display = image
    if len(image.shape) == 2:  # IR is single-channel; selectROI wants something displayable
        display = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    x, y, w, h = map(int, cv2.selectROI(window_title, display, showCrosshair=True, fromCenter=False))
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

    def set_context(self, ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps,
                    settle_frames=15):
        self._pending_args = dict(
            ctx=ctx, device_serial=device_serial, ir_resolution=ir_resolution, ir_fps=ir_fps,
            color_resolution=color_resolution, color_fps=color_fps, settle_frames=settle_frames,
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

    def _capture_and_select(self, ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps,
                            settle_frames):
        stereo_sensor, rgb_sensor = get_sensors_for_device(ctx, device_serial)
        if not disable_ir_emitter(stereo_sensor):
            self.status_label.setText(
                "WARNING: emitter_enabled not supported - confirm the IR projector is off manually."
            )
        enable_auto_exposure(rgb_sensor)

        capture = ContinuousCapture(ir_resolution, ir_fps, color_resolution, color_fps)
        capture.start()
        try:
            frame_iter = capture.frames()
            LEDPanel.stop()
            LEDPanel.all_leds_on()
            time.sleep(0.5)  # let the panel actually reach full brightness
            # See engine.streams.capture_settled_frame_pair's docstring: the
            # very next frame off the pipeline can still be stale or
            # mid-auto-exposure-adjustment, so wait for settle_frames fresh
            # ones instead of trusting the first one after a fixed sleep.
            ir_image, rgb_image, _, _ = capture_settled_frame_pair(frame_iter, settle_frames)
        finally:
            capture.stop()
            LEDPanel.all_leds_off()

        ir_roi = _select_roi(ir_image, "IR - drag ROI, Enter=OK, C=Cancel")
        if ir_roi is None:
            self.status_label.setText("IR ROI selection cancelled - try again.")
            return

        rgb_roi = _select_roi(rgb_image, "RGB - drag ROI, Enter=OK, C=Cancel")
        if rgb_roi is None:
            self.status_label.setText("RGB ROI selection cancelled - try again.")
            return

        self.status_label.setText("ROI selected: IR={} RGB={}".format(ir_roi, rgb_roi))
        self.roi_chosen.emit((ir_roi, rgb_roi))
