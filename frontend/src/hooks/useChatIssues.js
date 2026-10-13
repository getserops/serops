/**
 * useChatIssues - Custom hook for managing chat state and interactions
 * Extracted from ChatIssues.jsx for better separation of concerns
 * 
 * Handles:
 * - Message state and sending
 * - Chat history management
 * - Model selection
 * - Session management
 * - Root cause parsing and formatting
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useLocation } from "react-router-dom";
import {
    sendChatMessage,
    getChatHistory,
    getSessionMessages,
    deleteChatSession,
} from "../services/chatService";
import SettingsService from "../services/settings.service";
import { formatAnalysisResult } from "../services/data.service";
import { scanMessageForSensitiveData } from "../services/redaction.service";
import { isDemoUser } from '../utils/demo';

/**
 * Parse root cause from various formats (JSON, Python dict, string)
 */
export const parseRootCause = (rootCause) => {
    if (!rootCause) return null;

    // Already an object
    if (typeof rootCause === "object") return rootCause;

    // Try to parse as JSON
    if (typeof rootCause === "string") {
        try {
            return JSON.parse(rootCause);
        } catch {
            // Try regex extraction for Python-style dict
            try {
                if (
                    rootCause.trim().startsWith("{") &&
                    rootCause.includes("'description'")
                ) {
                    const result = {};

                    // Extract description using regex
                    const descMatch = rootCause.match(
                        /'description':\s*['"](.*?)['"],\s*(?:'evidence'|'confidence_level'|$)/s
                    );
                    if (descMatch) {
                        result.description = descMatch[1]
                            .replace(/\\'/g, "'")
                            .replace(/\\n/g, "\n");
                    }

                    // Extract evidence array
                    const evidenceMatch = rootCause.match(
                        /'evidence':\s*\[(.*?)\],?\s*(?:'confidence_level'|$)/s
                    );
                    if (evidenceMatch) {
                        const evidenceItems = [];
                        const itemRegex = /'([^']*(?:\\'[^']*)*)'/g;
                        let match;
                        while ((match = itemRegex.exec(evidenceMatch[1])) !== null) {
                            evidenceItems.push(match[1].replace(/\\'/g, "'"));
                        }
                        if (evidenceItems.length > 0) {
                            result.evidence = evidenceItems;
                        }
                    }

                    // Extract confidence_level
                    const confMatch = rootCause.match(
                        /'confidence_level':\s*['"](\w+)['"]/
                    );
                    if (confMatch) {
                        result.confidence_level = confMatch[1];
                    }

                    if (Object.keys(result).length > 0) {
                        return result;
                    }
                }
            } catch {
                // Fall through to return null
            }
        }
    }

    return null;
};

/**
 * Format root cause for display
 */
export const formatRootCause = (rootCause) => {
    if (!rootCause) return "No root cause provided";

    const parsed = parseRootCause(rootCause);

    if (parsed && typeof parsed === "object") {
        let result = parsed.description || "No description provided";

        if (
            parsed.evidence &&
            Array.isArray(parsed.evidence) &&
            parsed.evidence.length > 0
        ) {
            result +=
                "\n\n**Evidence:**\n" + parsed.evidence.slice(0, 3).join("\n");
            if (parsed.evidence.length > 3) {
                result += `\n... and ${parsed.evidence.length - 3} more`;
            }
        }

        return result;
    }

    return rootCause.toString();
};

/**
 * Get confidence level from root cause
 */
export const getConfidenceLevel = (rootCause) => {
    if (!rootCause) return null;

    const parsed = parseRootCause(rootCause);

    if (parsed && typeof parsed === "object" && parsed.confidence_level) {
        return parsed.confidence_level;
    }
    return null;
};

/**
 * Process messages into formatted structure
 */
const processMessagesNormally = (messages, formatted) => {
    messages.forEach((msg, idx) => {
        formatted.push({
            id: idx * 2,
            sender: "user",
            text: msg.message,
            timestamp: msg.timestamp,
        });
        if (msg.response) {
            formatted.push({
                id: idx * 2 + 1,
                sender: "bot",
                text: msg.response,
                timestamp: msg.timestamp,
            });
        }
    });
};

/**
 * Custom hook for chat issues functionality
 */
export const useChatIssues = () => {
    const location = useLocation();
    const issueContext = location.state?.issueContext;
    const analysisResult = location.state?.analysisResult;
    const { sessionId } = location.state || {};

    // Build context messages
    const contextMessages = [];
    if (analysisResult) {
        contextMessages.push({
            id: 0,
            sender: "bot",
            text: `Batch Analysis Summary:\n${formatAnalysisResult(analysisResult)}`,
            timestamp: new Date().toISOString(),
        });
    }

    if (issueContext) {
        const confidenceLevel = getConfidenceLevel(issueContext.root_cause);
        const confidenceSection = confidenceLevel
            ? `\n\n**Confidence Level:**\n${confidenceLevel}`
            : "";

        contextMessages.push({
            id: 1,
            sender: "user",
            text: `**Issue from Batch ${issueContext.batchId || issueContext.batch}:**\n${issueContext.message
                }\n\n**Root Cause:**\n${formatRootCause(
                    issueContext.root_cause
                )}${confidenceSection}\n\n**Recommended Action:**\n${issueContext.solution || "No solution provided"
                }`,
            timestamp: new Date().toISOString(),
            isIssueContext: true,
        });
    }

    // State
    const [messages, setMessages] = useState(
        !analysisResult && !issueContext
            ? [
                {
                    id: -1,
                    sender: "bot",
                    text: "Hi, how can I help you with your technical issues today?",
                    timestamp: new Date().toISOString(),
                },
            ]
            : []
    );
    const [input, setInput] = useState("");
    const [selectedModel, setSelectedModel] = useState("gemini");
    const [availableModels, setAvailableModels] = useState([]); // Dynamic models
    const [isLoading, setIsLoading] = useState(false);
    const isDemo = isDemoUser();
    const [error, setError] = useState(null);
    const [showHistory, setShowHistory] = useState(false);
    const [chatHistory, setChatHistory] = useState([]);
    const [currentSessionId, setCurrentSessionId] = useState(null);
    const messagesEndRef = useRef(null);
    const initialContextSent = useRef(false);

    // Track if loaded from history (to prevent duplicate context)
    const [loadedFromHistory, setLoadedFromHistory] = useState(false);

    // Sensitive data scan state
    const [isScanning, setIsScanning] = useState(false);
    const [showSensitiveWarning, setShowSensitiveWarning] = useState(false);
    const [sensitiveFindings, setSensitiveFindings] = useState([]);
    const [pendingMessage, setPendingMessage] = useState("");

    // Scroll to bottom
    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
        scrollToBottom();
    }, [messages]);

    // Fetch available models — providers with a configured API key
    // for this org. Empty list = "no AI provider set up" and the UI
    // renders an empty state (see ChatIssues dropdown).
    //
    // Prior code fell back to a hardcoded [Gemini, DeepSeek] list on
    // fetch failure. That was misleading:
    //   * Only two of the five real providers (Claude missing entirely).
    //   * Picking a hardcoded id when the org has no API key for it
    //     500s at chat time — the user thinks they picked a valid
    //     model but hits AUTH_ERROR instead.
    //   * The URL was actually wrong, so the fallback fired on every
    //     call.
    // Now we surface the empty list honestly and let the dropdown
    // point users at Settings.
    useEffect(() => {
        const fetchModels = async () => {
            try {
                const data = await SettingsService.getAvailableModels();
                const models = (data && data.models) || [];
                setAvailableModels(models);
                // Auto-select the first model when the current selection
                // isn't one of the returned ids. Applies on fresh load
                // AND when a previously-selected provider gets removed.
                if (models.length > 0) {
                    const ids = new Set(models.map((m) => m.id));
                    if (!selectedModel || !ids.has(selectedModel)) {
                        setSelectedModel(models[0].id);
                    }
                }
            } catch (error) {
                console.error("Failed to fetch available models:", error);
                setAvailableModels([]);
            }
        };
        fetchModels();
    }, []);

    // Load session from URL
    useEffect(() => {
        if (sessionId) {
            setCurrentSessionId(sessionId);
            getSessionMessages(sessionId).then((data) => {
                if (Array.isArray(data.messages)) {
                    const formatted = data.messages.flatMap((msg, idx) => {
                        const messages = [
                            {
                                id: idx * 2,
                                sender: "user",
                                text: msg.message,
                                timestamp: msg.timestamp,
                            },
                        ];

                        if (msg.response) {
                            messages.push({
                                id: idx * 2 + 1,
                                sender: "bot",
                                text: msg.response,
                                timestamp: msg.timestamp,
                            });
                        }

                        return messages;
                    });
                    setMessages(formatted);
                }
            });
        }
    }, [sessionId]);

    // Fetch history
    const fetchHistory = async () => {
        try {
            const history = await getChatHistory();
            setChatHistory(history.sessions || []);
        } catch (error) {
            console.error("Failed to fetch chat history:", error);
            setChatHistory([]);
        }
    };

    useEffect(() => {
        fetchHistory();
    }, []);

    // Actual send logic (called after scan passes or user confirms)
    const doSendMessage = useCallback(async (messageText) => {
        const userMessage = {
            id: Date.now(),
            sender: "user",
            text: messageText,
            model: selectedModel,
            timestamp: new Date().toISOString(),
        };

        setMessages((prev) => {
            const filteredMessages = prev.filter((msg) => msg.id !== -1);
            return [...filteredMessages, userMessage];
        });

        setInput("");
        setError(null);
        setIsLoading(true);

        try {
            let messageToSend = messageText;

            if (
                !currentSessionId &&
                !initialContextSent.current &&
                (issueContext || analysisResult)
            ) {
                initialContextSent.current = true;
                let contextText = "";

                if (analysisResult) {
                    contextText += `Batch Analysis Summary:\n${formatAnalysisResult(
                        analysisResult
                    )}\n\n`;
                }

                if (issueContext) {
                    contextText += `**Issue from Batch ${issueContext.batchId}:**\n${issueContext.message}\n\n**Root Cause:**\n${issueContext.root_cause}\n\n**Recommended Action:**\n${issueContext.solution}\n\n`;
                }

                messageToSend = `${contextText}${messageText}`;
            }

            const botResponse = await sendChatMessage(
                messageToSend,
                selectedModel,
                currentSessionId,
                issueContext?.batchId || analysisResult?.batch_id
            );

            const botMessage = {
                id: Date.now() + 1,
                sender: "bot",
                text: botResponse,
                model: selectedModel,
                timestamp: new Date().toISOString(),
            };
            setMessages((prev) => [...prev, botMessage]);

            if (!currentSessionId) {
                const updatedHistory = await getChatHistory();
                setChatHistory(updatedHistory.sessions || []);
                if (updatedHistory.sessions?.[0]?.chat_id) {
                    setCurrentSessionId(updatedHistory.sessions[0].chat_id);
                }
            }
        } catch (error) {
            console.error("API Error:", error);

            // Demo visitors can't write — surface an accurate message
            // instead of "Error with gemini: demo_read_only" which
            // reads as if the AI provider failed. The whole request
            // never reached Gemini; the DemoUserMiddleware blocked it
            // upstream. Self-hosting is the only way to try chat, so
            // the copy points there rather than at a signup flow.
            // The chat UI disables sending for demo users, so this is only
            // a fallback (for instance a stale login payload). Shown once,
            // in the banner: it is a deliberate block, not a model reply.
            if (error.code === 'demo_read_only') {
                setError("This live demo is read-only. Self-host SerOps to try chat with your own data.");
                return;
            }

            setError(`Error with ${selectedModel}: ${error.message}`);
            setMessages((prev) => [...prev, {
                id: Date.now() + 1,
                sender: "bot",
                text: `Sorry, an error occurred with ${selectedModel}. Please try again.`,
                isError: true,
                model: selectedModel,
                timestamp: new Date().toISOString(),
            }]);
        } finally {
            setIsLoading(false);
        }
    }, [selectedModel, currentSessionId, issueContext, analysisResult]);

    // Send message handler with sensitive data scan
    const handleSend = async () => {
        if (isDemo || input.trim() === "" || isLoading || isScanning) return;

        setIsScanning(true);

        try {
            // Scan for sensitive data before sending
            const scanResult = await scanMessageForSensitiveData(input);

            if (scanResult.has_sensitive_data) {
                // Show warning popup
                setPendingMessage(input);
                setSensitiveFindings(scanResult.findings);
                setShowSensitiveWarning(true);
                setIsScanning(false);
                return;
            }

            // No sensitive data, send directly
            await doSendMessage(input);
        } catch (error) {
            // If scan fails, send anyway (don't block user)
            console.warn('Scan failed, sending anyway:', error);
            await doSendMessage(input);
        } finally {
            setIsScanning(false);
        }
    };

    // User chose to send despite warning
    const handleSendAnyway = useCallback(async () => {
        setShowSensitiveWarning(false);
        const message = pendingMessage;
        setPendingMessage("");
        setSensitiveFindings([]);
        await doSendMessage(message);
    }, [pendingMessage, doSendMessage]);

    // User chose to cancel and edit
    const handleCancelSend = useCallback(() => {
        setShowSensitiveWarning(false);
        // Keep pendingMessage in input so user can edit
        setInput(pendingMessage);
        setPendingMessage("");
        setSensitiveFindings([]);
    }, [pendingMessage]);

    // Model selection
    const handleSelectModel = (model) => {
        setSelectedModel(model);
        setError(null);
    };

    // Key press handler
    const handleKeyPress = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    // History toggle
    const toggleHistory = () => {
        setShowHistory(!showHistory);
    };

    // Load chat from history
    const loadChatFromHistory = async (session) => {
        setCurrentSessionId(session.chat_id);
        setShowHistory(false);
        setLoadedFromHistory(true);  // Mark as loaded from history
        try {
            const data = await getSessionMessages(session.chat_id);
            if (Array.isArray(data.messages)) {
                const formatted = [];

                if (
                    data.messages.length > 0 &&
                    data.messages[0].message.includes("Issue from Batch")
                ) {
                    const firstMessage = data.messages[0];
                    const messageContent = firstMessage.message;

                    const issueMatch = messageContent.match(
                        /Issue from Batch (.*?):([\s\S]*?)Root Cause:([\s\S]*?)Recommended Action:([\s\S]*?)(?=\n\n|$)/
                    );

                    if (issueMatch) {
                        const [, batchId, issueText, rootCause, solution] = issueMatch;

                        formatted.push({
                            id: -100,
                            sender: "bot",
                            text: `**Issue from Batch ${batchId.trim()}:**\n${issueText.trim()}\n\n**Root Cause:**\n${rootCause.trim()}\n\n**Recommended Action:**\n${solution.trim()}`,
                            timestamp: firstMessage.timestamp,
                            isIssueContext: true,
                        });

                        const userMessageMatch = messageContent.match(
                            /(?:Recommended Action:[\s\S]*?\n\n)([\s\S]*)/
                        );
                        if (userMessageMatch && userMessageMatch[1].trim()) {
                            formatted.push({
                                id: -99,
                                sender: "user",
                                text: userMessageMatch[1].trim(),
                                timestamp: firstMessage.timestamp,
                            });
                        }

                        if (firstMessage.response) {
                            formatted.push({
                                id: -98,
                                sender: "bot",
                                text: firstMessage.response,
                                timestamp: firstMessage.timestamp,
                            });
                        }

                        data.messages.slice(1).forEach((msg, idx) => {
                            formatted.push({
                                id: idx * 2,
                                sender: "user",
                                text: msg.message,
                                timestamp: msg.timestamp,
                            });
                            if (msg.response) {
                                formatted.push({
                                    id: idx * 2 + 1,
                                    sender: "bot",
                                    text: msg.response,
                                    timestamp: msg.timestamp,
                                });
                            }
                        });
                    } else {
                        processMessagesNormally(data.messages, formatted);
                    }
                } else {
                    processMessagesNormally(data.messages, formatted);
                }

                setMessages(formatted);
            } else {
                setMessages([]);
            }
        } catch (e) {
            console.error("Error loading chat history:", e);
            setMessages([]);
        }
    };

    // Delete session
    const deleteSession = async (chatId) => {
        try {
            await deleteChatSession(chatId);
            fetchHistory();
            if (currentSessionId === chatId) {
                setCurrentSessionId(null);
                setMessages([
                    {
                        id: -1,
                        sender: "bot",
                        text: "Hi, how can I help you with your technical issues today?",
                        timestamp: new Date().toISOString(),
                    },
                ]);
            }
        } catch (error) {
            console.error("Failed to delete chat session:", error);
            setError("Failed to delete chat session");
        }
    };

    return {
        // Context
        contextMessages,
        issueContext,
        analysisResult,

        // State
        messages,
        input,
        setInput,
        selectedModel,
        availableModels, // Exported for UI
        isLoading,
        error,
        isDemo,
        showHistory,
        chatHistory,
        messagesEndRef,
        loadedFromHistory,

        // Handlers
        handleSend,
        handleSelectModel,
        handleKeyPress,
        toggleHistory,
        loadChatFromHistory,
        deleteSession,

        // Sensitive data scan
        isScanning,
        showSensitiveWarning,
        sensitiveFindings,
        handleSendAnyway,
        handleCancelSend,
    };
};

export default useChatIssues;
