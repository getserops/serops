/**
 * Observability step — CTA that opens the ObservabilityModal.
 * All connect logic lives in the modal.
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaSearch } from 'react-icons/fa';

import ObservabilityModal from '../modals/ObservabilityModal';

export default function ObservabilityStep({ status, onDone }) {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);

    const handleSaved = async () => {
        await onDone?.();
    };

    return (
        <>
            <Card variant="outlined">
                <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                        <Box sx={{ color: 'primary.main' }}>
                            <FaSearch size={40} />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                            <Typography variant="h6" fontWeight={600} gutterBottom>
                                {t('observabilityStep.title')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('observabilityStep.intro')}
                            </Typography>
                        </Box>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            endIcon={<FaArrowRight />}
                        >
                            {t('observabilityStep.connect')}
                        </Button>
                    </Box>
                </CardContent>
            </Card>

            <ObservabilityModal
                open={open}
                onClose={() => setOpen(false)}
                onSaved={handleSaved}
            />
        </>
    );
}
