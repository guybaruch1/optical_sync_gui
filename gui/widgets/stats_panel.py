"""Generic live key/value readout, rendered as individual "stat tile"
cards grouped under section headers (e.g. "Live Data", "Stats") - matches
the Optical Sync GUI design mockup (claude.ai/design project "GUI layout
redesign options", file Optical Sync GUI.dc.html). add_field/set_value
keep the same signatures as before so callers don't need to change;
add_section_header is new."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QSizePolicy

SECTION_HEADER_STYLE = (
    "color: #555555; font-weight: 600; font-size: 10pt;"
    "text-transform: uppercase; letter-spacing: 1px; border: none; background: transparent;"
)
TILE_STYLE = "background-color: #ffffff; border: 1px solid #e3e1db; border-radius: 6px;"
TILE_LABEL_STYLE = (
    "color: #555555; font-weight: 600; font-size: 9pt;"
    "text-transform: uppercase; letter-spacing: 1px; border: none; background: transparent;"
)
TILE_VALUE_STYLE = "color: #1b7a63; font-weight: 700; font-size: 15pt; border: none; background: transparent;"


class StatsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self._value_labels = {}

    def add_section_header(self, text):
        header = QLabel(text)
        header.setStyleSheet(SECTION_HEADER_STYLE)
        self._layout.addWidget(header)

    def add_field(self, key, label):
        tile = QFrame()
        tile.setStyleSheet(TILE_STYLE)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(10, 8, 10, 8)
        tile_layout.setSpacing(2)

        label_widget = QLabel(label)
        label_widget.setStyleSheet(TILE_LABEL_STYLE)
        value_widget = QLabel("-")
        value_widget.setStyleSheet(TILE_VALUE_STYLE)
        tile_layout.addWidget(label_widget)
        tile_layout.addWidget(value_widget)

        self._value_labels[key] = value_widget
        self._layout.addWidget(tile)

    def set_value(self, key, value):
        if key not in self._value_labels:
            return
        self._value_labels[key].setText(str(value))
