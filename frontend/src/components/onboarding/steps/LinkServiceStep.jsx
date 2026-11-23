/**
 * Link-service step. Creating a service here is what triggers the
 * backend's post_save signal to dispatch an immediate batch analysis
 * (see Organisations/signals.py). The wizard's next step polls for
 * that analysis to complete.
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaLink } from 'react-icons/fa';

import LinkServiceModal from '../modals/LinkServiceModal';

export default function LinkServiceStep({ status, onDone }) {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);

    return (
        <>
            <Card variant="outlined">
                <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                        <Box sx={{ color: 'primary.main' }}>
                            <FaLink size={40} />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                            <Typography variant="h6" fontWeight={600} gutterBottom>
                                {t('linkServiceStep.title')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('linkServiceStep.introBefore')}<code>payments-api</code>{t('linkServiceStep.introAfter')}
                            </Typography>
                        </Box>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            endIcon={<FaArrowRight />}
                        >
                            {t('linkServiceStep.link')}
                        </Button>
                    </Box>
                </CardContent>
            </Card>

            <LinkServiceModal
                open={open}
                onClose={() => setOpen(false)}
                onSaved={onDone}
            />
        </>
    );
}
