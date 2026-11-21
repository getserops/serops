import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import en from '../../locales/en.json';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key.split('.').reduce((o, k) => o?.[k], en) ?? key }),
}));

const hook = vi.hoisted(() => ({ state: {} }));
vi.mock('../../hooks/useChatIssues', () => ({ useChatIssues: () => hook.state }));
vi.mock('../SimilarIssues', () => ({ default: () => null }));
vi.mock('../SensitiveDataWarningModal', () => ({ default: () => null }));

import ChatIssues from '../ChatIssues';

const base = () => ({
  contextMessages: [], issueContext: null, messages: [], input: '', setInput: vi.fn(),
  selectedModel: 'claude', availableModels: [{ value: 'claude', label: 'Anthropic Claude' }],
  isLoading: false, error: null, isDemo: true, showHistory: false, chatHistory: [],
  messagesEndRef: { current: null }, loadedFromHistory: false,
  handleSend: vi.fn(), handleSelectModel: vi.fn(), handleKeyPress: vi.fn(), toggleHistory: vi.fn(),
  loadChatFromHistory: vi.fn(), deleteSession: vi.fn(),
  isScanning: false, showSensitiveWarning: false, sensitiveFindings: [],
  handleSendAnyway: vi.fn(), handleCancelSend: vi.fn(),
});

const show = () => render(<MemoryRouter><ChatIssues /></MemoryRouter>);

describe('ChatIssues in the read-only demo', () => {
  beforeEach(() => { hook.state = base(); });

  it('offers the saved conversations by title and opens the one clicked', () => {
    const sessions = [
      { chat_id: 'a', title: 'Fleet: fleet-redis rejects writes' },
      { chat_id: 'b', title: 'Studio: payments rejects charges' },
    ];
    hook.state.chatHistory = sessions;
    show();
    expect(screen.getByRole('status').textContent).toContain(en.chat.demoSaved);
    fireEvent.click(screen.getByRole('button', { name: 'Studio: payments rejects charges' }));
    expect(hook.state.loadChatFromHistory).toHaveBeenCalledWith(sessions[1]);
    expect(screen.getByPlaceholderText(en.chat.demoPlaceholder)).toBeDisabled();
  });

  it('says only that chat is disabled when no conversation is saved', () => {
    show();
    expect(screen.getByRole('status').textContent).toContain(en.chat.demoReadOnly);
    expect(screen.getByRole('status').textContent).not.toContain(en.chat.demoSaved);
  });
});
