/**
 * WaitingAnalysisStep — the "aha moment" gate.
 *
 * When link_service completes, the backend's post_save signal
 * dispatches an immediate batch analysis (see
 * Organisations/signals.py). This step is what the user looks at
 * while that runs. When the batch has `analyzed_at` set, the
 * wizard's next poll flips `is_completed=true`, the parent
 * shell unmounts us, and the user lands on the dashboard with
 * their first insight ready.
 *
 * Analysis typically takes 15–60s (depends on AI provider + log
 * volume). Anything over ~2 min is unusual — we show a "still
 * running" nudge but never auto-fail. The user can always dismiss
 * the wizard and come back.
 */

import React, { useEffect, useState } from 'react';
import {
    Box,
    Card,
    CardContent,
    CircularProgress,
    Fade,
    LinearProgress,
    Typography,
} from '@mui/material';
import { FaBolt } from 'react-icons/fa';

// Show a "still running" nudge after this many ms so the user
// doesn't think the wizard is stuck.
const STILL_RUNNING_MS = 30_000;

export default function WaitingAnalysisStep({ status }) {
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        const start = Date.now();
        const t = setInterval(() => setElapsed(Date.now() - start), 1000);
        return () => clearInterval(t);
    }, []);

    const stillRunning = elapsed > STILL_RUNNING_MS;
    // Cap progress at 90% while waiting — the last 10% pops when the
    // status actually flips. Small quality-of-life touch: the bar
    // creeps toward "almost done" so it feels alive.
    const fauxProgress = Math.min(90, (elapsed / 60_000) * 90);

    return (
        <Card variant="outlined">
            <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                    <Box sx={{ position: 'relative', display: 'inline-flex' }}>
                        <CircularProgress size={48} thickness={4} />
                        <Box
                            sx={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                right: 0,
                                bottom: 0,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                color: 'primary.main',
                            }}
                        >
                            <FaBolt size={20} />
                        </Box>
                    </Box>
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="h6" fontWeight={600} gutterBottom>
                            Waiting for your first analysis…
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            We've kicked off a batch analysis in the background.
                            When it lands, we'll drop you straight into your
                            first insight.
                        </Typography>
                    </Box>
                </Box>

                <LinearProgress
                    variant="determinate"
                    value={fauxProgress}
                    sx={{ height: 6, borderRadius: 3, mb: 1 }}
                />
                <Typography variant="caption" color="text.secondary">
                    Elapsed {Math.round(elapsed / 1000)}s
                </Typography>

                <Fade in={stillRunning}>
                    <Box sx={{ mt: 2 }}>
                        <Typography variant="body2" color="text.secondary">
                            Still running — first analyses can take up to a
                            minute or two depending on your AI provider and
                            log volume. You can dismiss this wizard and
                            we'll notify you when it's ready.
                        </Typography>
                    </Box>
                </Fade>
            </CardContent>
        </Card>
    );
}
