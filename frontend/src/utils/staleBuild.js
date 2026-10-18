// A tab opened before a deploy still points at the previous build's hashed
// chunks. The new build no longer serves them, so the next lazy route
// (Login after a logout, for instance) fails with "Failed to fetch
// dynamically imported module". The fix is to load the new build: reload
// the page once. A short guard stops a reload loop if the chunk is
// genuinely missing.

const KEY = 'serops:stale-build-reload';
const GUARD_MS = 30_000;

const CHUNK_ERROR = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS/i;

export const isChunkLoadError = (error) => {
    const message = typeof error === 'string' ? error : error?.message;
    return Boolean(message && CHUNK_ERROR.test(message));
};

// Reloads once per 30 s window. Returns true when a reload was started.
export const reloadForNewBuild = () => {
    try {
        const last = Number(sessionStorage.getItem(KEY) || 0);
        if (Date.now() - last < GUARD_MS) return false;
        sessionStorage.setItem(KEY, String(Date.now()));
    } catch {
        // Storage blocked: still reload, the browser's own cache rules
        // (index.html is no-store) make a loop unlikely.
    }
    window.location.reload();
    return true;
};

// Vite emits ``vite:preloadError`` when a dynamic import's chunk fails.
export const installStaleBuildReload = () => {
    window.addEventListener('vite:preloadError', (event) => {
        if (reloadForNewBuild()) event.preventDefault();
    });
};
