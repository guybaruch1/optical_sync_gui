"""Static end-of-session plot export.

Matplotlib, not pyqtgraph - a live widget and a saved-file renderer are
different jobs. Restores the kind of after-the-fact plot
optical_sync_poc_/pipeline_sync_test_diff.py used to save before this
GUI's live view took over; this reads the same buffered rows
TestSession.stop() returns and domain.csv_export.export_session_csvs
writes, so it never recomputes a metric - it only re-renders numbers
that are already final.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def export_session_plot(rows, path):
    pair_indices = [row["pair_index"] for row in rows]
    pairing_gap = [_to_plot_value(row.get("pairing_gap_us")) for row in rows]
    position_gap = [_to_plot_value(row.get("position_gap_ms")) for row in rows]

    # Per-pair delta (0/1), not a running total - one spike exactly where a
    # drop happened, so it reads against the gap lines above on the same
    # x-axis instead of an ever-climbing staircase.
    dropped_this_pair = [
        1 if row.get("position_gap_ms_exclude_reason") == "frame_drop" else 0
        for row in rows
    ]

    fig, (gap_ax, drop_ax) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    gap_ax.plot(pair_indices, pairing_gap, label="Pairing gap (us)", color="tab:red")
    gap_ax.plot(pair_indices, position_gap, label="Position gap (ms)", color="tab:green")
    gap_ax.set_ylabel("Gap")
    gap_ax.legend()
    gap_ax.grid(True, alpha=0.3)

    drop_ax.plot(pair_indices, dropped_this_pair, label="Frame drop (this pair)", color="tab:orange")
    drop_ax.set_xlabel("Pair index")
    drop_ax.set_ylabel("Frame drop")
    drop_ax.legend()
    drop_ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _to_plot_value(value):
    return value if value is not None else float("nan")
