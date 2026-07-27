import os

import numpy as np

from gui.pages.live_session_page import LiveSessionPage, _short_camera_name


def test_short_camera_name_returns_model_designator():
    assert _short_camera_name("Intel RealSense D455") == "D455"


def test_short_camera_name_handles_single_word_input():
    assert _short_camera_name("D455") == "D455"


def test_short_camera_name_handles_empty_string():
    assert _short_camera_name("") == ""


def _minimal_context(tmp_path, **overrides):
    ctx = dict(
        ctx=None, device_serial="123456", ir_resolution=(4, 4), ir_fps=30,
        color_resolution=(4, 4), color_fps=30, switch_time_ms=1.0, scan_direction=1,
        ir_threshold=np.full(2, 150.0), rgb_threshold=np.full(2, 150.0),
        ir_xy=np.array([(1, 1), (2, 2)]), rgb_xy=np.array([(1, 1), (2, 2)]),
        num_leds=2, neighborhood_size=5, frame_drop_threshold_factor=1.5,
        warmup_pairs_to_skip=0, pairing_gap_outlier_threshold_us=100000,
        kept_csv_path=str(tmp_path / "kept.csv"), dropped_csv_path=str(tmp_path / "dropped.csv"),
        output_dir=str(tmp_path), snapshot_every_n_pairs=20, max_snapshots=2,
        ir_roi=(0, 0, 4, 4), rgb_roi=(0, 0, 4, 4), camera_name="Intel RealSense D455",
    )
    ctx.update(overrides)
    return ctx


def _page_with_frame_data(qapp, tmp_path, **context_overrides):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, **context_overrides))
    page._last_ir_image = np.zeros((4, 4), dtype=np.uint8)
    page._last_rgb_image = np.zeros((4, 4), dtype=np.uint8)
    page._last_ir_on_mask = np.array([True, False])
    page._last_rgb_on_mask = np.array([True, False])
    return page


def test_maybe_save_periodic_snapshot_skips_when_pair_index_not_a_multiple(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path)

    page._maybe_save_periodic_snapshot(pair_index=7)  # 7 % 20 != 0

    assert page._periodic_snapshot_count == 0
    assert not os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_ir_pair00007.png"))


def test_maybe_save_periodic_snapshot_saves_on_multiple_of_every_n(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path)

    page._maybe_save_periodic_snapshot(pair_index=20)

    assert page._periodic_snapshot_count == 1
    assert os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_ir_pair00020.png"))
    assert os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_rgb_pair00020.png"))


def test_maybe_save_periodic_snapshot_stops_after_max_snapshots(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path, max_snapshots=1)

    page._maybe_save_periodic_snapshot(pair_index=0)  # 0 % 20 == 0 -> saves, count becomes 1
    page._maybe_save_periodic_snapshot(pair_index=20)  # count already at max_snapshots -> skipped

    assert page._periodic_snapshot_count == 1
    assert not os.path.exists(os.path.join(str(tmp_path), "periodic_led_state_ir_pair00020.png"))


def test_maybe_save_periodic_snapshot_noop_without_context(qapp):
    page = LiveSessionPage()

    page._maybe_save_periodic_snapshot(pair_index=0)  # must not raise

    assert page._periodic_snapshot_count == 0


def test_maybe_save_periodic_snapshot_noop_when_every_n_is_zero(qapp, tmp_path):
    page = _page_with_frame_data(qapp, tmp_path, snapshot_every_n_pairs=0)

    page._maybe_save_periodic_snapshot(pair_index=0)

    assert page._periodic_snapshot_count == 0


def test_crop_to_roi_if_available_returns_image_unchanged_without_context(qapp):
    page = LiveSessionPage()
    image = np.zeros((4, 4), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "ir")

    assert result is image


def test_crop_to_roi_if_available_returns_image_unchanged_for_zero_size_roi(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, ir_roi=(0, 0, 0, 0)))
    image = np.zeros((4, 4), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "ir")

    assert result is image


def test_crop_to_roi_if_available_crops_when_roi_present(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, ir_roi=(1, 1, 2, 2)))
    image = np.zeros((4, 4), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "ir")

    assert result.shape == (2, 2)


def test_crop_to_roi_if_available_uses_rgb_roi_for_rgb_stream(qapp, tmp_path):
    page = LiveSessionPage()
    page.set_context(**_minimal_context(tmp_path, ir_roi=(0, 0, 0, 0), rgb_roi=(1, 1, 3, 3)))
    image = np.zeros((4, 4), dtype=np.uint8)

    result = page._crop_to_roi_if_available(image, "rgb")

    assert result.shape == (3, 3)
