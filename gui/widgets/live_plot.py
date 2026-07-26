"""Generic live scrolling plot, fed by named metric series (e.g. one
curve for PairingGapMetric, one for PositionGapMetric) so the GUI never
has to special-case which metrics exist - see engine.metrics.Metric."""

from collections import deque

import pyqtgraph as pg
from PySide6.QtWidgets import QSizePolicy


class LivePlot(pg.PlotWidget):
    def __init__(self, parent=None, max_points=2000):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 150)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.addLegend()
        # Bounded per series (not the whole session) - add_point() used to
        # append forever and hand the ENTIRE history to setData() on every
        # single point, making one point's cost grow with how long the
        # session had been running (O(n) per call, O(n^2) over a session).
        # At 30fps unthrottled that compounds fast enough to look like the
        # app hanging on a long run. A deque caps memory AND keeps each
        # setData() call's cost constant, and incidentally makes this an
        # actual scrolling window instead of "whole history, rescaled".
        self._max_points = max_points
        self._curves = {}
        self._x_data = {}
        self._y_data = {}

    def add_series(self, name, color):
        curve = self.plot([], [], pen=pg.mkPen(color=color, width=2), name=name, connect="finite")
        self._curves[name] = curve
        self._x_data[name] = deque(maxlen=self._max_points)
        self._y_data[name] = deque(maxlen=self._max_points)

    def add_point(self, name, x, y):
        self._x_data[name].append(x)
        self._y_data[name].append(y)
        self._curves[name].setData(list(self._x_data[name]), list(self._y_data[name]))

    def set_series_visible(self, name, visible):
        self._curves[name].setVisible(visible)

    def get_series_data(self, name):
        return list(self._x_data[name]), list(self._y_data[name])
