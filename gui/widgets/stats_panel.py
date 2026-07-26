"""Generic live key/value readout list - frame index, HW timestamp gap,
LED switch_time_ms today; add_field lets future callers register more
stats fields without changing this widget."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QFormLayout, QLabel, QSizePolicy


class StatsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            "StatsPanel {"
            "  background-color: #f5f6f8;"
            "  border: 1px solid #d0d3d8;"
            "  border-radius: 8px;"
            "}"
        )
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setHorizontalSpacing(28)
        self._layout.setVerticalSpacing(16)
        self._value_labels = {}

    def add_field(self, key, label):
        label_widget = QLabel(label)
        label_widget.setFont(_label_font())
        label_widget.setStyleSheet("color: #333333; border: none;")

        value_label = QLabel("-")
        value_label.setFont(_value_font())
        value_label.setStyleSheet("color: #1a6b3c; border: none;")

        self._value_labels[key] = value_label
        self._layout.addRow(label_widget, value_label)

    def set_value(self, key, value):
        if key not in self._value_labels:
            return
        self._value_labels[key].setText(str(value))


def _label_font():
    font = QFont()
    font.setPointSize(13)
    font.setBold(True)
    return font


def _value_font():
    font = QFont()
    font.setPointSize(15)
    return font
