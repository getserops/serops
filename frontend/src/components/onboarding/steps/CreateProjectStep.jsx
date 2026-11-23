/**
 * Create-project step — CTA that opens the CreateProjectModal.
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaFolder } from 'react-icons/fa';

import CreateProjectModal from '../modals/CreateProjectModal';

export default function CreateProjectStep({ status, onDone }) {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);

    return (
        <>
            <Card variant="outlined">
                <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                        <Box sx={{ color: 'primary.main' }}>
                            <FaFolder size={40} />
                        </Box>
                        <Box sx={{ flex: 1 }}>
                            <Typography variant="h6" fontWeight={600} gutterBottom>
                                {t('createProjectStep.title')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('createProjectStep.intro')}
                            </Typography>
                        </Box>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            endIcon={<FaArrowRight />}
                        >
                            {t('createProjectStep.create')}
                        </Button>
                    </Box>
                </CardContent>
            </Card>

            <CreateProjectModal
                open={open}
                onClose={() => setOpen(false)}
                onSaved={onDone}
            />
        </>
    );
}
