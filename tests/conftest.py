"""Configurazione pytest: isolamento dei test (nessuna rete, DB temporaneo).

Imposta l'ambiente PRIMA di importare `app`, così il resolver non viene
avviato e la libreria utente va in un file temporaneo.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="crosswave_test_")
os.environ.setdefault("CROSSWAVE_SKIP_RESOLVER", "1")
os.environ.setdefault("CROSSWAVE_USER_DB", os.path.join(_TMP, "user.db"))
os.environ.setdefault("FLASK_DEBUG", "0")


@pytest.fixture(scope="session")
def app_module():
    import app  # import dopo aver impostato le env

    yield app
    try:
        app.resolver_service.shutdown()
    except Exception:
        pass


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()
