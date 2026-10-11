from __future__ import annotations

import pytest

from player_engine.recommend.events import infer_event_type


@pytest.mark.parametrize(
    "seconds,completion,provided,expected",
    [
        (5, 0.0, None, "skip"),          # < 15s
        (20, 0.2, None, "partial"),      # 15s..50%
        (100, 0.6, None, "half"),        # >= 50%
        (180, 0.95, None, "complete"),   # >= 90%
        (10, 0.0, "replay", "replay"),   # esplicito dal client
        (30, 0.3, "like", "like"),       # esplicito
        (30, 0.3, "bogus", "partial"),   # evento non valido → derivato
    ],
)
def test_infer_event_type(seconds, completion, provided, expected):
    assert infer_event_type(seconds, completion, provided) == expected
