import pytest
from engine.streams import list_supported_profiles, match_profile


class FakeVideoProfile:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeProfile:
    def __init__(self, stream_type, fmt, width, height, fps):
        self._stream_type = stream_type
        self._fmt = fmt
        self._fps = fps
        self._video = FakeVideoProfile(width, height)

    def stream_type(self):
        return self._stream_type

    def format(self):
        return self._fmt

    def fps(self):
        return self._fps

    def as_video_stream_profile(self):
        return self._video


class FakeSensor:
    def __init__(self, profiles):
        self.profiles = profiles


def test_list_supported_profiles_filters_by_stream_and_format():
    sensor = FakeSensor(profiles=[
        FakeProfile("infrared", "y8", 1280, 720, 30),
        FakeProfile("infrared", "y8", 640, 480, 60),
        FakeProfile("color", "yuyv", 1280, 720, 30),
    ])
    result = list_supported_profiles(sensor, "infrared", "y8")
    assert set(result) == {(1280, 720, 30), (640, 480, 60)}


def test_match_profile_finds_exact_match():
    target = FakeProfile("infrared", "y8", 1280, 720, 30)
    sensor = FakeSensor(profiles=[FakeProfile("infrared", "y8", 640, 480, 60), target])
    matched = match_profile(sensor, "infrared", "y8", 1280, 720, 30)
    assert matched is target


def test_match_profile_raises_when_nothing_matches():
    sensor = FakeSensor(profiles=[FakeProfile("infrared", "y8", 640, 480, 60)])
    with pytest.raises(RuntimeError):
        match_profile(sensor, "infrared", "y8", 1280, 720, 30)
