"""Wizard step 2: pick FPS/resolution for the IR and RGB streams."""

import pyrealsense2 as rs
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QComboBox, QPushButton

from engine.streams import list_supported_profiles


class StreamConfigPage(QWidget):
    config_chosen = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.ir_combo = QComboBox()
        self.rgb_combo = QComboBox()
        form.addRow(QLabel("IR resolution/fps:"), self.ir_combo)
        form.addRow(QLabel("RGB resolution/fps:"), self.rgb_combo)
        layout.addLayout(form)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._on_next_clicked)
        layout.addWidget(self.next_button)

    def populate(self, stereo_sensor, rgb_sensor, preferred_ir=None, preferred_rgb=None):
        """preferred_ir/preferred_rgb are optional (width, height, fps) tuples
        (e.g. from settings.yaml's camera.ir/camera.color) - if the connected
        camera actually reports that exact combo, it's pre-selected in the
        dropdown instead of leaving it at whatever comes first; the user can
        still pick something else if it doesn't suit this rig/camera."""
        ir_profiles = list_supported_profiles(stereo_sensor, rs.stream.infrared, rs.format.y8)
        rgb_profiles = list_supported_profiles(rgb_sensor, rs.stream.color, rs.format.yuyv)

        ir_profiles = [(1280, 720, 30)]
        rgb_profiles = [(1280, 720, 30)]

        self.ir_combo.clear()
        for width, height, fps in ir_profiles:
            self.ir_combo.addItem("{}x{}@{}fps".format(width, height, fps), userData=(width, height, fps))
        self._preselect(self.ir_combo, preferred_ir)

        self.rgb_combo.clear()
        for width, height, fps in rgb_profiles:
            self.rgb_combo.addItem("{}x{}@{}fps".format(width, height, fps), userData=(width, height, fps))
        self._preselect(self.rgb_combo, preferred_rgb)

    def _preselect(self, combo, preferred):
        if preferred is None:
            return
        index = combo.findData(tuple(preferred))
        if index != -1:
            combo.setCurrentIndex(index)

    def _on_next_clicked(self):
        ir_choice = self.ir_combo.currentData()
        rgb_choice = self.rgb_combo.currentData()
        if ir_choice is not None and rgb_choice is not None:
            ir_width, ir_height, ir_fps = ir_choice
            rgb_width, rgb_height, rgb_fps = rgb_choice
            self.config_chosen.emit((ir_width, ir_height, ir_fps, rgb_width, rgb_height, rgb_fps))
