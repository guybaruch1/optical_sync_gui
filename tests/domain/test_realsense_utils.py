import numpy as np
from domain.realsense_utils import (
    sample_neighborhood_brightness,
    apply_roi_mask,
    merge_close_centroids,
    detect_led_centroids,
    ir_bytes_to_image,
    yuyv_to_bgr,
)


def test_sample_neighborhood_brightness_center_patch():
    image = np.zeros((20, 20), dtype=np.uint8)
    image[8:13, 8:13] = 200
    value = sample_neighborhood_brightness(image, x=10, y=10, size=5)
    assert value == 200.0


def test_sample_neighborhood_brightness_clamps_at_edge():
    image = np.full((10, 10), 100, dtype=np.uint8)
    # Should not raise even though the window would run off the top-left edge.
    value = sample_neighborhood_brightness(image, x=0, y=0, size=5)
    assert value == 100.0


def test_apply_roi_mask_zeroes_outside_box():
    image = np.full((10, 10, 3), 255, dtype=np.uint8)
    masked = apply_roi_mask(image, (2, 2, 3, 3))
    assert masked[0, 0].tolist() == [0, 0, 0]
    assert masked[3, 3].tolist() == [255, 255, 255]
    assert masked.shape == image.shape


def test_merge_close_centroids_merges_nearby_points():
    # nearest-neighbor distances here are [1.0, 1.0, ~55.9], so the median
    # (typical_spacing) is 1.0; distance_fraction must exceed 1.0 for the
    # merge_threshold to exceed the 1.0 gap between the first two points.
    centroids = [(10.0, 10.0), (11.0, 10.0), (50.0, 50.0)]
    merged = merge_close_centroids(centroids, distance_fraction=1.5)
    assert len(merged) == 2


def test_merge_close_centroids_passthrough_below_two_points():
    assert merge_close_centroids([(1.0, 1.0)]) == [(1.0, 1.0)]


def test_detect_led_centroids_finds_bright_blob():
    image = np.zeros((50, 50), dtype=np.uint8)
    image[20:30, 20:30] = 255
    centroids, chosen_threshold = detect_led_centroids(image, None, min_area=20)
    assert len(centroids) == 1
    cx, cy = centroids[0]
    assert 20 <= cx <= 30
    assert 20 <= cy <= 30


def test_ir_bytes_to_image_reshapes_correctly():
    raw = bytes(range(6))  # 2x3 image, 1 byte/pixel
    image = ir_bytes_to_image(raw, width=3, height=2)
    assert image.shape == (2, 3)
    assert image[0].tolist() == [0, 1, 2]
    assert image[1].tolist() == [3, 4, 5]


def test_yuyv_to_bgr_returns_correct_shape():
    width, height = 4, 2
    raw = bytes([128] * (width * height * 2))
    bgr = yuyv_to_bgr(raw, width, height)
    assert bgr.shape == (height, width, 3)
