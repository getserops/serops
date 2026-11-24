import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import i18n from "../../i18n";

vi.mock("../../services/chatService", () => ({
  sendChatMessage: vi.fn(),
  getChatHistory: vi.fn().mockResolvedValue({ sessions: [] }),
  getSessionMessages: vi.fn(),
  deleteChatSession: vi.fn(),
}));
vi.mock("../../services/settings.service", () => ({ default: { getAvailableModels: vi.fn().mockResolvedValue({ models: [] }) } }));
vi.mock("../../services/data.service", () => ({ formatAnalysisResult: () => "" }));
vi.mock("../../services/redaction.service", () => ({ scanMessageForSensitiveData: vi.fn() }));
vi.mock("../../utils/demo", () => ({ isDemoUser: () => false }));

import { useChatIssues } from "../useChatIssues";

const wrapper = ({ children }) => <MemoryRouter>{children}</MemoryRouter>;

// 1.5.5, C3: the chat greeted a French user in English.
describe("chat in French", () => {
  afterEach(async () => { await act(() => i18n.changeLanguage("en")); });

  it("greets in the language shown, also after a switch", async () => {
    await i18n.changeLanguage("fr");
    const { result } = renderHook(() => useChatIssues(), { wrapper });
    await waitFor(() => expect(result.current.messages[0].text).toBe("Bonjour, comment puis-je vous aider avec vos problèmes techniques aujourd'hui ?"));
    await act(() => i18n.changeLanguage("en"));
    expect(result.current.messages[0].text).toBe("Hi, how can I help you with your technical issues today?");
  });

  it("has no message of its own written in English", () => {
    const src = readFileSync(resolve(__dirname, "../useChatIssues.js"), "utf8");
    expect(src).not.toMatch(/set\w*Error\(\s*["'`][^"'`]*[A-Za-z]{3}/);
    expect(src).not.toMatch(/text:\s*["'`](Hi|Sorry)\b/);
  });

  it("shows the confidence of the issue it opened with in French, sends nothing new", async () => {
    await i18n.changeLanguage("fr");
    const issueContext = { batchId: 7, message: "m", root_cause: "{'description': 'd', 'confidence_level': 'HIGH'}", solution: "s" };
    const withIssue = ({ children }) => <MemoryRouter initialEntries={[{ pathname: "/dash/chat", state: { issueContext } }]}>{children}</MemoryRouter>;
    const { result } = renderHook(() => useChatIssues(), { wrapper: withIssue });
    expect(result.current.contextMessages[0].text).toContain("**Confidence Level:**\nÉlevée");
    // the text sent to the AI is built apart, without the label
    const src = readFileSync(resolve(__dirname, "../useChatIssues.js"), "utf8");
    expect(src).toMatch(/contextText \+= `\*\*Issue from Batch \$\{issueContext\.batchId\}:\*\*\\n\$\{issueContext\.message\}/);
  });

  it("puts the confidence word in French in the issue panel and the commit hint", () => {
    expect(readFileSync(resolve(__dirname, "../../components/issues/IssuePanel.jsx"), "utf8")).toContain("confidenceLabel(t, issue.confidence, issue.confidence_display)");
    expect(readFileSync(resolve(__dirname, "../../components/Issues.jsx"), "utf8")).toContain("confidenceLabel(t, confidence)");
  });
});
