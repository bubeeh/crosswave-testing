"""Unit test del ranking cross-platform dei risultati di ricerca (puro)."""

from __future__ import annotations

from player_engine.core.schema import SearchResult
from player_engine.resolver import ranking


def _res(platform, title, uploader="", url=None, **kwargs):
    url = url or f"https://example.com/{platform}/{title}"
    return SearchResult(platform=platform, url=url, title=title,
                        uploader=uploader, **kwargs)


def test_exact_title_match_ranks_first_across_platforms():
    per_platform = {
        "youtube": [_res("youtube", "Some Random Upload", "Nobody")],
        "bandcamp": [_res("bandcamp", "Archangel", "Burial")],
    }
    ranked = ranking.rank_results(per_platform, "burial archangel")
    assert ranked[0].title == "Archangel"
    assert ranked[0].platform == "bandcamp"


def test_top_window_interleaves_platforms():
    yt = [_res("youtube", f"yt {i}") for i in range(5)]
    bc = [_res("bandcamp", f"bc {i}") for i in range(5)]
    ranked = ranking.rank_results({"youtube": yt, "bandcamp": bc}, "zzz")
    platforms = [r.platform for r in ranked[:6]]
    # punteggi equivalenti → la testa alterna esattamente le due sorgenti
    assert platforms == ["youtube", "bandcamp"] * 3


def test_top_window_mixes_platforms():
    yt = [_res("youtube", f"yt {i}") for i in range(8)]
    mc = [_res("mixcloud", f"mc {i}") for i in range(8)]
    ranked = ranking.rank_results({"youtube": yt, "mixcloud": mc}, "zzz")
    window = ranked[: ranking.TOP_WINDOW]
    yt_count = sum(1 for r in window if r.platform == "youtube")
    mc_count = sum(1 for r in window if r.platform == "mixcloud")
    # entrambe le sorgenti presenti e nessuna monopolizza la testa
    assert yt_count > 0 and mc_count > 0
    assert yt_count < ranking.TOP_WINDOW and mc_count < ranking.TOP_WINDOW
    # nessun risultato perso
    assert len(ranked) == 16


def test_tail_follows_score_order():
    yt = [_res("youtube", f"yt {i}") for i in range(6)]
    bc = [_res("bandcamp", f"bc {i}") for i in range(6)]
    ranked = ranking.rank_results({"youtube": yt, "bandcamp": bc}, "zzz")
    tail = ranked[ranking.TOP_WINDOW:]
    # oltre la finestra: prima tutti i punteggi rimasti di YouTube (piattaforma
    # con peso RRF maggiore), poi Bandcamp — ordine di punteggio preservato
    yt_tail = [r for r in tail if r.platform == "youtube"]
    if yt_tail:
        first_bc = next((i for i, r in enumerate(tail) if r.platform == "bandcamp"), None)
        last_yt = max(i for i, r in enumerate(tail) if r.platform == "youtube")
        assert first_bc is None or last_yt < first_bc



def test_cap_falls_back_when_single_platform():
    yt = [_res("youtube", f"yt {i}") for i in range(8)]
    ranked = ranking.rank_results({"youtube": yt}, "zzz")
    assert len(ranked) == 8
    assert all(r.platform == "youtube" for r in ranked)


def test_dedup_across_platforms_keeps_highest():
    per_platform = {
        "youtube": [_res("youtube", "Burial - Archangel", "Burial")],
        "soundcloud": [_res("soundcloud", "Burial - Archangel", "Burial")],
    }
    ranked = ranking.rank_results(per_platform, "burial archangel")
    assert len(ranked) == 1
    # ordine di arrivo: youtube è la prima sorgente (a parità di punteggio)
    assert ranked[0].platform == "youtube"


def test_no_dedup_without_uploader():
    per_platform = {
        "youtube": [_res("youtube", "Untitled")],
        "soundcloud": [_res("soundcloud", "Untitled")],
    }
    ranked = ranking.rank_results(per_platform, "untitled")
    assert len(ranked) == 2


def test_album_bonus_beats_track_at_equal_text():
    per_platform = {
        "youtube": [_res("youtube", "Album X", "Artist", url="https://www.youtube.com/watch?v=1")],
        "bandcamp": [_res("bandcamp", "Album X", "Artist",
                          url="https://a.bandcamp.com/album/album-x")],
    }
    ranked = ranking.rank_results(per_platform, "album x")
    assert ranked[0].platform == "bandcamp"


def test_empty_input():
    assert ranking.rank_results({}, "anything") == []
    assert ranking.rank_results({"youtube": []}, "anything") == []
