"""Generic live scrolling plot, fed by named metric series (e.g. one
curve for PairingGapMetric, one for PositionGapMetric) so the GUI never
has to special-case which metrics exist - see engine.metrics.Metric."""

import pyqtgraph as pg


class LivePlot(pg.PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.showGrid(x=True, y=True, alpha=0.3)
        self._curves = {}
        self._x_data = {}
        self._y_data = {}

    def add_series(self, name, color):
        curve = self.plot([], [], pen=pg.mkPen(color=color, width=2), name=name)
        self._curves[name] = curve
        self._x_data[name] = []
        self._y_data[name] = []

    def add_point(self, name, x, y):
        self._x_data[name].append(x)
        self._y_data[name].append(y)
        self._curves[name].setData(self._x_data[name], self._y_data[name])

    def set_series_visible(self, name, visible):
        self._curves[name].setVisible(visible)

    def get_series_data(self, name):
        return self._x_data[name], self._y_data[name]
