import { describe, it, expect, vi, beforeEach } from 'vitest';

const post = vi.fn();
vi.mock('../api-client', () => ({ default: { post: (...a) => post(...a) } }));

import { sendChatMessage } from '../chatService';

describe('sendChatMessage', () => {
  beforeEach(() => { post.mockReset(); post.mockResolvedValue({ data: { response: 'ok' } }); });

  it('sends the selected provider id, not a remapped default', async () => {
    for (const id of ['claude', 'ollama', 'openai', 'deepseek', 'gemini']) {
      await sendChatMessage('hi', id);
      expect(post.mock.calls.at(-1)[1].ai_model).toBe(id);
    }
  });

  it('omits ai_model when no provider is selected, so the backend picks the default', async () => {
    await sendChatMessage('hi', '');
    expect(post.mock.calls.at(-1)[1]).not.toHaveProperty('ai_model');
  });

  it('passes chat and batch ids through', async () => {
    await sendChatMessage('hi', 'claude', 'c-1', 'b-2');
    expect(post.mock.calls.at(-1)[1]).toMatchObject({ type: 'chat', chat_id: 'c-1', batch_id: 'b-2', prompt: { message: 'hi' } });
  });
});
