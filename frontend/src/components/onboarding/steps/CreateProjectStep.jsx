/**
 * Create-project step — CTA that opens the CreateProjectModal.
 */

import React, { useState } from 'react';
import { Box, Button, Card, CardContent, Typography } from '@mui/material';
import { FaArrowRight, FaFolder } from 'react-icons/fa';

import CreateProjectModal from '../modals/CreateProjectModal';

export default function CreateProjectStep({ status, onDone }) {
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
                                Create your first project
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                A project is a grouping of services SerOps
                                analyzes together — e.g. "Payments Backend"
                                or "Data Pipeline". Default environments
                                (development, staging, production) are created
                                for you.
                            </Typography>
                        </Box>
                    </Box>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            onClick={() => setOpen(true)}
                            endIcon={<FaArrowRight />}
                        >
                            Create project
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
