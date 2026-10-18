import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { isChunkLoadError, reloadForNewBuild } from '../staleBuild';

// After a deploy, an open tab asks for chunks the new build no longer
// serves. The app should reload once into the new build, not show an error,
// and never loop if the chunk is really gone.

describe('isChunkLoadError', () => {
    it('recognises the Chrome, Safari and Firefox wording', () => {
        expect(isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: http://x/assets/Login-DPvUOAR7.js'))).toBe(true);
        expect(isChunkLoadError(new TypeError('Importing a module script failed.'))).toBe(true);
        expect(isChunkLoadError(new TypeError('error loading dynamically imported module'))).toBe(true);
    });

    it('leaves ordinary crashes alone', () => {
        expect(isChunkLoadError(new TypeError("Cannot read properties of undefined (reading 'map')"))).toBe(false);
        expect(isChunkLoadError(null)).toBe(false);
    });
});

describe('reloadForNewBuild', () => {
    const reload = vi.fn();
    const original = window.location;

    beforeEach(() => {
        sessionStorage.clear();
        reload.mockClear();
        Object.defineProperty(window, 'location', { configurable: true, value: { ...original, reload } });
    });
    afterEach(() => {
        Object.defineProperty(window, 'location', { configurable: true, value: original });
    });

    it('reloads the page the first time', () => {
        expect(reloadForNewBuild()).toBe(true);
        expect(reload).toHaveBeenCalledTimes(1);
    });

    it('does not reload again within the guard window, so a missing chunk cannot loop', () => {
        reloadForNewBuild();
        expect(reloadForNewBuild()).toBe(false);
        expect(reload).toHaveBeenCalledTimes(1);
    });
});
