import { useState, useCallback } from 'react';
import { scanMessageForSensitiveData } from '../services/redaction.service';

/**
 * Hook for scanning chat messages before sending.
 * 
 * Provides:
 * - handleSend: Scans message, shows warning if sensitive data found
 * - handleSendAnyway: User accepted risk, send original message
 * - handleCancel: User wants to edit message
 * - showWarning: Whether to show warning modal
 * - findings: List of sensitive data findings
 * - isScanning: Whether scan is in progress
 * 
 * @param {Function} onSendMessage - Callback to actually send the message
 * @returns {Object} - Hook state and handlers
 */
export const useChatWithScan = (onSendMessage) => {
    const [showWarning, setShowWarning] = useState(false);
    const [pendingMessage, setPendingMessage] = useState('');
    const [findings, setFindings] = useState([]);
    const [isScanning, setIsScanning] = useState(false);

    const handleSend = useCallback(async (message) => {
        if (!message || !message.trim()) {
            return;
        }

        setIsScanning(true);

        try {
            // Scan message before sending
            const scanResult = await scanMessageForSensitiveData(message);

            if (scanResult.has_sensitive_data) {
                // Show warning popup
                setPendingMessage(message);
                setFindings(scanResult.findings);
                setShowWarning(true);
            } else {
                // No sensitive data, send directly
                onSendMessage(message);
            }
        } catch (error) {
            // If scan fails, send anyway (don't block user)
            console.warn('Scan failed, sending anyway:', error);
            onSendMessage(message);
        } finally {
            setIsScanning(false);
        }
    }, [onSendMessage]);

    const handleSendAnyway = useCallback(() => {
        // User accepted the risk, send original message
        if (pendingMessage) {
            onSendMessage(pendingMessage);
        }
        setShowWarning(false);
        setPendingMessage('');
        setFindings([]);
    }, [pendingMessage, onSendMessage]);

    const handleCancel = useCallback(() => {
        // User wants to edit, close modal but keep message
        setShowWarning(false);
        // Return the pendingMessage so component can restore it to input
    }, []);

    const clearWarning = useCallback(() => {
        setShowWarning(false);
        setPendingMessage('');
        setFindings([]);
    }, []);

    return {
        handleSend,
        handleSendAnyway,
        handleCancel,
        clearWarning,
        showWarning,
        findings,
        isScanning,
        pendingMessage,
    };
};

export default useChatWithScan;
