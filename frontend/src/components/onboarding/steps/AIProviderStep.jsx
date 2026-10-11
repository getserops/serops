/**
 * AI provider step — thin wrapper that renders a summary card plus
 * an "Add" CTA that opens the AIProviderModal. The heavy lifting
 * (provider list, key input, test-connection, save) all lives in
 * the modal — this file stays presentational so the wizard shell
 * doesn't accumulate feature-specific state.
 */

import React, { useState } from 'react';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaRobot } from 'react-icons/fa';

import AIProviderModal from '../modals/AIProviderModal';

export default function AIProviderStep({ status, onDone }) {
    const [open, setOpen] = useState(false);

    const handleSaved = async () => {
        // The parent shell's polling loop will pick up the new state,
        // but calling refresh explicitly gives instant feedback.
        await onDone?.();
    };

    return (
        <>
            <Card variant="outlined">
                <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                        <Box sx={{ color: 'primary.main' }}>
                            <FaRobot size={40} />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                            <Typography variant="h6" fontWeight={600} gutterBottom>
                                Choose your AI model
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                SerOps supports Gemini, Claude, OpenAI, DeepSeek,
                                and Ollama (local). Pick one and add your key —
                                we'll encrypt it at rest and use it for every
                                batch analysis.
                            </Typography>
                        </Box>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            endIcon={<FaArrowRight />}
                        >
                            Configure AI provider
                        </Button>
                    </Box>
                </CardContent>
            </Card>

            <AIProviderModal
                open={open}
                onClose={() => setOpen(false)}
                onSaved={handleSaved}
            />
        </>
    );
}
