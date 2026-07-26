"""Live scrolling plot with two independently-scaled y-axes sharing one
x-axis - unlike LivePlot (one shared y-axis for all series), this lets a
very different-magnitude series (e.g. a timing delta in microseconds and
a small integer drop count) be read together on one chart, correlated
against the same x-axis, using pyqtgraph's linked-ViewBox pattern for a
second y-axis."""

import pyqtgraph as pg
from PySide6.QtWidgets import QSizePolicy


class DualAxisLivePlot(pg.PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 150)
        self.showGrid(x=True, y=True, alpha=0.3)

        self.showAxis("right")
        self._right_viewbox = pg.ViewBox()
        self.scene().addItem(self._right_viewbox)
        self.getAxis("right").linkToView(self._right_viewbox)
        self._right_viewbox.setXLink(self.getPlotItem())
        self.getPlotItem().vb.sigResized.connect(self._sync_right_viewbox)

        self._curves = {}
        self._x_data = {}
        self._y_data = {}
        self._right_series = set()

    def _sync_right_viewbox(self):
        self._right_viewbox.setGeometry(self.getPlotItem().vb.sceneBoundingRect())
        self._right_viewbox.linkedViewChanged(self.getPlotItem().vb, self._right_viewbox.XAxis)

    def set_left_label(self, text):
        self.setLabel("left", text)

    def set_right_label(self, text):
        self.setLabel("right", text)

    def add_left_series(self, name, color):
        curve = self.plot([], [], pen=pg.mkPen(color=color, width=2), name=name)
        self._curves[name] = curve
        self._x_data[name] = []
        self._y_data[name] = []

    def add_right_series(self, name, color):
        curve = pg.PlotCurveItem(pen=pg.mkPen(color=color, width=2))
        self._right_viewbox.addItem(curve)
        self._curves[name] = curve
        self._x_data[name] = []
        self._y_data[name] = []
        self._right_series.add(name)

    def add_point(self, name, x, y):
        self._x_data[name].append(x)
        self._y_data[name].append(y)
        self._curves[name].setData(self._x_data[name], self._y_data[name])

    def get_series_data(self, name):
        return self._x_data[name], self._y_data[name]

    def is_right_series(self, name):
        return name in self._right_series
