import React, { useRef } from 'react';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render } from '@testing-library/react';
import { usePublishedHeight, useVisualViewportHeight } from '../usePublishedSize';

// A5: the chat assumed a 56 px top bar. On a phone the bar is taller, so the
// message box ended below the screen. Heights are measured now.
const Bar = () => {
  const ref = useRef(null);
  usePublishedHeight(ref, '--topbar-real-h');
  return <header ref={ref}>bar</header>;
};
const Chat = () => { useVisualViewportHeight(); return <div>chat</div>; };
const root = document.documentElement;

describe('measured heights for layouts that fill the screen', () => {
  afterEach(() => { vi.restoreAllMocks(); delete window.visualViewport; });

  it('publishes the real height of the top bar and removes it when the bar goes away', () => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(97);
    const { unmount } = render(<Bar />);
    expect(root.style.getPropertyValue('--topbar-real-h')).toBe('97px');
    unmount();
    expect(root.style.getPropertyValue('--topbar-real-h')).toBe('');
  });

  it('follows the visible screen when the on-screen keyboard opens', () => {
    const listeners = {};
    window.visualViewport = { height: 791, addEventListener: (name, fn) => { listeners[name] = fn; }, removeEventListener: vi.fn() };
    const { unmount } = render(<Chat />);
    expect(root.style.getPropertyValue('--visual-vh')).toBe('791px');
    window.visualViewport.height = 455; // keyboard open
    listeners.resize();
    expect(root.style.getPropertyValue('--visual-vh')).toBe('455px');
    unmount();
    expect(root.style.getPropertyValue('--visual-vh')).toBe('');
  });

  it('does nothing where the browser has no visualViewport', () => {
    render(<Chat />);
    expect(root.style.getPropertyValue('--visual-vh')).toBe('');
  });

  it('leaves no assumed 56 px top bar in a stylesheet', () => {
    const read = (file) => fs.readFileSync(path.resolve(__dirname, '../../components', file), 'utf8');
    for (const file of ['ChatIssues.css', 'NotificationPanel.css', 'Dashboard.css', 'Sidebar.css']) {
      expect(read(file)).not.toMatch(/--topbar-h, 56px/);
    }
    const chat = read('ChatIssues.css');
    expect(chat).toContain('--chat-chrome: calc(var(--topbar-real-h, var(--topbar-h)) + var(--demo-banner-h, 0px));');
    expect(chat).toContain('height: calc(var(--visual-vh, 100dvh) - var(--chat-chrome) - var(--chat-gutters));');
  });
});
