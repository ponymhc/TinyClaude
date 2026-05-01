// ========== Global State ==========
const API = '';  // API prefix (empty = same origin)
let currentSessionId = null;
let isStreaming = false;
let currentAiContainer = null;
let _sseState = {};
let fileCurrentPath = '';
let _lastFileListHash = '';