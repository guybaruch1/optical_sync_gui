"""Wizard step 5 - the live sync-test view: dual video panels, a
togglable/stacked live plot of both metrics, a live stats sidebar, and
Start/Stop with an optional fixed duration. Produces a CSV at Stop via
domain.csv_export.export_session_csvs, same spirit as
optical_sync_poc_/pipeline_sync_test_diff.py's write_raw_csvs."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox, QLabel, QCheckBox,
)

from gui.widgets.video_panel import VideoPanel
from gui.widgets.live_plot import LivePlot
from gui.widgets.stats_panel import StatsPanel
from engine.session_engine import SessionEngineThread
from engine.test_session import TestSession, TestSessionConfig
from engine.metrics import PairingGapMetric, PositionGapMetric
from domain.csv_export import export_session_csvs


class LiveSessionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine_thread = None
        self._context = None

        layout = QVBoxLayout(self)

        video_row = QHBoxLayout()
        self.ir_panel = VideoPanel()
        self.rgb_panel = VideoPanel()
        video_row.addWidget(self.ir_panel)
        video_row.addWidget(self.rgb_panel)
        layout.addLayout(video_row)

        toggle_row = QHBoxLayout()
        self.pairing_gap_checkbox = QCheckBox("Pairing gap (us)")
        self.pairing_gap_checkbox.setChecked(True)
        self.pairing_gap_checkbox.toggled.connect(
            lambda checked: self.live_plot.set_series_visible("pairing_gap_us", checked)
        )
        self.position_gap_checkbox = QCheckBox("Position gap (ms)")
        self.position_gap_checkbox.setChecked(True)
        self.position_gap_checkbox.toggled.connect(
            lambda checked: self.live_plot.set_series_visible("position_gap_ms", checked)
        )
        toggle_row.addWidget(self.pairing_gap_checkbox)
        toggle_row.addWidget(self.position_gap_checkbox)
        layout.addLayout(toggle_row)

        bottom_row = QHBoxLayout()
        self.live_plot = LivePlot()
        self.live_plot.add_series("pairing_gap_us", color="r")
        self.live_plot.add_series("position_gap_ms", color="g")
        bottom_row.addWidget(self.live_plot, stretch=2)

        self.stats_panel = StatsPanel()
        self.stats_panel.add_field("frame_index", "Frame Index")
        self.stats_panel.add_field("pairing_gap_us", "HW Timestamp Gap (us)")
        self.stats_panel.add_field("switch_time_ms", "LED Switch Time (ms)")
        bottom_row.addWidget(self.stats_panel, stretch=1)
        layout.addLayout(bottom_row)

        control_row = QHBoxLayout()
        control_row.addWidget(QLabel("Duration (s, 0 = manual stop):"))
        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(0, 3600)
        control_row.addWidget(self.duration_spinbox)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_session)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_session)
        self.stop_button.setEnabled(False)
        control_row.addWidget(self.start_button)
        control_row.addWidget(self.stop_button)
        layout.addLayout(control_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def set_context(self, ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps,
                    switch_time_ms, scan_direction, ir_threshold, rgb_threshold, ir_xy, rgb_xy, num_leds,
                    frame_drop_threshold_factor, warmup_pairs_to_skip, pairing_gap_outlier_threshold_us,
                    kept_csv_path, dropped_csv_path):
        self._context = dict(
            ctx=ctx, device_serial=device_serial, ir_resolution=ir_resolution, ir_fps=ir_fps,
            color_resolution=color_resolution, color_fps=color_fps, switch_time_ms=switch_time_ms,
            scan_direction=scan_direction,
            ir_threshold=ir_threshold, rgb_threshold=rgb_threshold, ir_xy=ir_xy, rgb_xy=rgb_xy,
            num_leds=num_leds,
            frame_drop_threshold_factor=frame_drop_threshold_factor,
            warmup_pairs_to_skip=warmup_pairs_to_skip,
            pairing_gap_outlier_threshold_us=pairing_gap_outlier_threshold_us,
            kept_csv_path=kept_csv_path, dropped_csv_path=dropped_csv_path,
        )
        self.stats_panel.set_value("switch_time_ms", switch_time_ms)

    def start_session(self):
        ctx = self._context
        duration_s = self.duration_spinbox.value() or None
        metrics = [
            PairingGapMetric(outlier_threshold_us=ctx["pairing_gap_outlier_threshold_us"]),
            PositionGapMetric(
                ir_threshold=ctx["ir_threshold"], rgb_threshold=ctx["rgb_threshold"], num_leds=ctx["num_leds"],
                switch_time_ms=ctx["switch_time_ms"], ir_fps=ctx["ir_fps"], rgb_fps=ctx["color_fps"],
                frame_drop_threshold_factor=ctx["frame_drop_threshold_factor"],
                warmup_pairs_to_skip=ctx["warmup_pairs_to_skip"],
            ),
        ]
        test_session = TestSession(TestSessionConfig(metrics=metrics, duration_s=duration_s))
        test_session.start()

        self.engine_thread = SessionEngineThread(
            ctx["ctx"], ctx["device_serial"], ctx["ir_resolution"], ctx["ir_fps"],
            ctx["color_resolution"], ctx["color_fps"], test_session,
            ir_xy=ctx["ir_xy"], rgb_xy=ctx["rgb_xy"],
            scan_direction=ctx["scan_direction"], switch_time_ms=ctx["switch_time_ms"],
        )
        self.engine_thread.frame_ready.connect(self._on_frame_ready)
        self.engine_thread.row_ready.connect(self._on_row_ready)
        self.engine_thread.stats_ready.connect(self._on_stats_ready)
        self.engine_thread.session_finished.connect(self._on_session_finished)
        self.engine_thread.error.connect(self._on_error)
        self.engine_thread.start()

        self.status_label.setText("")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_session(self):
        if self.engine_thread is not None:
            self.engine_thread.request_stop()

    def _on_frame_ready(self, stream_name, image):
        if stream_name == "ir":
            self.ir_panel.set_frame(image)
        else:
            self.rgb_panel.set_frame(image)

    def _on_row_ready(self, row):
        # Fired every frame-pair (not throttled) - the plot gets every point
        # so the graph itself isn't affected by the video-display stride.
        pair_index = row["pair_index"]
        if row.get("pairing_gap_us") is not None:
            self.live_plot.add_point("pairing_gap_us", pair_index, row["pairing_gap_us"])
        if row.get("position_gap_ms") is not None:
            self.live_plot.add_point("position_gap_ms", pair_index, row["position_gap_ms"])

    def _on_stats_ready(self, stats):
        # Fired only at the throttled display_stride cadence (same frames
        # the video panels update on), so the shown frame index always
        # matches what's visually on screen right now.
        self.stats_panel.set_value("frame_index", stats["pair_index"])
        if stats.get("pairing_gap_us") is not None:
            self.stats_panel.set_value("pairing_gap_us", stats["pairing_gap_us"])

    def _on_session_finished(self, rows):
        export_session_csvs(rows, self._context["kept_csv_path"], self._context["dropped_csv_path"])
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _on_error(self, message):
        # Surfaces a hardware failure (e.g. camera unplugged mid-session) to
        # the operator and resets controls so Start can be retried, rather
        # than leaving Stop enabled against a worker thread that already
        # exited its run() loop.
        self.status_label.setText("Error: {}".format(message))
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
