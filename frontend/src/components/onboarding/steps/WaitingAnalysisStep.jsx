/**
 * WaitingAnalysisStep — the "aha moment" gate.
 *
 * When link_service completes, the backend's post_save signal
 * dispatches an immediate batch analysis (see
 * Organisations/signals.py). This step is what the user looks at
 * while that runs. When the batch has `analyzed_at` set, the
 * wizard's next poll flips `is_completed=true`, the parent
 * shell unmounts us, and the user lands on the dashboard with
 * their first insight ready.
 *
 * Analysis typically takes 15–60s (depends on AI provider + log
 * volume). Anything over ~2 min is unusual — we show a "still
 * running" nudge but never auto-fail. The user can always dismiss
 * the wizard and come back.
 *
 * When nothing has landed after CHECK_DATA_MS, or the scheduler already
 * says a run found nothing to analyse, the step says why and links to
 * "Check my data" on the project page, instead of a spinner that never
 * ends. Only a link: the check itself made the floating wizard taller than
 * the screen, its Minimize button went off-screen and a new customer could
 * not get it out of the way (journey suite, 2026-10-28).
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
    Box,
    Button,
    Card,
    CardContent,
    CircularProgress,
    Fade,
    LinearProgress,
    Typography,
} from '@mui/material';
import { FaBolt } from 'react-icons/fa';
import { Link as RouterLink } from 'react-router-dom';
import { ProjectService } from '../../../services/project.service';

// Show a "still running" nudge after this many ms so the user
// doesn't think the wizard is stuck.
const STILL_RUNNING_MS = 30_000;
// Offer "Check my data" after this long without a first analysis.
const CHECK_DATA_MS = 120_000;
const RUNS_POLL_MS = 30_000;

/** The project the person just set up, and whether a run found nothing. */
function useFirstProject() {
    const [project, setProject] = useState(null);
    const [nothingFound, setNothingFound] = useState(false);
    const [lastRun, setLastRun] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const projects = await ProjectService.GetProjects();
                // The newest project: the one created in this wizard.
                const first = Array.isArray(projects) && projects.length
                    ? [...projects].sort((x, y) => String(y.created_at).localeCompare(String(x.created_at)))[0]
                    : null;
                if (!first || cancelled) return;
                const details = await ProjectService.GetProjectDetails(first.id).catch(() => first);
                if (!cancelled) setProject({ id: first.id, environments: details?.environments || [] });
            } catch {
                /* the check is a help, never a blocker */
            }
        })();
        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        if (!project || nothingFound) return undefined;
        let cancelled = false;
        const poll = async () => {
            try {
                const data = await ProjectService.GetDataRuns(project.id);
                const runs = Array.isArray(data?.runs) ? data.runs : [];
                const empty = runs.find((r) => r.outcome !== 'batch');
                if (!cancelled && empty) {
                    setLastRun(empty);
                    setNothingFound(true);
                }
            } catch {
                /* ignore */
            }
        };
        poll();
        const timer = setInterval(poll, RUNS_POLL_MS);
        return () => { cancelled = true; clearInterval(timer); };
    }, [project, nothingFound]);

    return { project, nothingFound, lastRun };
}

export default function WaitingAnalysisStep({ status }) {
    const { t } = useTranslation();
    const [elapsed, setElapsed] = useState(0);
    const { project, nothingFound, lastRun } = useFirstProject();

    useEffect(() => {
        const start = Date.now();
        const t = setInterval(() => setElapsed(Date.now() - start), 1000);
        return () => clearInterval(t);
    }, []);

    const stillRunning = elapsed > STILL_RUNNING_MS;
    const offerCheck = project && (nothingFound || elapsed > CHECK_DATA_MS);
    // Cap progress at 90% while waiting — the last 10% pops when the
    // status actually flips. Small quality-of-life touch: the bar
    // creeps toward "almost done" so it feels alive.
    const fauxProgress = Math.min(90, (elapsed / 60_000) * 90);

    return (
        <Card variant="outlined">
            <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 3, mb: 2 }}>
                    <Box sx={{ position: 'relative', display: 'inline-flex' }}>
                        <CircularProgress size={48} thickness={4} />
                        <Box
                            sx={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                right: 0,
                                bottom: 0,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                color: 'primary.main',
                            }}
                        >
                            <FaBolt size={20} />
                        </Box>
                    </Box>
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="h6" fontWeight={600} gutterBottom>
                            Waiting for your first analysis…
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            We've kicked off a batch analysis in the background.
                            When it lands, we'll drop you straight into your
                            first insight.
                        </Typography>
                    </Box>
                </Box>

                <LinearProgress
                    variant="determinate"
                    value={fauxProgress}
                    sx={{ height: 6, borderRadius: 3, mb: 1 }}
                />
                <Typography variant="caption" color="text.secondary">
                    Elapsed {Math.round(elapsed / 1000)}s
                </Typography>

                <Fade in={stillRunning}>
                    <Box sx={{ mt: 2 }}>
                        <Typography variant="body2" color="text.secondary">
                            Still running — first analyses can take up to a
                            minute or two depending on your AI provider and
                            log volume. You can dismiss this wizard and
                            we'll notify you when it's ready.
                        </Typography>
                    </Box>
                </Fade>

                {offerCheck && (
                    <Box sx={{ mt: 3 }}>
                        <Typography variant="subtitle1" component="h3" fontWeight={600} gutterBottom>
                            {t('dataCheck.waitingTitle')}
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                            {t('dataCheck.waitingIntro')}
                        </Typography>
                        {lastRun?.reason && (
                            <Typography variant="body2" sx={{ mb: 2 }}>
                                {t(`dataCheck.reason.${lastRun.reason}`, { defaultValue: lastRun.detail })}
                            </Typography>
                        )}
                        {/* A link, not the panel: the floating wizard has to stay small
                            enough that its Minimize button stays on screen. */}
                        <Button variant="contained" size="small" component={RouterLink}
                            to={`/dash/projects/${project.id}?tab=data`}>
                            {t('dataCheck.run')}
                        </Button>
                    </Box>
                )}
            </CardContent>
        </Card>
    );
}
