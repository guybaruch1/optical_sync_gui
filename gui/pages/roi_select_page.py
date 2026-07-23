"""Wizard step 3: live preview of both sensors, drag a box on each to
pick its ROI - replaces optical_sync_poc_/roi_picker.py's cv2.selectROI
popup with an in-app rubber-band selection over a live feed."""

from PySide6.QtCore import Signal, Qt, QRect
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRubberBand

from gui.widgets.video_panel import VideoPanel
from engine.session_engine import SessionEngineThread
from engine.test_session import TestSession, TestSessionConfig


class _DraggableVideoPanel(VideoPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self)
        self._origin = None
        self.roi = None

    def mousePressEvent(self, event):
        self._origin = event.pos()
        self._rubber_band.setGeometry(QRect(self._origin, event.pos()))
        self._rubber_band.show()

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self._rubber_band.setGeometry(QRect(self._origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        if self._origin is not None:
            rect = QRect(self._origin, event.pos()).normalized()
            self.roi = (rect.x(), rect.y(), rect.width(), rect.height())
            self._origin = None


class RoiSelectPage(QWidget):
    roi_chosen = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine_thread = None

        layout = QVBoxLayout(self)
        video_row = QHBoxLayout()
        self.ir_panel = _DraggableVideoPanel()
        self.rgb_panel = _DraggableVideoPanel()
        video_row.addWidget(self.ir_panel)
        video_row.addWidget(self.rgb_panel)
        layout.addLayout(video_row)
        layout.addWidget(QLabel("Drag a box on each preview to set its ROI, then click Next."))
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._on_next_clicked)
        layout.addWidget(self.next_button)

    def start_preview(self, ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps):
        test_session = TestSession(TestSessionConfig(metrics=[]))
        test_session.start()
        self.engine_thread = SessionEngineThread(
            ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps, test_session,
        )
        self.engine_thread.frame_ready.connect(self._on_frame_ready)
        self.engine_thread.start()

    def stop_preview(self):
        if self.engine_thread is not None:
            self.engine_thread.request_stop()
            self.engine_thread.wait()
            self.engine_thread = None

    def _on_frame_ready(self, stream_name, image):
        if stream_name == "ir":
            self.ir_panel.set_frame(image)
        else:
            self.rgb_panel.set_frame(image)

    def _on_next_clicked(self):
        if self.ir_panel.roi is not None and self.rgb_panel.roi is not None:
            self.stop_preview()
            self.roi_chosen.emit((self.ir_panel.roi, self.rgb_panel.roi))
