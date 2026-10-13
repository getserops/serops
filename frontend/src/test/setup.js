/**
 * Test setup file for Vitest
 * Configures testing environment with jsdom and mocks
 */

import '@testing-library/jest-dom';
import { vi } from 'vitest';

// Mock localStorage for tests
const localStorageMock = {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
    length: 0,
    key: vi.fn(),
};

Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
});

// Mock window.confirm
Object.defineProperty(window, 'confirm', {
    writable: true,
    value: vi.fn(() => true),
});

// Mock window.alert
Object.defineProperty(window, 'alert', {
    writable: true,
    value: vi.fn(),
});
