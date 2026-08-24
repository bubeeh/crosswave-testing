"""Rate limiting etico: 1 richiesta / 5s per piattaforma (riserva Yuki Nakamura).

Persistente (SQLite): il confine tra uso legittimo e scraping. Nessuna
rotazione IP, nessuna elusione di robots.txt. La UI mostra "Sorgente
occupata — riprovo tra Ns" quando scatta il limite (riserva Astrid).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.errors import RateLimitedError
from ..storage.repos import RateLimitRepo

INTERVAL_SECONDS = 0.5


@dataclass
class RateGate:
    """Esito della richiesta di slot."""

    allowed: bool
    retry_after: float = 0.0


class RateLimiter:
    """Controllo del rate per piattaforma, persistito su SQLite."""

    def __init__(self, repo: RateLimitRepo, interval: float = INTERVAL_SECONDS) -> None:
        self._repo = repo
        self.interval = interval

    def check(self, platform: str, now: float | None = None) -> RateGate:
        """Verifica se la piattaforma ha uno slot libero (senza consumarlo)."""
        now = now if now is not None else time.time()
        last = self._repo.last_request(platform)
        remaining = self.interval - (now - last)
        if remaining > 0:
            return RateGate(allowed=False, retry_after=remaining)
        return RateGate(allowed=True)

    def acquire(self, url: str, platform: str, now: float | None = None) -> None:
        """Consuma uno slot; solleva RateLimitedError se non disponibile."""
        gate = self.check(platform, now)
        if not gate.allowed:
            raise RateLimitedError(url, platform, retry_after=gate.retry_after)
        self._repo.record(platform, now if now is not None else time.time())

    def release(self, platform: str, now: float | None = None) -> None:
        """Registra l'avvenuta richiesta (chiamato dopo una risoluzione)."""
        self._repo.record(platform, now if now is not None else time.time())
