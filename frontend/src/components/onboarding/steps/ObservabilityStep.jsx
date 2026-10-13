/**
 * Observability step — CTA that opens the ObservabilityModal.
 * All connect logic lives in the modal.
 */

import React, { useState } from 'react';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaSearch } from 'react-icons/fa';

import ObservabilityModal from '../modals/ObservabilityModal';

export default function ObservabilityStep({ status, onDone }) {
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
                                Connect an observability source
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                Point SerOps at your log store (Elasticsearch,
                                Loki, Datadog, CloudWatch…). We'll pull recent
                                logs into every batch analysis. Metrics are
                                optional for the same provider.
                            </Typography>
                        </Box>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            endIcon={<FaArrowRight />}
                        >
                            Connect source
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
