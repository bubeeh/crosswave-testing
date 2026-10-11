"""Fonti di similarità per il sistema di raccomandazione v2."""

from .bandcamp import BandcampSource
from .base import Candidate, RecSource
from .discogs import DiscogsSource
from .lastfm import LastFmSource
from .musicbrainz import MusicBrainzSource
from .soundcloud import SoundCloudSource
from .youtube import YouTubeSource

__all__ = [
    "Candidate",
    "RecSource",
    "BandcampSource",
    "DiscogsSource",
    "LastFmSource",
    "MusicBrainzSource",
    "SoundCloudSource",
    "YouTubeSource",
]
