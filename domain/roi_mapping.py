"""Maps a rectangle captured in widget pixel coordinates (e.g. a
QRubberBand selection over a VideoPanel using setScaledContents) back to
the corresponding region in the underlying image's native pixel
coordinates. setScaledContents stretches independently per axis (no
aspect-ratio preservation), so x and y need separate scale factors.
"""


def widget_rect_to_image_roi(rect_xywh, widget_size, image_size):
    x, y, w, h = rect_xywh
    widget_width, widget_height = widget_size
    image_width, image_height = image_size

    if widget_width <= 0 or widget_height <= 0:
        raise ValueError("widget_size must be positive, got {!r}".format(widget_size))

    scale_x = image_width / widget_width
    scale_y = image_height / widget_height

    return (
        int(round(x * scale_x)),
        int(round(y * scale_y)),
        int(round(w * scale_x)),
        int(round(h * scale_y)),
    )
