/**
 * OnboardingResumeChip — persistent reminder that setup is incomplete.
 *
 * Shown when the user dismissed the wizard (is_skipped=true) but
 * setup isn't actually done (is_completed=false). The distinction
 * exists because the Day 2 backend rework decoupled "hide the UI"
 * from "onboarding is finished" — the chip is what nudges dismissed
 * orgs back to complete setup instead of silently losing them.
 *
 * Clicking Resume calls POST /organisation/onboarding/resume/ (which
 * flips is_skipped back to false), then notifies the parent Dashboard
 * to re-mount the wizard.
 *
 * Renders nothing when the wizard is either currently visible (not
 * dismissed) or when onboarding is fully complete — nothing to nudge.
 *
 * Uses its own useOnboardingStatus polling instance so it works even
 * when the wizard component is unmounted (which it is, whenever the
 * user has dismissed it).
 */

import React, { useState } from 'react';
import { Alert, Box, Button, CircularProgress, Slide } from '@mui/material';
import { FaBell } from 'react-icons/fa';

import { useOnboardingStatus } from './hooks/useOnboardingStatus';

export default function OnboardingResumeChip({ onResume }) {
    const { status, resume } = useOnboardingStatus({ enabled: true });
    const [resuming, setResuming] = useState(false);

    // Only render for dismissed-but-not-complete state. Everything
    // else (loading, completed, actively-in-progress) → nothing.
    const shouldShow = status && status.is_skipped && !status.is_completed;

    const handleResume = async () => {
        setResuming(true);
        try {
            await resume();
            onResume?.();
        } catch {
            // resume() itself is a POST to a same-origin endpoint —
            // the apiClient interceptor handles 401. Any other error
            // is a network hiccup; silently retry-on-next-click.
        } finally {
            setResuming(false);
        }
    };

    if (!shouldShow) return null;

    return (
        <Slide in direction="up" mountOnEnter unmountOnExit>
            <Box
                sx={{
                    position: 'fixed',
                    bottom: 16,
                    right: 16,
                    zIndex: 1300,   // Above most content, below modals (MUI modal z=1300+)
                    maxWidth: 380,
                }}
            >
                <Alert
                    severity="info"
                    icon={<FaBell />}
                    action={
                        <Button
                            color="inherit"
                            size="small"
                            onClick={handleResume}
                            disabled={resuming}
                            startIcon={resuming ? <CircularProgress size={14} /> : null}
                            sx={{ fontWeight: 600 }}
                        >
                            Resume
                        </Button>
                    }
                    sx={{ boxShadow: 3 }}
                >
                    Setup is {status.progress_percentage}% done —
                    finish it whenever you're ready.
                </Alert>
            </Box>
        </Slide>
    );
}
