// Singleton State Management for CrossWave Hybrid
export const state = {
    queue: [],
    currentIndex: -1,
    history: [],
    playlists: {},
    activePlayer: null, // 'youtube', 'soundcloud', 'bandcamp', 'mixcloud', 'radio', 'local'
    currentTrack: null,

    // Audio / Player Widget Instances
    ytPlayer: null,
    scWidget: null,
    mcWidget: null,
    bcAudio: null,

    // Playback States
    isPlaying: false,
    shuffleMode: false,
    repeatMode: 'none', // 'none', 'one', 'all'
    currentVolume: 80,

    // Intervals & Temporary Handles
    ytProgressInterval: null,
    radioMetadataInterval: null,
    preMuteVolume: 80,
    pendingTrackToPlaylist: null,
    currentRandomMixTrack: null,
};
