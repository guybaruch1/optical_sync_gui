"""Wizard step 5 - the live sync-test view: dual video panels (each
showing a live LED on/off detection overlay), a togglable/stacked live
plot of both metrics, a separate frame-drops-per-pair plot, a live stats
sidebar, and Start/Stop with an optional fixed duration. Saves periodic
LED on/off debug snapshots during the run (every settings.yaml
test.snapshot_every_n_pairs pairs, capped at test.max_snapshots per
stream, filename includes the pair_index so it can be cross-checked
against what was on screen and against the CSV's pair_index column). At
Stop, writes the CSVs (domain.csv_export.export_session_csvs), a static
end-of-run plot image (domain.plot_export.export_session_plot), and one
final LED on/off debug snapshot for each stream - the same final
snapshot can also be saved on demand mid-session via the "Save Debug
Snapshot" button.

The frame-drops plot was originally a single dual-axis chart sharing one
plot with the pairing-gap line (via pyqtgraph's linked-ViewBox pattern
for a second y-axis), but that rendering proved unreliable in practice
(the second axis's curve visibly tracked the wrong scale on a real run,
despite passing isolated unit tests) - replaced with a second, ordinary
LivePlot instance instead, the same well-tested single-axis widget used
above, trading the "one chart" look for reliability."""

import glob
import os

import cv2
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
from domain.plot_export import export_session_plot
from domain.realsense_utils import draw_led_state_overlay


class LiveSessionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine_thread = None
        self._context = None
        self._ir_drop_count = 0
        self._rgb_drop_count = 0
        self._drop_since_last_plot = False
        self._last_ir_image = None
        self._last_rgb_image = None
        self._last_ir_on_mask = None
        self._last_rgb_on_mask = None
        self._periodic_snapshot_count = 0

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
        self.pairing_gap_checkbox.toggled.connect(self._set_pairing_gap_visible)
        self.position_gap_checkbox = QCheckBox("Position gap (ms)")
        self.position_gap_checkbox.setChecked(True)
        self.position_gap_checkbox.toggled.connect(
            lambda checked: self.live_plot.set_series_visible("position_gap_ms", checked)
        )
        toggle_row.addWidget(self.pairing_gap_checkbox)
        toggle_row.addWidget(self.position_gap_checkbox)

        self.live_plot = LivePlot()
        self.live_plot.add_series("pairing_gap_us", color="r")
        self.live_plot.add_series("position_gap_ms", color="g")

        self.drop_plot = LivePlot()
        self.drop_plot.setLabel("left", "Frame Drops (count)")
        self.drop_plot.setLabel("bottom", "Pair Index")
        self.drop_plot.add_series("frame_drops", color=(255, 140, 0))

        # Both graphs live in the same column with equal stretch, so they
        # get identical width AND height - previously live_plot shared its
        # row with stats_panel while drop_plot had the full row to itself,
        # so the two ended up different sizes despite looking like they
        # should match.
        graphs_column = QVBoxLayout()
        graphs_column.addLayout(toggle_row)
        graphs_column.addWidget(self.live_plot, stretch=1)
        graphs_column.addWidget(self.drop_plot, stretch=1)

        self.stats_panel = StatsPanel()
        self.stats_panel.add_field("frame_index", "Frame Index")
        self.stats_panel.add_field("pairing_gap_us", "HW Timestamp Gap (us)")
        self.stats_panel.add_field("position_gap_ms", "Position Gap (ms)")
        self.stats_panel.add_field("switch_time_ms", "LED Switch Time (ms)")
        self.stats_panel.add_field("ir_frame_drops", "IR Frame Drops")
        self.stats_panel.add_field("rgb_frame_drops", "RGB Frame Drops")

        middle_row = QHBoxLayout()
        middle_row.addLayout(graphs_column, stretch=2)
        middle_row.addWidget(self.stats_panel, stretch=1)
        layout.addLayout(middle_row)

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

    def _set_pairing_gap_visible(self, checked):
        self.live_plot.set_series_visible("pairing_gap_us", checked)

    def set_context(self, ctx, device_serial, ir_resolution, ir_fps, color_resolution, color_fps,
                    switch_time_ms, scan_direction, ir_threshold, rgb_threshold, ir_xy, rgb_xy, num_leds,
                    neighborhood_size,
                    frame_drop_threshold_factor, warmup_pairs_to_skip, pairing_gap_outlier_threshold_us,
                    kept_csv_path, dropped_csv_path, output_dir,
                    snapshot_every_n_pairs, max_snapshots):
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
            snapshot_every_n_pairs=snapshot_every_n_pairs, max_snapshots=max_snapshots,
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

        # A new session's pair_index restarts at 0 - without clearing, its
        # points would draw right on top of/alongside whatever the previous
        # session left on these graphs, and any manual zoom/pan from the
        # previous session would carry over too (clear() also resets to
        # auto-range).
        self.live_plot.clear_data()
        self.drop_plot.clear_data()

        self._ir_drop_count = 0
        self._rgb_drop_count = 0
        self._drop_since_last_plot = False
        self._last_ir_image = None
        self._last_rgb_image = None
        self._last_ir_on_mask = None
        self._last_rgb_on_mask = None
        self._periodic_snapshot_count = 0
        self._clear_periodic_snapshots(ctx["output_dir"])

        if self.engine_thread is not None:
            # Defense-in-depth: the Start button shouldn't be clickable
            # again until _on_engine_thread_finished has already fired (see
            # below), so this should return immediately. But if it somehow
            # isn't done yet, block until it is rather than let a second
            # ContinuousCapture/LEDPanel session race the first one for the
            # same physical camera - that race is what caused
            # "QThread: Destroyed while thread '' is still running" and the
            # crash/freeze it led to.
            self.engine_thread.wait()

        self.engine_thread = SessionEngineThread(
            ctx["ctx"], ctx["device_serial"], ctx["ir_resolution"], ctx["ir_fps"],
            ctx["color_resolution"], ctx["color_fps"], test_session,
            ir_xy=ctx["ir_xy"], rgb_xy=ctx["rgb_xy"], neighborhood_size=ctx["neighborhood_size"],
            scan_direction=ctx["scan_direction"], switch_time_ms=ctx["switch_time_ms"],
            position_gap_metric=position_gap_metric,
        )
        self.engine_thread.frame_ready.connect(self._on_frame_ready)
        self.engine_thread.row_ready.connect(self._on_row_ready)
        self.engine_thread.stats_ready.connect(self._on_stats_ready)
        self.engine_thread.session_finished.connect(self._on_session_finished)
        self.engine_thread.error.connect(self._on_error)
        # QThread's own finished signal - unlike session_finished/error
        # (emitted inside SessionEngineThread.run()'s try block), this only
        # fires once run() has fully returned, including its finally block
        # (stopping the camera pipeline, stopping the LED panel). Gating
        # "Start is clickable again" on this, not on session_finished/error,
        # is the actual fix - re-enabling Start any earlier let a new
        # session's camera/LED-panel calls race the old thread's still-running
        # cleanup for the same physical hardware.
        self.engine_thread.finished.connect(self._on_engine_thread_finished)
        self.engine_thread.start()

        self.status_label.setText("")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_session(self):
        if self.engine_thread is not None:
            self.engine_thread.request_stop()

    def _on_frame_ready(self, stream_name, image, pair_index, on_mask):
        # image and on_mask arrive together, already paired correctly by
        # SessionEngineThread (a snapshot copy taken on the background
        # thread at this exact pair_index) - this method must not read any
        # live/mutable state to recover the mask itself, only use what was
        # handed to it, or the same stale-read bug comes right back.
        if stream_name == "ir":
            self._last_ir_image = image
            self._last_ir_on_mask = on_mask
        else:
            self._last_rgb_image = image
            self._last_rgb_on_mask = on_mask

        display_image = draw_led_state_overlay(image, self._overlay_xy(stream_name), on_mask) \
            if on_mask is not None and self._context is not None else image
        if stream_name == "ir":
            self.ir_panel.set_frame(display_image)
        else:
            self.rgb_panel.set_frame(display_image)
            # "rgb" is always the second of the pair emitted per iteration
            # (see SessionEngineThread.on_frames), so by this point
            # _last_ir_image/_last_ir_on_mask have already been updated too.
            self._maybe_save_periodic_snapshot(pair_index)

    def _overlay_xy(self, stream_name):
        return self._context["ir_xy"] if stream_name == "ir" else self._context["rgb_xy"]

    def _maybe_save_periodic_snapshot(self, pair_index):
        if self._context is None:
            return
        every_n = self._context["snapshot_every_n_pairs"]
        max_snapshots = self._context["max_snapshots"]
        if every_n <= 0 or pair_index % every_n != 0:
            return
        if self._periodic_snapshot_count >= max_snapshots:
            return
        if self._last_ir_on_mask is None or self._last_rgb_on_mask is None:
            return
        if self._last_ir_image is None or self._last_rgb_image is None:
            return

        output_dir = self._context["output_dir"]
        # pair_index in the filename lets you directly verify the saved
        # detection picture matches the frame that was on screen at that
        # exact moment - the same number the live display and the CSV's
        # pair_index column both use.
        ir_path = os.path.join(output_dir, "periodic_led_state_ir_pair{:05d}.png".format(pair_index))
        rgb_path = os.path.join(output_dir, "periodic_led_state_rgb_pair{:05d}.png".format(pair_index))
        ir_debug = draw_led_state_overlay(self._last_ir_image, self._context["ir_xy"], self._last_ir_on_mask)
        rgb_debug = draw_led_state_overlay(self._last_rgb_image, self._context["rgb_xy"], self._last_rgb_on_mask)
        cv2.imwrite(ir_path, ir_debug)
        cv2.imwrite(rgb_path, rgb_debug)
        self._periodic_snapshot_count += 1

    def _clear_periodic_snapshots(self, output_dir):
        # Stale files from a previous run (e.g. one that ran longer and
        # reached higher pair_index values) would otherwise linger alongside
        # this run's snapshots and make "same frame index" cross-checking
        # ambiguous about which run a given file belongs to.
        for path in glob.glob(os.path.join(output_dir, "periodic_led_state_*.png")):
            os.remove(path)

    def _on_row_ready(self, row):
        # Fired on EVERY frame-pair (not throttled) - this must stay O(1)
        # and cheap. It used to also call add_point() (pyqtgraph setData())
        # here, up to 4 times per pair; even after bounding each series'
        # history, that was still too expensive to sustain every single
        # pair at up to 30fps, so a backlog of queued GUI-thread work built
        # up continuously and only became visible once the user tried to
        # interact (Stop, Save Debug Snapshot) and that click had to wait
        # behind the entire backlog - looking exactly like a freeze. Plot
        # updates now happen in _on_stats_ready instead, which only fires
        # every display_stride pairs. Only cheap counter bookkeeping stays
        # here, so the drop counts remain exact even though the plots don't
        # sample every single pair.
        if row.get("ir_frame_drop"):
            self._ir_drop_count += 1
            self._drop_since_last_plot = True
        if row.get("rgb_frame_drop"):
            self._rgb_drop_count += 1
            self._drop_since_last_plot = True
        if row.get("position_gap_ms_exclude_reason") == "frame_drop":
            self._drop_since_last_plot = True

    def _on_stats_ready(self, stats):
        # Fired only at the throttled display_stride cadence (same frames
        # the video panels update on) - this is also where plot updates
        # happen now (see _on_row_ready), keeping the expensive pyqtgraph
        # setData() calls at a rate the GUI thread can actually sustain.
        pair_index = stats["pair_index"]
        self.stats_panel.set_value("frame_index", pair_index)

        # Same NaN-for-excluded-values convention as
        # optical_sync_poc_/pipeline_sync_test_diff.py's own plotting
        # (`np.where(valid, gap_ms, nan)`) - an excluded pair can carry a
        # wild real value (e.g. a multi-hundred-thousand-us pairing gap
        # during auto-exposure warmup) that would otherwise force the whole
        # y-axis to that scale.
        if stats.get("pairing_gap_us") is not None:
            self.stats_panel.set_value("pairing_gap_us", stats["pairing_gap_us"])
            pairing_value = stats["pairing_gap_us"] if not stats.get("pairing_gap_us_excluded") else float("nan")
            self.live_plot.add_point("pairing_gap_us", pair_index, pairing_value)
        if stats.get("position_gap_ms") is not None:
            self.stats_panel.set_value("position_gap_ms", stats["position_gap_ms"])
            position_value = stats["position_gap_ms"] if not stats.get("position_gap_ms_excluded") else float("nan")
            self.live_plot.add_point("position_gap_ms", pair_index, position_value)

        self.stats_panel.set_value("ir_frame_drops", self._ir_drop_count)
        self.stats_panel.set_value("rgb_frame_drops", self._rgb_drop_count)
        # Whether ANY drop happened since the last plotted point, not just
        # this exact pair's own value - otherwise an isolated drop on one of
        # the ~9 skipped pairs between throttled samples would silently
        # never show up as a spike.
        self.drop_plot.add_point("frame_drops", pair_index, 1 if self._drop_since_last_plot else 0)
        self._drop_since_last_plot = False

    def _on_session_finished(self, rows):
        export_session_csvs(rows, self._context["kept_csv_path"], self._context["dropped_csv_path"])
        export_session_plot(rows, os.path.join(self._context["output_dir"], "pipeline_sync_plot.png"))
        self._save_led_state_debug_images()
        # Button re-enabling happens in _on_engine_thread_finished, not here -
        # this fires before SessionEngineThread.run()'s finally block (camera
        # pipeline/LED panel cleanup) has actually completed.

    def _on_engine_thread_finished(self):
        # QThread.finished - fires only once run() has fully returned,
        # finally block included, so it's safe to let the user start a new
        # session now (the camera/LED panel are actually free).
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _save_led_state_debug_images(self):
        # Also wired to the "Save Debug Snapshot" button for an on-demand
        # check mid-session, not just the automatic one at Stop. Uses the
        # cached masks populated by _on_frame_ready from the signal payload
        # (already correctly paired to _last_ir_image/_last_rgb_image at
        # the moment they arrived) - never reads a live metric object,
        # which was the source of the frame/detection offset bug. Always
        # reports what happened via status_label - previously this
        # returned silently on every path (not-ready, success, and failure
        # all looked identical), which is why the button appeared "not
        # working" even when it may have been succeeding.
        if self._context is None:
            self.status_label.setText("No active session - click Start first.")
            return
        if self._last_ir_on_mask is None or self._last_rgb_on_mask is None:
            self.status_label.setText("No frame data yet - wait a moment after Start and try again.")
            return
        if self._last_ir_image is None or self._last_rgb_image is None:
            self.status_label.setText("No frame data yet - wait a moment after Start and try again.")
            return

        output_dir = self._context["output_dir"]
        ir_path = os.path.join(output_dir, "live_led_state_ir.png")
        rgb_path = os.path.join(output_dir, "live_led_state_rgb.png")
        try:
            ir_debug = draw_led_state_overlay(self._last_ir_image, self._context["ir_xy"], self._last_ir_on_mask)
            rgb_debug = draw_led_state_overlay(self._last_rgb_image, self._context["rgb_xy"], self._last_rgb_on_mask)
            ir_ok = cv2.imwrite(ir_path, ir_debug)
            rgb_ok = cv2.imwrite(rgb_path, rgb_debug)
        except Exception as exc:
            self.status_label.setText("Failed to save debug snapshot: {}".format(exc))
            return

        if ir_ok and rgb_ok:
            self.status_label.setText("Saved debug snapshot: {}, {}".format(ir_path, rgb_path))
        else:
            self.status_label.setText("Failed to write one or both debug snapshot files to {}".format(output_dir))

    def _on_error(self, message):
        # Surfaces a hardware failure (e.g. camera unplugged mid-session) to
        # the operator. Button re-enabling happens in
        # _on_engine_thread_finished, not here - this fires before
        # SessionEngineThread.run()'s finally block (camera pipeline/LED
        # panel cleanup) has actually completed.
        self.status_label.setText("Error: {}".format(message))
