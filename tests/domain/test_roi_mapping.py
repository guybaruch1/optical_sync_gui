import pytest
from domain.roi_mapping import widget_rect_to_image_roi


def test_scales_up_uniformly_when_image_is_larger_than_widget():
    # widget is exactly half the image's size on both axes
    roi = widget_rect_to_image_roi((50, 50, 100, 60), widget_size=(500, 300), image_size=(1000, 600))
    assert roi == (100, 100, 200, 120)


def test_scales_independently_per_axis():
    # widget is half width but a third of the height of the image
    roi = widget_rect_to_image_roi((10, 10, 20, 30), widget_size=(200, 100), image_size=(400, 300))
    assert roi == (20, 30, 40, 90)


def test_identity_when_widget_matches_image_size():
    roi = widget_rect_to_image_roi((5, 5, 50, 40), widget_size=(640, 480), image_size=(640, 480))
    assert roi == (5, 5, 50, 40)


def test_raises_on_nonpositive_widget_size():
    with pytest.raises(ValueError):
        widget_rect_to_image_roi((0, 0, 10, 10), widget_size=(0, 300), image_size=(1000, 600))
