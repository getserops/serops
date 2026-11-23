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
import { useTranslation } from 'react-i18next';
import { FaArrowRight, FaCog } from 'react-icons/fa';

import CICDModal from '../modals/CICDModal';

const STEP = 'connect_cicd';

export default function CICDStep({ status, onDone, onSkip }) {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [skipping, setSkipping] = useState(false);
    const [error, setError] = useState(null);

    const handleSkip = async () => {
        setError(null);
        setSkipping(true);
        try {
            await onSkip(STEP);
        } catch (err) {
            setError(err?.response?.data?.error || t('scmStep.skipFailed'));
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
                                {t('cicdStep.title')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('cicdStep.intro')}
                            </Typography>
                        </Box>
                    </Box>

                    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                    <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 2 }}>
                        <Button
                            variant="outlined"
                            onClick={handleSkip}
                            disabled={skipping || open}
                            startIcon={skipping ? <CircularProgress aria-label={t('onboarding.loading')} size={16} /> : null}
                        >
                            {t('scmStep.skip')}
                        </Button>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            disabled={skipping}
                            endIcon={<FaArrowRight />}
                        >
                            {t('cicdStep.link')}
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
