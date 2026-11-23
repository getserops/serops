/**
 * SCM step — optional. Users can connect a repo or skip for later.
 * Connect flow lives in SCMModal; the "Skip for now" button here
 * calls the wizard's skipStep helper, which persists to
 * skipped_steps on the backend.
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
import { FaArrowRight, FaCodeBranch } from 'react-icons/fa';

import SCMModal from '../modals/SCMModal';

const STEP = 'connect_scm';

export default function SCMStep({ status, onDone, onSkip }) {
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
                            <FaCodeBranch size={40} />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                            <Typography variant="h6" fontWeight={600} gutterBottom>
                                {t('scmStep.title')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('scmStep.intro')}
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
                            {t('scmStep.link')}
                        </Button>
                    </Box>
                </CardContent>
            </Card>

            <SCMModal
                open={open}
                onClose={() => setOpen(false)}
                onSaved={onDone}
            />
        </>
    );
}
