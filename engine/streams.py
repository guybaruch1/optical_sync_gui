"""Hardware-facing RealSense device/sensor helpers.

Ported from optical_sync_poc_/realsense_utils.py's pyrealsense2-dependent
half (the pure-numpy half lives in domain/realsense_utils.py instead),
plus new device-listing and continuous-capture pieces the GUI needs that
the original one-shot scripts didn't: find_camera_sensors only ever
returned the FIRST matching device, and none of the original scripts
streamed continuously - they all captured one settled frame (calibration,
ROI picker) or ran a fixed-duration batch loop (pipeline_sync_test_diff).
The GUI's live preview and live session both need an open-ended stream,
hence ContinuousCapture.
"""

import time
from dataclasses import dataclass

import numpy as np
import pyrealsense2 as rs


@dataclass
class DeviceInfo:
    name: str
    serial: str


def list_devices(ctx):
    devices = []
    for d in ctx.query_devices():
        sensors = d.query_sensors()
        names = [s.get_info(rs.camera_info.name) for s in sensors]
        if "Stereo Module" in names and "RGB Camera" in names:
            devices.append(DeviceInfo(
                name=d.get_info(rs.camera_info.name),
                serial=d.get_info(rs.camera_info.serial_number),
            ))
    return devices


def get_sensors_for_device(ctx, serial):
    for d in ctx.query_devices():
        if d.get_info(rs.camera_info.serial_number) != serial:
            continue
        sensors = d.query_sensors()
        stereo = next(s for s in sensors if s.get_info(rs.camera_info.name) == "Stereo Module")
        rgb = next(s for s in sensors if s.get_info(rs.camera_info.name) == "RGB Camera")
        return stereo, rgb
    raise RuntimeError("No connected device with serial {!r}".format(serial))


def list_supported_profiles(sensor, stream_type, fmt):
    results = set()
    for p in sensor.profiles:
        if p.stream_type() != stream_type or p.format() != fmt:
            continue
        vp = p.as_video_stream_profile()
        results.add((vp.width(), vp.height(), p.fps()))
    return sorted(results)


def match_profile(sensor, stream_type, fmt, width, height, fps):
    for p in sensor.profiles:
        vp = p.as_video_stream_profile()
        if (
            p.stream_type() == stream_type
            and p.format() == fmt
            and vp.width() == width
            and vp.height() == height
            and p.fps() == fps
        ):
            return p
    raise RuntimeError(
        "No matching profile for {} {}x{}@{}fps ({})".format(stream_type, width, height, fps, fmt)
    )


def capture_settled_frame_pair(frame_iter, settle_frames):
    """Pulls `settle_frames` fresh pairs from an open ContinuousCapture.frames()
    generator and returns the last one, discarding the rest.

    Ported behavior from optical_sync_poc_/realsense_utils.py's
    capture_synced_frame_pair: after a trigger (e.g. turning the LED panel
    on/off), the very next frame the pipeline hands back can still be a
    stale frame that was already queued before the trigger took effect, or
    one captured mid-auto-exposure-adjustment. Waiting for `settle_frames`
    fresh pairs and keeping only the last one is what makes the captured
    frame actually reflect the post-trigger state - taking just one frame
    right after a fixed sleep (with no discard) does not give that
    guarantee and was a real cause of spurious zero-LED-detected results.
    """
    result = None
    for _ in range(settle_frames):
        result = next(frame_iter)
    return result


def disable_ir_emitter(stereo_sensor):
    if stereo_sensor.supports(rs.option.emitter_enabled):
        stereo_sensor.set_option(rs.option.emitter_enabled, 0)
        return True
    return False


def enable_auto_exposure(sensor):
    if sensor.supports(rs.option.enable_auto_exposure):
        sensor.set_option(rs.option.enable_auto_exposure, 1)


class ContinuousCapture:
    """Open-ended IR+RGB capture via rs.pipeline(), same mechanism as
    optical_sync_poc_/pipeline_sync_test_diff.py's run_pipeline_capture,
    restructured as start/frames()/stop() so it can back both the live
    ROI-selection preview and the live sync-test session."""

    def __init__(self, ir_resolution, ir_fps, color_resolution, color_fps):
        self.ir_resolution = ir_resolution
        self.ir_fps = ir_fps
        self.color_resolution = color_resolution
        self.color_fps = color_fps
        self._pipeline = None

    def start(self):
        config = rs.config()
        config.enable_stream(rs.stream.infrared, 1, *self.ir_resolution, rs.format.y8, self.ir_fps)
        config.enable_stream(rs.stream.color, *self.color_resolution, rs.format.yuyv, self.color_fps)
        self._pipeline = rs.pipeline()
        self._pipeline.start(config)

    def frames(self):
        from domain.realsense_utils import ir_bytes_to_image, yuyv_to_bgr

        while True:
            frameset = self._pipeline.wait_for_frames()
            ir_frame = frameset.get_infrared_frame()
            color_frame = frameset.get_color_frame()
            if not ir_frame or not color_frame:
                continue

            metadata = rs.frame_metadata_value.frame_timestamp
            if not (ir_frame.supports_frame_metadata(metadata) and color_frame.supports_frame_metadata(metadata)):
                raise RuntimeError(
                    "This camera/driver does not expose per-frame HW timestamp metadata "
                    "(frame_metadata_value.frame_timestamp), which the sync metrics require. "
                    "On Windows, RealSense per-frame metadata is often disabled by default at "
                    "the OS/driver level and needs a one-time enablement step (see Intel's "
                    "librealsense documentation on Windows metadata support) - reconnect the "
                    "camera after enabling it and retry."
                )

            ir_image = ir_bytes_to_image(bytes(ir_frame.get_data()), *self.ir_resolution)
            rgb_image = yuyv_to_bgr(bytes(color_frame.get_data()), *self.color_resolution)
            ir_ts_us = ir_frame.get_frame_metadata(metadata)
            rgb_ts_us = color_frame.get_frame_metadata(metadata)

            yield ir_image, rgb_image, ir_ts_us, rgb_ts_us

    def stop(self):
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
