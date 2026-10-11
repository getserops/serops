/**
 * Chat API service — routes every call through the shared apiClient
 * axios interceptor.
 *
 * Migrated 2026-08-30 from raw ``fetch`` calls. Reasons:
 *  - apiClient auto-injects the Token header (single source of truth
 *    for auth); the old fetch calls each re-read localStorage.
 *  - apiClient's response interceptor clears localStorage + redirects
 *    to /login on 401, so a stale session doesn't leave chat stuck
 *    on "Loading…" until the user notices.
 *  - Consistent error shape: every rejection is an Error with
 *    ``.code`` (e.g. ``'demo_read_only'`` from
 *    ``DemoUserMiddleware``) and ``.status`` (HTTP), so callers can
 *    branch on a stable identifier instead of substring-matching a
 *    rendered message.
 */

import apiClient from './api-client';

/** Turn an axios rejection into an Error with .code + .status. */
function _rethrow(err) {
    const detail = err?.response?.data;
    const message =
        (detail && typeof detail === 'object' && (detail.message || detail.error))
        || (typeof detail === 'string' ? detail : null)
        || err?.message
        || 'Request failed';
    const wrapped = new Error(message);
    wrapped.code = (detail && typeof detail === 'object' && detail.error) || null;
    wrapped.status = err?.response?.status ?? null;
    throw wrapped;
}

// Model IDs that the backend understands. Frontend labels
// ("Deepseek", "Gemini") get mapped to the canonical lowercase
// codes here so the API contract stays stable.
const MODEL_LABEL_TO_CODE = {
    Deepseek: 'deepseek',
    Gemini: 'gemini',
};

export const sendChatMessage = async (
    message,
    model = 'Deepseek',
    chatId = null,
    batchId = null,
) => {
    const aiModel = MODEL_LABEL_TO_CODE[model] || 'pods';
    const body = {
        type: 'chat',
        ai_model: aiModel,
        prompt: { message },
    };
    if (chatId) body.chat_id = chatId;
    if (batchId) body.batch_id = batchId;

    try {
        const { data } = await apiClient.post('/chat/generate-text/', body);
        return data.response || data.analysis_result || 'No response text found';
    } catch (err) {
        _rethrow(err);
    }
};

export const getChatHistory = async () => {
    try {
        const { data } = await apiClient.get('/chat/chat-sessions/');
        return data;
    } catch (err) {
        _rethrow(err);
    }
};

export const getSessionMessages = async (chatId) => {
    try {
        const { data } = await apiClient.get(`/chat/chats/${chatId}/`);
        return data;
    } catch (err) {
        _rethrow(err);
    }
};

export const deleteChatSession = async (chatId) => {
    // Semantic preserved from the pre-migration version: return
    // ``true`` on success, ``false`` on failure (callers rely on
    // this instead of the throw path).
    try {
        await apiClient.delete(`/chat/chats/delete/${chatId}`);
        return true;
    } catch (err) {
        console.error('Error deleting chat session:', err);
        return false;
    }
};

export const createChatSession = async ({ initialMessages, title }) => {
    try {
        const { data } = await apiClient.post('/chat/chat-sessions/', {
            initialMessages,
            title,
        });
        return data;
    } catch (err) {
        _rethrow(err);
    }
};
