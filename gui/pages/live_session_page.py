"""Wizard step 5 - the live sync-test view: dual video panels, a
togglable/stacked live plot of both metrics, a dual-axis HW-timestamp-gap
vs. frame-drop-count graph, a live stats sidebar, and Start/Stop with an
optional fixed duration. At Stop, writes the CSVs
(domain.csv_export.export_session_csvs), a static end-of-run plot image
(domain.plot_export.export_session_plot), and an LED on/off debug
snapshot for each stream (domain.realsense_utils.draw_led_state_overlay) -
the same snapshot can also be saved on demand mid-session."""

import os

import cv2
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox, QLabel, QCheckBox,
)

from gui.widgets.video_panel import VideoPanel
from gui.widgets.live_plot import LivePlot
from gui.widgets.dual_axis_live_plot import DualAxisLivePlot
from gui.widgets.stats_panel import StatsPanel
from engine.session_engine import SessionEngineThread
from engine.test_session import TestSession, TestSessionConfig
from engine.metrics import PairingGapMetric, PositionGapMetric
from domain.csv_export import export_session_csvs
from domain.plot_export import export_session_plot
from domain.realsense_utils import draw_led_state_overlay


class LiveSessionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine_thread = None
        self._context = None
        self._position_gap_metric = None
        self._ir_drop_count = 0
        self._rgb_drop_count = 0
        self._last_ir_image = None
        self._last_rgb_image = None
        self._last_ir_on_mask = None
        self._last_rgb_on_mask = None

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
        self.stats_panel.add_field("position_gap_ms", "Position Gap (ms)")
        self.stats_panel.add_field("switch_time_ms", "LED Switch Time (ms)")
        self.stats_panel.add_field("ir_frame_drops", "IR Frame Drops")
        self.stats_panel.add_field("rgb_frame_drops", "RGB Frame Drops")
        bottom_row.addWidget(self.stats_panel, stretch=1)
        layout.addLayout(bottom_row)

        drop_row = QHBoxLayout()
        self.dual_plot = DualAxisLivePlot()
        self.dual_plot.set_left_label("HW TS Delta (us)")
        self.dual_plot.set_right_label("Frame Drops (count)")
        self.dual_plot.add_left_series("pairing_gap_us", color="r")
        self.dual_plot.add_right_series("frame_drops", color=(255, 140, 0))
        drop_row.addWidget(self.dual_plot)
        layout.addLayout(drop_row)

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
        self.save_debug_button = QPushButton("Save Debug Snapshot")
        self.save_debug_button.clicked.connect(self._save_led_state_debug_images)
        control_row.addWidget(self.start_button)
        control_row.addWidget(self.stop_button)
        control_row.addWidget(self.save_debug_button)
        layout.addLayout(control_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def set_context(self, ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps,
                    switch_time_ms, scan_direction, ir_threshold, rgb_threshold, ir_xy, rgb_xy, num_leds,
                    neighborhood_size,
                    frame_drop_threshold_factor, warmup_pairs_to_skip, pairing_gap_outlier_threshold_us,
                    kept_csv_path, dropped_csv_path, output_dir):
        self._context = dict(
            ctx=ctx, device_serial=device_serial, ir_resolution=ir_resolution, ir_fps=ir_fps,
            color_resolution=color_resolution, color_fps=color_fps, switch_time_ms=switch_time_ms,
            scan_direction=scan_direction,
            ir_threshold=ir_threshold, rgb_threshold=rgb_threshold, ir_xy=ir_xy, rgb_xy=rgb_xy,
            num_leds=num_leds, neighborhood_size=neighborhood_size,
            frame_drop_threshold_factor=frame_drop_threshold_factor,
            warmup_pairs_to_skip=warmup_pairs_to_skip,
            pairing_gap_outlier_threshold_us=pairing_gap_outlier_threshold_us,
            kept_csv_path=kept_csv_path, dropped_csv_path=dropped_csv_path, output_dir=output_dir,
        )
        self.stats_panel.set_value("switch_time_ms", switch_time_ms)

    def start_session(self):
        ctx = self._context
        duration_s = self.duration_spinbox.value() or None
        position_gap_metric = PositionGapMetric(
            ir_threshold=ctx["ir_threshold"], rgb_threshold=ctx["rgb_threshold"], num_leds=ctx["num_leds"],
            switch_time_ms=ctx["switch_time_ms"], ir_fps=ctx["ir_fps"], rgb_fps=ctx["color_fps"],
            frame_drop_threshold_factor=ctx["frame_drop_threshold_factor"],
            warmup_pairs_to_skip=ctx["warmup_pairs_to_skip"],
        )
        metrics = [
            PairingGapMetric(outlier_threshold_us=ctx["pairing_gap_outlier_threshold_us"]),
            position_gap_metric,
        ]
        test_session = TestSession(TestSessionConfig(metrics=metrics, duration_s=duration_s))
        test_session.start()

        self._position_gap_metric = position_gap_metric
        self._ir_drop_count = 0
        self._rgb_drop_count = 0
        self._last_ir_image = None
        self._last_rgb_image = None
        self._last_ir_on_mask = None
        self._last_rgb_on_mask = None

        self.engine_thread = SessionEngineThread(
            ctx["ctx"], ctx["device_serial"], ctx["ir_resolution"], ctx["ir_fps"],
            ctx["color_resolution"], ctx["color_fps"], test_session,
            ir_xy=ctx["ir_xy"], rgb_xy=ctx["rgb_xy"], neighborhood_size=ctx["neighborhood_size"],
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
            self._last_ir_image = image
        else:
            self.rgb_panel.set_frame(image)
            self._last_rgb_image = image

    def _on_row_ready(self, row):
        # Fired every frame-pair (not throttled) - the plots get every point
        # so the graphs themselves aren't affected by the video-display stride.
        pair_index = row["pair_index"]
        if row.get("pairing_gap_us") is not None:
            self.live_plot.add_point("pairing_gap_us", pair_index, row["pairing_gap_us"])
            self.dual_plot.add_point("pairing_gap_us", pair_index, row["pairing_gap_us"])
        if row.get("position_gap_ms") is not None:
            self.live_plot.add_point("position_gap_ms", pair_index, row["position_gap_ms"])

        if row.get("ir_frame_drop"):
            self._ir_drop_count += 1
        if row.get("rgb_frame_drop"):
            self._rgb_drop_count += 1
        # Per-pair delta (0/1), not a running total - one spike exactly where
        # a drop happened, so it reads against the HW TS delta line on the
        # same x-axis instead of an ever-climbing staircase.
        dropped_this_pair = 1 if row.get("position_gap_ms_exclude_reason") == "frame_drop" else 0
        self.dual_plot.add_point("frame_drops", pair_index, dropped_this_pair)

    def _on_stats_ready(self, stats):
        # Fired only at the throttled display_stride cadence (same frames
        # the video panels update on), so the shown frame index always
        # matches what's visually on screen right now. Captures the
        # matching LED on/off masks here too - process_pair() (and thus
        # PositionGapMetric.last_ir_on_mask/last_rgb_on_mask) already ran for
        # this exact pair_index earlier in the same acquisition-loop
        # iteration that produced the frame just stored by _on_frame_ready,
        # so the two stay in sync despite updating via separate signals.
        self.stats_panel.set_value("frame_index", stats["pair_index"])
        if stats.get("pairing_gap_us") is not None:
            self.stats_panel.set_value("pairing_gap_us", stats["pairing_gap_us"])
        if stats.get("position_gap_ms") is not None:
            self.stats_panel.set_value("position_gap_ms", stats["position_gap_ms"])
        self.stats_panel.set_value("ir_frame_drops", self._ir_drop_count)
        self.stats_panel.set_value("rgb_frame_drops", self._rgb_drop_count)

        if self._position_gap_metric is not None:
            self._last_ir_on_mask = self._position_gap_metric.last_ir_on_mask
            self._last_rgb_on_mask = self._position_gap_metric.last_rgb_on_mask

    def _on_session_finished(self, rows):
        export_session_csvs(rows, self._context["kept_csv_path"], self._context["dropped_csv_path"])
        export_session_plot(rows, os.path.join(self._context["output_dir"], "pipeline_sync_plot.png"))
        self._save_led_state_debug_images()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _save_led_state_debug_images(self):
        # Also wired to the "Save Debug Snapshot" button for an on-demand
        # check mid-session, not just the automatic one at Stop.
        if self._context is None or self._last_ir_on_mask is None or self._last_rgb_on_mask is None:
            return
        if self._last_ir_image is None or self._last_rgb_image is None:
            return
        output_dir = self._context["output_dir"]
        ir_debug = draw_led_state_overlay(self._last_ir_image, self._context["ir_xy"], self._last_ir_on_mask)
        cv2.imwrite(os.path.join(output_dir, "live_led_state_ir.png"), ir_debug)
        rgb_debug = draw_led_state_overlay(self._last_rgb_image, self._context["rgb_xy"], self._last_rgb_on_mask)
        cv2.imwrite(os.path.join(output_dir, "live_led_state_rgb.png"), rgb_debug)

    def _on_error(self, message):
        # Surfaces a hardware failure (e.g. camera unplugged mid-session) to
        # the operator and resets controls so Start can be retried, rather
        # than leaving Stop enabled against a worker thread that already
        # exited its run() loop.
        self.status_label.setText("Error: {}".format(message))
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
