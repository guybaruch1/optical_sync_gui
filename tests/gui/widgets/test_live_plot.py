from gui.widgets.live_plot import LivePlot


def test_add_point_accumulates_series_data(qapp):
    plot = LivePlot()
    plot.add_series("pairing_gap_us", color="r")
    plot.add_point("pairing_gap_us", x=0, y=10.0)
    plot.add_point("pairing_gap_us", x=1, y=-5.0)

    xs, ys = plot.get_series_data("pairing_gap_us")
    assert xs == [0, 1]
    assert ys == [10.0, -5.0]


def test_set_series_visible_toggles_curve_visibility(qapp):
    plot = LivePlot()
    plot.add_series("position_gap_ms", color="g")
    plot.set_series_visible("position_gap_ms", False)
    assert plot._curves["position_gap_ms"].isVisible() is False
    plot.set_series_visible("position_gap_ms", True)
    assert plot._curves["position_gap_ms"].isVisible() is True


def test_two_independent_series_do_not_interfere(qapp):
    plot = LivePlot()
    plot.add_series("a", color="r")
    plot.add_series("b", color="b")
    plot.add_point("a", 0, 1.0)
    plot.add_point("b", 0, 99.0)
    assert plot.get_series_data("a") == ([0], [1.0])
    assert plot.get_series_data("b") == ([0], [99.0])
