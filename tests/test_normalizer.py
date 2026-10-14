"""Test del Normalizer: da JSON grezzo yt-dlp a MediaObject canonico."""

from __future__ import annotations

from player_engine.core.schema import DownloadLicense, MediaType
from player_engine.resolver.normalizer import Normalizer

NORM = Normalizer(resolver_version="yt-dlp/test")


def _raw(**overrides):
    base = {
        "id": "abc123",
        "webpage_url": "https://example.com/track",
        "title": "Brano",
        "uploader": "Artista",
        "duration": 120,
        "formats": [
            {"format_id": "a1", "url": "https://cdn/a.mp3", "ext": "mp3",
             "acodec": "mp3", "vcodec": "none", "abr": 128},
        ],
    }
    base.update(overrides)
    return base


def test_audio_only_stream_detection():
    media = NORM.normalize("bandcamp", _raw())
    assert media.media_type == MediaType.AUDIO
    assert media.streams and media.streams[0].is_audio_only


def test_hls_formats_are_excluded():
    raw = _raw(formats=[
        {"format_id": "hls", "url": "https://cdn/master.m3u8", "ext": "m3u8"},
        {"format_id": "a1", "url": "https://cdn/a.mp3", "ext": "mp3",
         "acodec": "mp3", "vcodec": "none", "abr": 128},
    ])
    media = NORM.normalize("bandcamp", raw)
    assert [s.format_id for s in media.streams] == ["a1"]


def test_canonical_id_is_stable():
    a = NORM.normalize("bandcamp", _raw())
    b = NORM.normalize("bandcamp", _raw())
    assert a.canonical_id == b.canonical_id
    assert a.canonical_id.startswith("sha256:")


def test_bandcamp_license_is_explicit_permission():
    media = NORM.normalize("bandcamp", _raw())
    assert media.rights.download_license == DownloadLicense.EXPLICIT_PERMISSION


def test_youtube_creative_commons_license():
    raw = _raw(license="Creative Commons Attribution")
    media = NORM.normalize("youtube", raw)
    assert media.rights.download_license == DownloadLicense.CREATIVE_COMMONS


def test_collection_flag_from_entries():
    raw = _raw(_type="playlist", entries=[{"id": "t1", "title": "Traccia 1"}])
    media = NORM.normalize("youtube", raw)
    assert media.is_collection is True
