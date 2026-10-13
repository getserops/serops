/**
 * PostOnboardingUpsells — contextual "connect SCM / CI-CD" cards
 * surfaced on the BatchDetail view once the org has landed its
 * first analysis.
 *
 * Rationale (Sentry/Datadog pattern documented in the item-#11 plan):
 * SCM + CI/CD bindings are deferred out of the wizard's required path
 * to keep TTV under the 30-min abandonment cliff. But we still want
 * users to discover them — and the moment they're most receptive is
 * *after* they've seen their first AI-generated insight, when
 * "this could be more precise with commits" is a tangible claim
 * rather than an abstract feature.
 *
 * Render logic:
 *   - Fetch the org's SCM + CI/CD binding lists (both endpoints are
 *     org-scoped by the backend queryset).
 *   - If either list is empty, render a card pointing at
 *     Settings → Integrations to add one.
 *   - Renders nothing while loading or if the user already has both.
 *
 * We intentionally scope by ORG (not the specific batch's project)
 * because a batch view doesn't cleanly expose project_id without
 * an extra fetch, and the org-level check is a strict-enough proxy
 * for "this user hasn't set up SCM anywhere yet" which is the
 * relevant nudge state. If they've set it up on any project, we
 * assume they know the feature exists and don't nag.
 */

import React, { useEffect, useState } from 'react';
import { Alert, Box, Button, Stack } from '@mui/material';
import { FaCodeBranch, FaCog } from 'react-icons/fa';

import apiClient from '../../services/api-client';

export default function PostOnboardingUpsells() {
    const [state, setState] = useState({
        loading: true,
        hasSCM: true,   // Default to true so we don't flash the upsell
        hasCICD: true,  // while loading.
    });

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [scmRes, cicdRes] = await Promise.all([
                    apiClient.get('/projects/scm-bindings/'),
                    apiClient.get('/projects/cicd-bindings/'),
                ]);
                if (cancelled) return;
                const scmData = Array.isArray(scmRes.data) ? scmRes.data : (scmRes.data?.results || []);
                const cicdData = Array.isArray(cicdRes.data) ? cicdRes.data : (cicdRes.data?.results || []);
                setState({
                    loading: false,
                    hasSCM: scmData.length > 0,
                    hasCICD: cicdData.length > 0,
                });
            } catch {
                // Silent failure — an upsell is a UX polish, not a
                // hard requirement. If the API 5xx's or the user
                // lacks permission, just hide the card.
                if (!cancelled) {
                    setState({ loading: false, hasSCM: true, hasCICD: true });
                }
            }
        })();
        return () => { cancelled = true; };
    }, []);

    // Nothing to say: loading or fully set up.
    if (state.loading || (state.hasSCM && state.hasCICD)) return null;

    return (
        <Box sx={{ mb: 2 }}>
            <Stack spacing={1}>
                {!state.hasSCM && (
                    <Alert
                        severity="info"
                        icon={<FaCodeBranch />}
                        action={
                            <Button
                                color="inherit"
                                size="small"
                                href="/dash/settings/integrations"
                                sx={{ fontWeight: 600 }}
                            >
                                Connect
                            </Button>
                        }
                    >
                        Add a source-control integration to correlate this
                        analysis with recent commits and diffs.
                    </Alert>
                )}
                {!state.hasCICD && (
                    <Alert
                        severity="info"
                        icon={<FaCog />}
                        action={
                            <Button
                                color="inherit"
                                size="small"
                                href="/dash/settings/integrations"
                                sx={{ fontWeight: 600 }}
                            >
                                Connect
                            </Button>
                        }
                    >
                        Add a CI/CD integration so AI can spot when incidents
                        line up with recent builds or deploys.
                    </Alert>
                )}
            </Stack>
        </Box>
    );
}
