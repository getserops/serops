/**
 * Link-service step. Creating a service here is what triggers the
 * backend's post_save signal to dispatch an immediate batch analysis
 * (see Organisations/signals.py). The wizard's next step polls for
 * that analysis to complete.
 */

import React, { useState } from 'react';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaLink } from 'react-icons/fa';

import LinkServiceModal from '../modals/LinkServiceModal';

export default function LinkServiceStep({ status, onDone }) {
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
                                Link a service
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                Tell us the name of a service in your project
                                (e.g. <code>payments-api</code>). As soon as
                                you add it, we'll kick off your first
                                analysis in the background.
                            </Typography>
                        </Box>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            endIcon={<FaArrowRight />}
                        >
                            Link service
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
