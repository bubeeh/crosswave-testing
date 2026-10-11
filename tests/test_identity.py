from __future__ import annotations

import pytest

from player_engine.recommend.identity import ArtistRef, canonical_ref, normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Burial", "burial"),
        ("Burial - Topic", "burial"),
        ("burial  -  topic", "burial"),
        ("BÜRIAL", "burial"),
        ("The  Beatles!", "the beatles"),
        ("Boards of Canada", "boards of canada"),
        ("A$AP Rocky", "a ap rocky"),
        ("  Aphex   Twin  ", "aphex twin"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_normalize_strips_topic_only_at_end():
    # "Topic" a metà nome non va toccato
    assert normalize_name("Topic Records") == "topic records"


def test_canonical_ref():
    ref = canonical_ref("Burial - Topic")
    assert isinstance(ref, ArtistRef)
    assert ref.name == "Burial - Topic"
    assert ref.name_norm == "burial"
    assert ref.mbid is None
