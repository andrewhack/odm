"""Video encoder configuration round-trip tests.

These tests use a fake media service so we can verify the SOAP payload
shape passed to ``SetVideoEncoderConfiguration`` without requiring a
live camera.  The shape is touchy — onvif-zeep's service_wrapper takes
a single positional dict, and several firmwares (HIK and Dahua in
particular) reject a partially-populated configuration, so we read the
existing config first and patch only the fields the caller supplied.
"""

from __future__ import annotations

from typing import Any

import pytest

from onvifcfg.media import (
    Resolution,
    set_video_encoder_configuration,
)


class _FakeRateControl:
    def __init__(self) -> None:
        self.FrameRateLimit = 25
        self.BitrateLimit = 4096
        self.EncodingInterval = 1


class _FakeH264:
    def __init__(self) -> None:
        self.GovLength = 50
        self.H264Profile = "Main"


class _FakeConfig:
    """Mimics a zeep CompoundValue for VideoEncoderConfiguration."""

    def __init__(self) -> None:
        self.Name = "main_h264"
        self.UseCount = 2
        self.Encoding = "H264"
        self.Resolution = type("R", (), {"Width": 1920, "Height": 1080})()
        self.Quality = 5.0
        self.RateControl = _FakeRateControl()
        self.H264 = _FakeH264()
        self.Multicast = type("M", (), {"Address": "0.0.0.0", "Port": 0})()
        self.SessionTimeout = "PT30S"
        # Dunder-like attribute zeep exposes; ours is just a marker.
        self.__values__ = None  # type: ignore[assignment]


class _FakeMediaService:
    def __init__(self, cfg: _FakeConfig) -> None:
        self._cfg = cfg
        self.last_set_payload: dict[str, Any] | None = None

    def GetVideoEncoderConfiguration(self, payload: dict[str, Any]) -> _FakeConfig:  # noqa: N802
        assert payload == {"ConfigurationToken": "vec_main"}
        return self._cfg

    def SetVideoEncoderConfiguration(self, payload: dict[str, Any]) -> None:  # noqa: N802
        self.last_set_payload = payload


class _FakeSession:
    def __init__(self, media: _FakeMediaService) -> None:
        self.media = media


@pytest.fixture()
def fake_session() -> _FakeSession:
    return _FakeSession(_FakeMediaService(_FakeConfig()))


def test_set_resolution_only_patches_resolution(fake_session: _FakeSession) -> None:
    set_video_encoder_configuration(
        fake_session,  # type: ignore[arg-type]
        "vec_main",
        resolution=Resolution(1280, 720),
    )
    payload = fake_session.media.last_set_payload
    assert payload is not None
    cfg = payload["Configuration"]
    assert cfg["Resolution"] == {"Width": 1280, "Height": 720}
    # Untouched fields preserved on the round-trip.
    assert cfg["Encoding"] == "H264"
    assert cfg["Name"] == "main_h264"
    # Token is set so the device knows which configuration to write.
    assert cfg["token"] == "vec_main"
    # Force-persistence default is True (changes survive reboot).
    assert payload["ForcePersistence"] is True


def test_set_fps_and_bitrate_patches_rate_control(fake_session: _FakeSession) -> None:
    set_video_encoder_configuration(
        fake_session,  # type: ignore[arg-type]
        "vec_main",
        fps=20,
        bitrate_kbps=2048,
    )
    cfg = fake_session.media.last_set_payload["Configuration"]  # type: ignore[index]
    rc = cfg["RateControl"]
    assert rc["FrameRateLimit"] == 20
    assert rc["BitrateLimit"] == 2048
    # EncodingInterval was not supplied -> preserved from existing config.
    assert rc["EncodingInterval"] == 1


def test_set_gov_length_routes_to_h264_block(fake_session: _FakeSession) -> None:
    set_video_encoder_configuration(
        fake_session,  # type: ignore[arg-type]
        "vec_main",
        gov_length=30,
    )
    cfg = fake_session.media.last_set_payload["Configuration"]  # type: ignore[index]
    assert cfg["H264"]["GovLength"] == 30
    # H264 sub-block fields the caller did not touch must survive.
    assert cfg["H264"]["H264Profile"] == "Main"


def test_force_persistence_can_be_overridden(fake_session: _FakeSession) -> None:
    set_video_encoder_configuration(
        fake_session,  # type: ignore[arg-type]
        "vec_main",
        fps=15,
        force_persistence=False,
    )
    assert fake_session.media.last_set_payload["ForcePersistence"] is False  # type: ignore[index]


def test_missing_config_raises(fake_session: _FakeSession) -> None:
    """If the device refuses GetVideoEncoderConfiguration we must abort
    rather than send an empty configuration that would clobber the
    device's current settings."""

    class _RefusingMedia(_FakeMediaService):
        def GetVideoEncoderConfiguration(self, payload: dict[str, Any]) -> Any:  # noqa: N802
            raise RuntimeError("Sender not Authorized")

    sess = _FakeSession(_RefusingMedia(_FakeConfig()))
    with pytest.raises(RuntimeError, match="could not read encoder configuration"):
        set_video_encoder_configuration(
            sess,  # type: ignore[arg-type]
            "vec_main",
            fps=15,
        )
