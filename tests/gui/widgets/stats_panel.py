"""Generic live key/value readout list - frame index, HW timestamp gap,
LED switch_time_ms today; add_field lets future callers register more
stats fields without changing this widget."""

from PySide6.QtWidgets import QWidget, QFormLayout, QLabel


class StatsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._value_labels = {}

    def add_field(self, key, label):
        value_label = QLabel("-")
        self._value_labels[key] = value_label
        self._layout.addRow(QLabel(label), value_label)

    def set_value(self, key, value):
        if key not in self._value_labels:
            return
        self._value_labels[key].setText(str(value))
