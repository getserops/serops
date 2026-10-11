/**
 * CI/CD step — optional. Same shape as SCMStep — connect via modal
 * or defer via "Skip for now" (persisted to skipped_steps).
 */

import React, { useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    CircularProgress,
    Typography,
} from '@mui/material';
import { FaArrowRight, FaCog } from 'react-icons/fa';

import CICDModal from '../modals/CICDModal';

const STEP = 'connect_cicd';

export default function CICDStep({ status, onDone, onSkip }) {
    const [open, setOpen] = useState(false);
    const [skipping, setSkipping] = useState(false);
    const [error, setError] = useState(null);

    const handleSkip = async () => {
        setError(null);
        setSkipping(true);
        try {
            await onSkip(STEP);
        } catch (err) {
            setError(err?.response?.data?.error || 'Could not skip this step');
        } finally {
            setSkipping(false);
        }
    };

    return (
        <>
            <Card variant="outlined">
                <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                        <Box sx={{ color: 'primary.main' }}>
                            <FaCog size={40} />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                            <Typography variant="h6" fontWeight={600} gutterBottom>
                                Connect CI/CD (optional)
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                Link a build or deploy pipeline so AI can
                                correlate incidents with recent deployments.
                                You can skip this and add it later from Settings.
                            </Typography>
                        </Box>
                    </Box>

                    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                    <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 2 }}>
                        <Button
                            variant="outlined"
                            onClick={handleSkip}
                            disabled={skipping || open}
                            startIcon={skipping ? <CircularProgress size={16} /> : null}
                        >
                            Skip for now
                        </Button>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            disabled={skipping}
                            endIcon={<FaArrowRight />}
                        >
                            Link pipeline
                        </Button>
                    </Box>
                </CardContent>
            </Card>

            <CICDModal
                open={open}
                onClose={() => setOpen(false)}
                onSaved={onDone}
            />
        </>
    );
}
