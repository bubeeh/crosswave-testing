from __future__ import annotations

from player_engine.core.schema import normalize_thumbnail


def test_maxres_and_sd_default_become_hq():
    assert normalize_thumbnail("https://i.ytimg.com/vi/abc/maxresdefault.jpg") == \
        "https://i.ytimg.com/vi/abc/hqdefault.jpg"
    assert normalize_thumbnail("https://i.ytimg.com/vi/abc/sddefault.jpg") == \
        "https://i.ytimg.com/vi/abc/hqdefault.jpg"
    assert normalize_thumbnail("https://img.youtube.com/vi/abc/maxresdefault.jpg") == \
        "https://img.youtube.com/vi/abc/hqdefault.jpg"


def test_hq_and_other_hosts_untouched():
    assert normalize_thumbnail("https://i.ytimg.com/vi/abc/hqdefault.jpg") == \
        "https://i.ytimg.com/vi/abc/hqdefault.jpg"
    assert normalize_thumbnail("https://f4.bcbits.com/img/a123_2.jpg") == \
        "https://f4.bcbits.com/img/a123_2.jpg"
    assert normalize_thumbnail(None) == ""
    assert normalize_thumbnail("") == ""
