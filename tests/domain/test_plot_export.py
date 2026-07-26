import os
from domain.plot_export import export_session_plot


def _row(pair_index, pairing_gap=None, position_gap=None, exclude_reason=None):
    return {
        "pair_index": pair_index,
        "pairing_gap_us": pairing_gap,
        "position_gap_ms": position_gap,
        "position_gap_ms_exclude_reason": exclude_reason,
    }


def test_export_session_plot_writes_a_file(tmp_path):
    rows = [
        _row(0, pairing_gap=10.0, position_gap=1.0),
        _row(1, pairing_gap=-5.0, position_gap=None, exclude_reason="frame_drop"),
        _row(2, pairing_gap=8.0, position_gap=2.0),
    ]
    path = str(tmp_path / "plot.png")

    export_session_plot(rows, path)

    assert os.path.exists(path)
    assert os.path.getsize(path) > 0


def test_export_session_plot_handles_empty_rows(tmp_path):
    path = str(tmp_path / "plot.png")

    export_session_plot([], path)

    assert os.path.exists(path)
