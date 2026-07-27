from domain.running_stats import RunningStats


def test_empty_stats_summary_is_dash():
    stats = RunningStats()
    assert stats.summary_text() == "-"


def test_mean_of_single_value():
    stats = RunningStats()
    stats.update(10.0)
    assert stats.mean == 10.0
    assert stats.std == 0.0
    assert stats.extreme == 10.0


def test_mean_and_std_match_known_values():
    stats = RunningStats()
    for value in (2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0):
        stats.update(value)
    assert stats.count == 8
    assert stats.mean == 5.0
    assert round(stats.std, 4) == 2.0


def test_extreme_is_largest_magnitude_sign_preserved():
    stats = RunningStats()
    for value in (-37.0, -38.5, -40.0, -36.0):
        stats.update(value)
    assert stats.extreme == -40.0


def test_extreme_prefers_large_positive_over_smaller_negative():
    stats = RunningStats()
    stats.update(-5.0)
    stats.update(12.0)
    assert stats.extreme == 12.0


def test_summary_text_formats_mean_std_extreme():
    stats = RunningStats()
    stats.update(-38.0)
    stats.update(-40.0)
    assert stats.summary_text() == "-39.0 / 1.0 / -40.0"
