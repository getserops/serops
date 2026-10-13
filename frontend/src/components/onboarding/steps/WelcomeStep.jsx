/**
 * Splash step — informational, no gate. Advancing is a UI-only click;
 * the underlying `welcome` computed-state is always true, so as soon
 * as the user clicks past this step the wizard cursor lands on the
 * first un-resolved required step (AI provider by default).
 */

import React from 'react';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaCog } from 'react-icons/fa';

export default function WelcomeStep({ onContinue }) {
    return (
        <Card variant="outlined">
            <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                    <Box sx={{ color: 'primary.main' }}>
                        <FaCog size={48} />
                    </Box>
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="h6" fontWeight={600} gutterBottom>
                            Welcome to SerOps
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            Let's connect your first AI model and log source
                            so we can run your first analysis. The wizard
                            watches your workspace as you go — no need to
                            confirm each step.
                        </Typography>
                    </Box>
                </Box>
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
                    <Button
                        variant="contained"
                        onClick={onContinue}
                        endIcon={<FaArrowRight />}
                    >
                        Get Started
                    </Button>
                </Box>
            </CardContent>
        </Card>
    );
}
