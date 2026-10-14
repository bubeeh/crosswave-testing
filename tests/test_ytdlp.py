"""Test dell'helper condiviso yt-dlp (risoluzione del comando)."""

from __future__ import annotations

import sys

from player_engine.resolver import ytdlp


def test_bin_reads_env(monkeypatch):
    monkeypatch.setenv("PLAYER_YTDLP_BIN", "custom-ytdlp")
    assert ytdlp.ytdlp_bin() == "custom-ytdlp"


def test_cmd_prepends_python_for_py_script(monkeypatch):
    monkeypatch.setenv("PLAYER_YTDLP_BIN", "C:/tools/yt.py")
    assert ytdlp.ytdlp_cmd(["--version"]) == [sys.executable, "C:/tools/yt.py", "--version"]


def test_cmd_uses_module_fallback(monkeypatch):
    monkeypatch.setenv("PLAYER_YTDLP_BIN", "definitely-not-a-real-binary-xyz")
    assert ytdlp.ytdlp_cmd(["-J"]) == [sys.executable, "-m", "yt_dlp", "-J"]
