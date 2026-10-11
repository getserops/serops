import React from 'react';

/**
 * Error boundary — one crash contained per region rather than blanking
 * the whole app.
 *
 * Wrap around routed sections, not around individual widgets: a widget-
 * level boundary hides the crash and makes debugging harder. The point
 * here is to keep the shell (nav, sidebar) alive so the user can
 * navigate away from the broken page and admins can still reach
 * Settings / Audit Log to diagnose.
 *
 * Design decisions:
 * - No error-reporting network call. If you wire an APM later, do it
 *   in componentDidCatch. Silent-swallow is deliberate for OSS.
 * - Reset button re-mounts the child tree by bumping ``resetKey``.
 *   Keeps the boundary itself alive so a repeated crash doesn't
 *   spiral.
 * - Uses inline styles to survive a CSS-module load failure — the
 *   whole point is being resilient when *anything* below breaks.
 */
class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null, resetKey: 0 };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        // eslint-disable-next-line no-console
        console.error('[ErrorBoundary]', error, info?.componentStack);
    }

    handleReset = () => {
        this.setState((prev) => ({
            hasError: false,
            error: null,
            resetKey: prev.resetKey + 1,
        }));
    };

    render() {
        if (this.state.hasError) {
            const { error } = this.state;
            const message = error?.message || 'An unexpected error occurred.';
            return (
                <div
                    role="alert"
                    aria-live="assertive"
                    style={{
                        padding: '2rem',
                        margin: '1rem',
                        border: '1px solid #f5c2c7',
                        borderRadius: '0.5rem',
                        background: '#f8d7da',
                        color: '#842029',
                        fontFamily: 'system-ui, -apple-system, sans-serif',
                    }}
                >
                    <h2 style={{ marginTop: 0, fontSize: '1.25rem' }}>
                        Something went wrong on this page
                    </h2>
                    <p style={{ marginBottom: '0.5rem' }}>{message}</p>
                    <p style={{ fontSize: '0.875rem', opacity: 0.85 }}>
                        Other pages in SerOps are still working — use the sidebar to
                        navigate away, or click Retry to reload just this section.
                    </p>
                    <button
                        type="button"
                        onClick={this.handleReset}
                        style={{
                            marginTop: '0.5rem',
                            padding: '0.5rem 1rem',
                            border: '1px solid #842029',
                            borderRadius: '0.25rem',
                            background: 'white',
                            color: '#842029',
                            cursor: 'pointer',
                            fontWeight: 500,
                        }}
                    >
                        Retry
                    </button>
                </div>
            );
        }

        return (
            <React.Fragment key={this.state.resetKey}>
                {this.props.children}
            </React.Fragment>
        );
    }
}

export default ErrorBoundary;
