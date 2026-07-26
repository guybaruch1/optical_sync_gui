from gui.widgets.dual_axis_live_plot import DualAxisLivePlot


def test_left_and_right_series_accumulate_independently(qapp):
    plot = DualAxisLivePlot()
    plot.add_left_series("pairing_gap_us", color="r")
    plot.add_right_series("frame_drops", color="y")

    plot.add_point("pairing_gap_us", 0, 12.5)
    plot.add_point("pairing_gap_us", 1, -3.0)
    plot.add_point("frame_drops", 0, 0)
    plot.add_point("frame_drops", 1, 1)

    assert plot.get_series_data("pairing_gap_us") == ([0, 1], [12.5, -3.0])
    assert plot.get_series_data("frame_drops") == ([0, 1], [0, 1])


def test_is_right_series_distinguishes_axis_assignment(qapp):
    plot = DualAxisLivePlot()
    plot.add_left_series("pairing_gap_us", color="r")
    plot.add_right_series("frame_drops", color="y")

    assert plot.is_right_series("pairing_gap_us") is False
    assert plot.is_right_series("frame_drops") is True
