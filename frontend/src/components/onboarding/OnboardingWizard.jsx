/**
 * OnboardingWizard — shell that drives the computed-state wizard.
 *
 * Reworked 2026-08-30 (item #11). See the plan file and the backend
 * OnboardingStatus model docstring for design rationale. Summary:
 *
 *   - No "Mark Complete" buttons anywhere. The backend recomputes
 *     step-by-step completion on every status GET from real DB state.
 *   - Each step renders its own action (modal trigger, skip button).
 *   - The shell only handles: polling, stepper display, dismiss.
 *
 * Interface with the parent (Dashboard.jsx) is preserved: onComplete
 * fires once `status.is_completed` flips true; onSkip fires when the
 * user dismisses the wizard via the top-right X.
 */

import React from 'react';
import {
    Alert,
    Box,
    Card,
    CardContent,
    CircularProgress,
    IconButton,
    LinearProgress,
    Step,
    StepLabel,
    Stepper,
    Typography,
} from '@mui/material';
import { FaArrowLeft, FaTimes } from 'react-icons/fa';

import { useOnboardingStatus } from './hooks/useOnboardingStatus';
import WelcomeStep from './steps/WelcomeStep';
import AIProviderStep from './steps/AIProviderStep';
import ObservabilityStep from './steps/ObservabilityStep';
import CreateProjectStep from './steps/CreateProjectStep';
import LinkServiceStep from './steps/LinkServiceStep';
import SCMStep from './steps/SCMStep';
import CICDStep from './steps/CICDStep';
import WaitingAnalysisStep from './steps/WaitingAnalysisStep';
import './OnboardingWizard.css';

// Steps rendered in the stepper header. Excludes 'welcome' + 'completed'
// so the visual step count matches user-visible required work.
const HEADER_STEPS = [
    { code: 'connect_ai_provider', label: 'AI Model' },
    { code: 'connect_observability', label: 'Observability' },
    { code: 'create_project', label: 'Project' },
    { code: 'link_service', label: 'Service' },
    { code: 'connect_scm', label: 'Source Control' },
    { code: 'connect_cicd', label: 'CI/CD' },
    { code: 'waiting_for_first_analysis', label: 'First Analysis' },
];

function renderStepBody(step, status, actions) {
    switch (step) {
        case 'welcome':
            return <WelcomeStep onContinue={actions.refresh} />;
        case 'connect_ai_provider':
            return <AIProviderStep status={status} onDone={actions.refresh} />;
        case 'connect_observability':
            return <ObservabilityStep status={status} onDone={actions.refresh} />;
        case 'create_project':
            return <CreateProjectStep status={status} onDone={actions.refresh} />;
        case 'link_service':
            return <LinkServiceStep status={status} onDone={actions.refresh} />;
        case 'connect_scm':
            return (
                <SCMStep
                    status={status}
                    onDone={actions.refresh}
                    onSkip={actions.skipStep}
                />
            );
        case 'connect_cicd':
            return (
                <CICDStep
                    status={status}
                    onDone={actions.refresh}
                    onSkip={actions.skipStep}
                />
            );
        case 'waiting_for_first_analysis':
            return <WaitingAnalysisStep status={status} />;
        default:
            return null;
    }
}

export default function OnboardingWizard({ onComplete, onSkip }) {
    const [minimized, setMinimized] = React.useState(false);
    const {
        status, loading, error,
        refresh, skipStep, storeData, dismiss,
    } = useOnboardingStatus({ enabled: true });

    // Notify parent when onboarding resolves (completed or dismissed).
    // Uses refs to avoid re-firing on every re-render.
    const notifiedCompleteRef = React.useRef(false);
    const notifiedSkipRef = React.useRef(false);
    React.useEffect(() => {
        if (!status) return;
        if (status.is_completed && !notifiedCompleteRef.current) {
            notifiedCompleteRef.current = true;
            onComplete?.();
        }
        if (status.is_skipped && !notifiedSkipRef.current) {
            notifiedSkipRef.current = true;
            onSkip?.();
        }
    }, [status, onComplete, onSkip]);

    // Guard: hide immediately when resolved. Parent will unmount us.
    if (status?.is_completed || status?.is_skipped) {
        return null;
    }

    if (loading && !status) {
        return (
            <Card className="onboarding-wizard loading">
                <CardContent sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                    <CircularProgress />
                </CardContent>
            </Card>
        );
    }

    if (minimized) {
        return (
            <Card
                className="onboarding-wizard minimized"
                onClick={() => setMinimized(false)}
            >
                <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2, p: 2, '&:last-child': { pb: 2 } }}>
                    <CircularProgress
                        variant="determinate"
                        value={status?.progress_percentage || 0}
                        size={40}
                        thickness={4}
                    />
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="body2" fontWeight={600}>
                            Setup — {status?.progress_percentage || 0}%
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            Click to expand
                        </Typography>
                    </Box>
                </CardContent>
            </Card>
        );
    }

    const currentStep = status?.current_step || 'welcome';
    const currentIndex = Math.max(
        0,
        HEADER_STEPS.findIndex((s) => s.code === currentStep),
    );

    const actions = { refresh, skipStep, storeData };

    return (
        <Card className="onboarding-wizard">
            <CardContent>
                {/* Header */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 3 }}>
                    <Box>
                        <Typography variant="h5" fontWeight={600} gutterBottom>
                            Getting Started
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            Connect the pieces so we can run your first AI analysis.
                        </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                        <IconButton
                            size="small"
                            onClick={() => setMinimized(true)}
                            title="Minimize"
                            aria-label="Minimize wizard"
                        >
                            <FaArrowLeft />
                        </IconButton>
                        <IconButton
                            size="small"
                            onClick={dismiss}
                            title="Dismiss wizard (reversible)"
                            aria-label="Dismiss wizard"
                        >
                            <FaTimes />
                        </IconButton>
                    </Box>
                </Box>

                {error && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                        {/* JSX auto-escapes — safe to render server-supplied string */}
                        {error}
                    </Alert>
                )}

                {/* Progress bar */}
                <Box sx={{ mb: 3 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="caption" color="text.secondary">
                            Progress
                        </Typography>
                        <Typography variant="caption" fontWeight={600}>
                            {status?.progress_percentage || 0}%
                        </Typography>
                    </Box>
                    <LinearProgress
                        variant="determinate"
                        value={status?.progress_percentage || 0}
                        sx={{ height: 8, borderRadius: 4 }}
                    />
                </Box>

                {/* Stepper */}
                <Stepper activeStep={currentIndex} alternativeLabel sx={{ mb: 4 }}>
                    {HEADER_STEPS.map((s) => {
                        const isCompleted = status?.completed_steps?.includes(s.code)
                            || status?.skipped_steps?.includes(s.code);
                        return (
                            <Step key={s.code} completed={isCompleted}>
                                <StepLabel>
                                    <Typography variant="caption">{s.label}</Typography>
                                </StepLabel>
                            </Step>
                        );
                    })}
                </Stepper>

                {/* Current step body */}
                {renderStepBody(currentStep, status, actions)}
            </CardContent>
        </Card>
    );
}
