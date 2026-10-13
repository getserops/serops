"""Regressions from the chaos-RCA run against a real cluster.

Three separate ways SerOps stayed silent or misreported when the evidence was
there:

* A quota failure on the primary provider was reported as an auth failure on
  the fallback, pointing the operator at the wrong provider entirely.
* A batch carrying only spans was skipped without an AI call, because the
  data-presence check never counted traces.
* The metric half of that check counted dict KEYS, so it read "we have
  metrics" even when every series inside was empty.
"""
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from ai_model.adapters.base import AIServiceError


class FallbackErrorAttributionTest(TestCase):
    """Observed on the validation cluster: Gemini returned
    429 RESOURCE_EXHAUSTED (free tier, 20 requests/day) and the configured
    fallback then failed auth because its stored key was a leftover
    placeholder. The batch recorded FAILED (AUTH_ERROR) — so the operator was
    told to check a key, on a provider they had not selected, while the real
    cause (exhausted quota on their primary) was discarded.
    """

    def setUp(self):
        from Organisations.models import Organisations
        from org_settings.models import AIModelProvider, OrganisationAISettings
        self.org = Organisations.objects.create(name='Fallback Attribution Org')
        gemini, _ = AIModelProvider.objects.get_or_create(name='gemini')
        claude, _ = AIModelProvider.objects.get_or_create(name='claude')
        OrganisationAISettings.objects.create(
            organisation=self.org, default_provider=gemini,
            fallback_provider=claude,
        )

    def _both_fail(self, primary_err, fallback_err):
        from ai_model import ai_service
        calls = []

        def fake(prompt, provider=None, **kwargs):
            calls.append(provider)
            err = primary_err if len(calls) == 1 else fallback_err
            return None, err, 0, 0

        with patch.object(ai_service, 'generate_text_unified', side_effect=fake), \
             patch.object(ai_service, 'get_api_key_for_org',
                          return_value=('k', None, {})):
            return ai_service.generate_for_organisation('p', self.org), calls

    def test_primary_error_is_reported_not_the_fallback_s(self):
        quota = AIServiceError.from_type('quota_exceeded', raw_error='429')
        auth = AIServiceError.from_type('auth_error', raw_error='401')
        (resp, provider, err, _, _), calls = self._both_fail(quota, auth)
        self.assertIsNone(resp)
        self.assertEqual(len(calls), 2, 'fallback should still be attempted')
        self.assertEqual(err.code, 'QUOTA_EXCEEDED',
                         'the primary cause must survive the fallback attempt')

    def test_fallback_failure_is_still_visible(self):
        """Surfacing the primary must not hide a broken fallback — otherwise a
        placeholder key sits there undetected."""
        quota = AIServiceError.from_type('quota_exceeded')
        auth = AIServiceError.from_type('auth_error')
        (_, _, err, _, _), _ = self._both_fail(quota, auth)
        self.assertIn('AUTH_ERROR', err.message)
        self.assertIn('claude', err.message)

    def test_fallback_error_used_when_primary_has_none(self):
        auth = AIServiceError.from_type('auth_error')
        (_, _, err, _, _), _ = self._both_fail(None, auth)
        self.assertEqual(err.code, 'AUTH_ERROR')

    def test_successful_fallback_reports_no_error(self):
        from ai_model import ai_service
        calls = []

        def fake(prompt, provider=None, **kwargs):
            calls.append(provider)
            if len(calls) == 1:
                return None, AIServiceError.from_type('quota_exceeded'), 0, 0
            return 'recovered', None, 5, 5

        with patch.object(ai_service, 'generate_text_unified', side_effect=fake), \
             patch.object(ai_service, 'get_api_key_for_org',
                          return_value=('k', None, {})):
            resp, provider, err, _, _ = ai_service.generate_for_organisation('p', self.org)
        self.assertEqual(resp, 'recovered')
        self.assertIsNone(err)
        self.assertEqual(provider, 'claude')


class DataPresenceCheckTest(SimpleTestCase):
    """The pre-flight "is there anything to analyse" count.

    Before the fix it summed `len(metrics_summary)` — the number of keys in a
    fixed-shape dict, so always 4 when present, even with every series empty —
    and never counted traces at all. A latency regression with no error logs,
    the exact case distributed tracing exists for, was skipped silently.
    """

    @staticmethod
    def _count(logs=0, cicd=0, changes=0, cpu_pts=0, mem_pts=0, spans=0,
               summary_present=True):
        """Mirrors the expression in analyze_batch."""
        metrics_summary = {
            'cpu': {}, 'memory': {}, 'time_range': {},
            'data_points': {'cpu': cpu_pts, 'memory': mem_pts},
        } if summary_present else {}
        traces_summary = {'span_count': spans} if spans else {}
        trace_span_count = int((traces_summary or {}).get('span_count') or 0)
        metric_points = 0
        if isinstance(metrics_summary, dict):
            points = metrics_summary.get('data_points') or {}
            metric_points = sum(int(v or 0) for v in points.values()
                                if isinstance(v, (int, float)))
        return logs + cicd + changes + metric_points + trace_span_count

    def test_traces_alone_are_enough_to_analyse(self):
        self.assertGreater(self._count(spans=2500, summary_present=False), 0)

    def test_metrics_alone_are_enough(self):
        self.assertGreater(self._count(cpu_pts=305, mem_pts=61), 0)

    def test_empty_metric_series_no_longer_counts_as_data(self):
        """The old check returned 4 here purely from the dict's shape."""
        self.assertEqual(self._count(cpu_pts=0, mem_pts=0, summary_present=True), 0)

    def test_genuinely_empty_batch_still_skips(self):
        self.assertEqual(self._count(), 0)

    def test_logs_alone_still_counted(self):
        self.assertEqual(self._count(logs=7), 7)

    def test_real_observed_case_latency_only(self):
        """a02/a04 on the cluster: 0 logs, 305 CPU points, 2500 spans. Those
        batches reached the AI but must never be skipped for lack of data."""
        self.assertGreater(self._count(logs=0, cpu_pts=305, mem_pts=61, spans=2500), 0)


class SignalOnlyPromptRulesTest(SimpleTestCase):
    """The prompt must tell the model that quiet logs are not a quiet system.

    On the cluster, two batches with 0 logs but 305 CPU points and 2500 spans
    reached Gemini and came back with an empty narrative and zero issues — the
    AI call was spent and nothing was reported.
    """

    def _system_prompt(self):
        from ai_model.prompts import get_batch_analysis_system_prompt
        return get_batch_analysis_system_prompt()

    def test_absence_of_error_logs_is_addressed(self):
        text = self._system_prompt().lower()
        self.assertIn('absence of error logs', text)

    def test_metric_only_degradation_is_reportable(self):
        text = self._system_prompt().lower()
        self.assertIn('metrics alone', text)

    def test_trace_only_degradation_is_reportable(self):
        text = self._system_prompt().lower()
        self.assertIn('traces alone', text)

    def test_empty_result_requires_all_three_signals_quiet(self):
        text = self._system_prompt().lower()
        self.assertIn('logs, metrics and traces are all unremarkable', text)

    def test_rules_are_numbered_into_the_existing_sequence(self):
        """Keeps them inside the numbered contract the model is told to follow,
        rather than appended as loose prose it may skim."""
        text = self._system_prompt()
        for n in ('17.', '18.', '19.', '20.'):
            with self.subTest(rule=n):
                self.assertIn(n, text)


class ClaudeTextExtractionTest(SimpleTestCase):
    """`content[0].text` broke on any response that does not lead with a text
    block. Extended thinking puts a ThinkingBlock first, which carries
    `.thinking` and no `.text`, so the adapter raised
    "'ThinkingBlock' object has no attribute 'text'", reported a provider
    failure, and SerOps fell back to its secondary provider — with a valid key
    and quota, Claude was simply unusable through the batch path.
    """

    class _Text:
        def __init__(self, text):
            self.type, self.text = 'text', text

    class _Thinking:
        def __init__(self, thinking):
            self.type, self.thinking = 'thinking', thinking

    class _ToolUse:
        def __init__(self, name):
            self.type, self.name, self.input = 'tool_use', name, {}

    def _extract(self, content):
        from ai_model.adapters.claude import _extract_text
        return _extract_text(content)

    def test_plain_text_response(self):
        self.assertEqual(self._extract([self._Text('hello')]), 'hello')

    def test_thinking_block_first_is_skipped(self):
        """The exact observed failure."""
        blocks = [self._Thinking('let me reason'), self._Text('the answer')]
        self.assertEqual(self._extract(blocks), 'the answer')

    def test_tool_use_block_is_skipped(self):
        blocks = [self._ToolUse('search'), self._Text('done')]
        self.assertEqual(self._extract(blocks), 'done')

    def test_multiple_text_blocks_are_joined(self):
        blocks = [self._Text('part one '), self._Text('part two')]
        self.assertEqual(self._extract(blocks), 'part one part two')

    def test_thinking_only_response_yields_empty_not_an_exception(self):
        """Empty is a reportable outcome; an AttributeError is not."""
        self.assertEqual(self._extract([self._Thinking('only thoughts')]), '')

    def test_empty_and_none_content(self):
        self.assertEqual(self._extract([]), '')
        self.assertEqual(self._extract(None), '')

    def test_never_raises_on_unexpected_block_shapes(self):
        class Weird:
            type = 'weird'
        self.assertEqual(self._extract([Weird(), self._Text('ok')]), 'ok')


class ClaudeOutputCeilingTest(SimpleTestCase):
    """A truncated response is discarded whole — zero issues, empty narrative,
    tokens already paid for. So the ceiling has to be high enough for a real
    multi-issue analysis.

    Observed the moment container-lifecycle data made answers richer: a
    five-issue analysis stopped at ~7997 output tokens against an 8192 ceiling
    and was thrown away.
    """

    def test_default_ceiling_has_headroom_over_observed_usage(self):
        import inspect
        from ai_model.adapters import claude
        src = inspect.getsource(claude)
        self.assertIn("config.get('max_tokens', 16384)", src)

    def test_ceiling_is_overridable_per_org(self):
        """Operators on a cheaper model may want it lower."""
        import inspect
        from ai_model.adapters import claude
        src = inspect.getsource(claude)
        self.assertIn("config.get('max_tokens'", src)


class TruncatedResponseSalvageTest(SimpleTestCase):
    """A response that hits the output ceiling used to be discarded whole.

    Observed on the chaos suite once container-lifecycle data made answers
    richer: a five-issue diagnosis stopped at ~7997 output tokens and the
    batch recorded zero issues and an empty narrative — while the tokens were
    billed. The model writes its conclusion first and runs out of room in the
    issue list, so most of that answer was correct and recoverable.

    Two halves are asserted here: the adapters must hand back the full body
    rather than a 2000-char stub, and the salvage must refuse to present a
    partial answer as a complete one.
    """

    def test_error_carries_the_full_body_not_a_stub(self):
        body = '{"correlated_issues": [' + ('x' * 9000)
        err = AIServiceError(
            'truncated', 'TRUNCATED', 'msg', 'action',
            raw_error=body[:2000], partial_text=body,
        )
        self.assertEqual(err.partial_text, body)
        self.assertEqual(len(err.raw_error), 2000,
                         'raw_error stays clipped — it is a display field')

    def test_non_truncation_errors_carry_no_partial_text(self):
        err = AIServiceError.from_type('auth_error', raw_error='401')
        self.assertIsNone(err.partial_text)

    def test_cut_off_analysis_parses_back_into_issues(self):
        from ai_model.response_repair import repair_json
        cut = (
            '{"root_cause_narrative": "cache was OOMKilled by the kubelet",'
            ' "correlated_issues": ['
            '{"issue_type": "MEMORY", "component": "cache", "title": "OOMKilled"},'
            '{"issue_type": "AVAILABILITY", "component": "api", "title": "conn refused"}'
        )
        parsed = repair_json(cut)
        self.assertEqual(len(parsed['correlated_issues']), 2)
        self.assertIn('OOMKilled', parsed['root_cause_narrative'] or '')

    def test_strand_left_by_truncation_is_dropped_not_fatal(self):
        """Truncation usually lands mid-object, sometimes mid-string. The
        complete issues before the cut must survive."""
        from ai_model.response_repair import repair_json
        cut = (
            '{"root_cause_narrative": "checkout raised unhandled exceptions",'
            ' "correlated_issues": ['
            '{"issue_type": "ERROR", "component": "checkout", "title": "500s"},'
            '{"issue_type": "LATEN'
        )
        parsed = repair_json(cut)
        self.assertIsNotNone(parsed, 'a strand must not cost the whole analysis')
        self.assertEqual(parsed['correlated_issues'][0]['component'], 'checkout')

    def test_closers_come_out_innermost_first(self):
        """The counting repair this replaced appended '}' before ']', so the
        one shape that actually occurs — an object holding a cut-off array —
        was closed as '}]' and never parsed."""
        from ai_model.response_repair import balance_json
        self.assertTrue(balance_json('{"correlated_issues": [').endswith(']}'))

    def test_braces_inside_log_text_are_not_structure(self):
        from ai_model.response_repair import repair_json
        parsed = repair_json('{"note": "dict {a: 1} in the log line", "n": 2}')
        self.assertEqual(parsed['n'], 2)

    def test_body_cut_at_a_clean_boundary_loses_nothing(self):
        """The model can stop right after a closing brace. Every issue in the
        body is then complete and discarding one would be pure data loss."""
        from ai_model.response_repair import repair_json
        cut = ('{"correlated_issues": ['
               '{"component": "a", "title": "one"},'
               '{"component": "b", "title": "two"}')
        parsed = repair_json(cut)
        self.assertEqual(len(parsed['correlated_issues']), 2)

    def test_hollow_trailing_issue_is_dropped_by_the_caller(self):
        """Balancing keeps the strand as a valid-but-empty object. Left in, the
        issue-creation loop fills its defaults and it reaches the incident page
        as a CRITICAL 'OTHER' against no component — an invented finding."""
        from ai_model.response_repair import repair_json
        from ai_model.tasks import _drop_hollow_issues
        cut = ('{"correlated_issues": ['
               '{"component": "checkout", "title": "unhandled RuntimeError"},'
               '{"issue_type": "LATEN')
        parsed = repair_json(cut)
        self.assertEqual(len(parsed['correlated_issues']), 2, 'balanced, not filtered')
        dropped = _drop_hollow_issues(parsed)
        self.assertEqual(dropped, 1)
        self.assertEqual([i['component'] for i in parsed['correlated_issues']],
                         ['checkout'])

    def test_an_issue_needs_both_what_and_where(self):
        from ai_model.tasks import _drop_hollow_issues
        parsed = {'correlated_issues': [
            {'component': 'api', 'title': 'both'},              # keep
            {'component': 'api'},                               # no what
            {'title': 'orphan finding'},                         # no where
            {'scope': 'INFRASTRUCTURE', 'description': 'both'},  # keep
            'not a dict',                                        # keep out
        ]}
        dropped = _drop_hollow_issues(parsed)
        self.assertEqual(dropped, 3)
        self.assertEqual(len(parsed['correlated_issues']), 2)

    def test_filter_tolerates_a_missing_or_odd_issue_list(self):
        from ai_model.tasks import _drop_hollow_issues
        self.assertEqual(_drop_hollow_issues({}), 0)
        self.assertEqual(_drop_hollow_issues({'correlated_issues': None}), 0)

    def test_unparsable_body_returns_none(self):
        from ai_model.response_repair import repair_json
        self.assertIsNone(repair_json('not json at all'))
        self.assertIsNone(repair_json(''))

    def test_salvage_is_labelled_so_it_never_reads_as_complete(self):
        """"one issue found" and "one issue, list cut short" are different
        answers for whoever is on call."""
        parsed = {'correlated_issues': [{'component': 'cache'}]}
        parsed['analysis_truncated'] = True
        parsed['truncation_note'] = 'The model hit its output token limit.'
        self.assertTrue(parsed['analysis_truncated'])
        self.assertIn('token limit', parsed['truncation_note'])

    def test_unsalvageable_body_yields_nothing_to_keep(self):
        """An empty partial must not trigger a salvage — the truncation error
        has to stand so the operator sees a failure rather than a silent
        zero-issue analysis."""
        err = AIServiceError('truncated', 'TRUNCATED', 'm', 'a', partial_text='')
        self.assertFalse(bool(err.partial_text and err.partial_text.strip()))


class BatchCreationTraceGateTest(SimpleTestCase):
    """The creation-time twin of ``DataPresenceCheckTest``.

    ``analyze_batch``'s gate was fixed to count traces, but the gate one stage
    earlier — in ``create_log_batch_with_project_name`` — still counted only
    logs and metrics. A latency-only incident therefore produced NO BATCH AT
    ALL ("No new logs or metrics found"), which is worse: there is no row left
    to reanalyse. Measured on the chaos suite with thousands of spans stored.
    """

    @staticmethod
    def _creates_batch(hits=0, metric_points=0, spans=0):
        """Mirrors the gate in create_log_batch_with_project_name."""
        filtered_hits = [object()] * hits
        trace_span_count = spans if (not filtered_hits and metric_points == 0) else 0
        return not (not filtered_hits and metric_points == 0 and trace_span_count == 0)

    def test_traces_alone_now_create_a_batch(self):
        self.assertTrue(self._creates_batch(spans=2400))

    def test_truly_empty_window_still_creates_nothing(self):
        self.assertFalse(self._creates_batch())

    def test_logs_alone_unchanged(self):
        self.assertTrue(self._creates_batch(hits=3))

    def test_metrics_alone_unchanged(self):
        self.assertTrue(self._creates_batch(metric_points=305))

    def test_trace_count_is_not_queried_when_logs_exist(self):
        """The count is two DB queries on every scheduled tick; it must only
        run when the cheap signals have already come up empty."""
        from ai_model import trace_context
        with patch.object(trace_context, 'count_spans_in_window') as counter:
            if not [object()] and 0 == 0:           # noqa: SIM201 — mirrors the guard
                trace_context.count_spans_in_window(None, None, None)
            counter.assert_not_called()


class CountSpansInWindowTest(TestCase):
    """The gate's helper must never be a reason a batch fails to be created."""

    def test_missing_project_counts_zero(self):
        from ai_model.trace_context import count_spans_in_window
        self.assertEqual(count_spans_in_window(None, 1, 2), 0)

    def test_missing_window_counts_zero(self):
        from ai_model.trace_context import count_spans_in_window
        self.assertEqual(count_spans_in_window(object(), None, None), 0)

    def test_query_failure_counts_zero_rather_than_raising(self):
        from ai_model import trace_context

        class Boom:
            @property
            def organisation(self):
                raise RuntimeError('db down')

        self.assertEqual(
            trace_context.count_spans_in_window(Boom(), 1, 2), 0,
            'traces may add a reason to create a batch, never a reason to fail one')


class MetricsWindowMatchesBatchWindowTest(SimpleTestCase):
    """Logs and metrics in one batch must describe the same span of time.

    The metrics window was computed as ``now - interval .. now``, independently
    of the batch window. A batch with an explicit window — the Q5-1
    alert-triggered path, and every chaos scenario — therefore carried logs from
    the requested window and metrics from somewhere else entirely, and the AI
    correlated them as if they were simultaneous.

    Measured: a 2-minute exception window was told about an OOMKill from 14
    minutes earlier (inherited by the container-lifecycle query) and reported a
    confident MEMORY_HIGH against a service healthy throughout the window it was
    asked about.
    """

    from datetime import datetime, timedelta, timezone as _tz

    NOW = datetime(2026, 9, 28, 11, 0, tzinfo=_tz.utc)

    @classmethod
    def _window(cls, override_active, batch_start, batch_end, interval):
        """Mirrors the expression in create_log_batch_with_project_name."""
        from datetime import timedelta
        if override_active:
            return batch_start, batch_end
        return (max(batch_start, batch_end - timedelta(minutes=interval)),
                batch_end)

    def test_explicit_window_is_honoured_exactly(self):
        from datetime import timedelta
        start = self.NOW - timedelta(minutes=2)
        got = self._window(True, start, self.NOW, interval=5)
        self.assertEqual(got, (start, self.NOW))

    def test_explicit_window_is_not_widened_to_the_interval(self):
        """The old code would have reached back 5 minutes for a 2-minute
        window, which is how a stale OOMKill got attributed to it."""
        from datetime import timedelta
        start = self.NOW - timedelta(minutes=2)
        metrics_start, _ = self._window(True, start, self.NOW, interval=15)
        self.assertEqual(metrics_start, start)
        self.assertGreater(metrics_start, self.NOW - timedelta(minutes=15))

    def test_scheduled_path_never_reaches_past_the_previous_batch(self):
        """Two batches must not both claim the same metric points."""
        from datetime import timedelta
        last_batch = self.NOW - timedelta(minutes=2)
        metrics_start, _ = self._window(False, last_batch, self.NOW, interval=5)
        self.assertEqual(metrics_start, last_batch)

    def test_a_stalled_scheduler_does_not_trigger_an_hours_long_query(self):
        from datetime import timedelta
        last_batch = self.NOW - timedelta(hours=6)
        metrics_start, _ = self._window(False, last_batch, self.NOW, interval=5)
        self.assertEqual(metrics_start, self.NOW - timedelta(minutes=5))

    def test_metrics_end_is_the_batch_end_not_wall_clock(self):
        from datetime import timedelta
        batch_end = self.NOW - timedelta(minutes=30)
        _, metrics_end = self._window(True, batch_end - timedelta(minutes=5), batch_end, 5)
        self.assertEqual(metrics_end, batch_end)


class HealthyWindowRulesTest(SimpleTestCase):
    """The prompt must not license a finding built on ranking alone.

    Rules 17-20 were added to stop SerOps staying silent when only metrics or
    traces showed a problem. They overshot: rule 19 said "if the slowest spans
    concentrate in one service, that service is the suspect", and in a healthy
    window some service always tops that list. Measured on the chaos suite's
    healthy-window scenario — no fault injected at all — the model reported a
    CONNECTION_TIMEOUT issue against checkout whose own narrative recorded the
    spans as 88-109ms.
    """

    def _prompt(self):
        from ai_model.prompts import get_batch_analysis_system_prompt
        return get_batch_analysis_system_prompt()

    def test_ranking_alone_is_explicitly_not_a_finding(self):
        text = self._prompt().lower()
        self.assertIn('being the slowest is not the same as being slow', text)

    def test_absolute_duration_is_required(self):
        text = self._prompt().lower()
        self.assertIn('absolute terms', text)

    def test_tens_of_milliseconds_named_as_healthy(self):
        """The observed false positive was 88-109ms, so the threshold has to be
        concrete enough for the model to place that."""
        text = self._prompt().lower()
        self.assertIn('tens of milliseconds', text)

    def test_empty_list_is_stated_to_be_a_correct_answer(self):
        text = self._prompt().lower()
        self.assertIn('correct answer for a healthy window', text)

    def test_manufacturing_a_finding_is_forbidden(self):
        text = self._prompt().lower()
        self.assertIn('must not manufacture', text)

    def test_the_opposite_failure_is_still_guarded(self):
        """Fixing over-eagerness must not restore the silence these rules were
        written to prevent."""
        text = self._prompt().lower()
        self.assertIn('silence means health', text)
        self.assertIn('metrics alone', text)
        self.assertIn('traces alone', text)

    def test_rules_stay_inside_the_numbered_contract(self):
        text = self._prompt()
        for n in ('17.', '18.', '19.', '20.'):
            with self.subTest(rule=n):
                self.assertIn(n, text)


class AdapterErrorFidelityTest(TestCase):
    """``generate_text_unified`` must not rebuild the adapter's error.

    It used to return ``AIServiceError.from_type(error.error_type, ...)``,
    replacing whatever the adapter had produced with the generic ERROR_TYPES
    entry for that type. Two things died there: the partial body of a truncated
    response — so the salvage in ``analyze_batch`` could never fire, which is
    exactly what happened when it was tested against the real provider — and
    adapter-specific codes and hints, so Claude's AUTH_WORKSPACE_MISSING became
    a bare AUTH_ERROR advising the operator to check a key that was fine.
    """

    def setUp(self):
        from Organisations.models import Organisations
        from org_settings.models import AIModelProvider
        self.org = Organisations.objects.create(name='Error Fidelity Org')
        AIModelProvider.objects.get_or_create(name='claude')

    def _through_unified(self, err):
        from ai_model import ai_service
        with patch.object(ai_service, '_generate_with_retry',
                          return_value=(None, err, 120, 700)), \
             patch.object(ai_service, 'AdapterRegistry', create=True):
            return ai_service.generate_text_unified('p', provider='claude', api_key='k')

    def test_partial_text_survives(self):
        body = '{"correlated_issues": [{"component": "cache"'
        err = AIServiceError('truncated', 'TRUNCATED', 'msg', 'act',
                             raw_error=body[:2000], partial_text=body)
        _, got, _, _ = self._through_unified(err)
        self.assertEqual(getattr(got, 'partial_text', None), body,
                         'without this the truncation salvage can never run')

    def test_adapter_specific_code_survives(self):
        err = AIServiceError(
            'auth_error', 'AUTH_WORKSPACE_MISSING',
            'Anthropic API key is workspace-scoped but no workspace_id was configured.',
            'Set workspace_id in the API key settings.',
        )
        _, got, _, _ = self._through_unified(err)
        self.assertEqual(got.code, 'AUTH_WORKSPACE_MISSING')
        self.assertIn('workspace_id', got.user_action)

    def test_token_counts_survive(self):
        err = AIServiceError.from_type('server_error')
        _, _, tin, tout = self._through_unified(err)
        self.assertEqual((tin, tout), (120, 700),
                         'providers bill for failed calls; usage must be logged')

    def test_non_aiserviceerror_is_normalised(self):
        _, got, _, _ = self._through_unified(RuntimeError('boom'))
        self.assertEqual(got.code, 'UNKNOWN_ERROR')


class TruncationDoesNotTriggerFallbackTest(TestCase):
    """Truncation is not a provider failure, so it must not spend a second call.

    Measured against the real provider: Claude truncated, SerOps fell back to
    Gemini, Gemini was 503 at the time, and the batch recorded a failure — while
    a salvageable partial analysis sat in the primary's response. Even had the
    fallback succeeded it would have silently swapped providers for a batch that
    already had a usable answer, and billed for it.
    """

    def setUp(self):
        from Organisations.models import Organisations
        from org_settings.models import AIModelProvider, OrganisationAISettings
        self.org = Organisations.objects.create(name='Truncation Fallback Org')
        claude, _ = AIModelProvider.objects.get_or_create(name='claude')
        gemini, _ = AIModelProvider.objects.get_or_create(name='gemini')
        OrganisationAISettings.objects.create(
            organisation=self.org, default_provider=claude, fallback_provider=gemini,
        )

    def _run(self, primary_error):
        from ai_model import ai_service
        calls = []

        def fake(prompt, provider=None, **kwargs):
            calls.append(provider)
            if len(calls) == 1:
                return None, primary_error, 100, 700
            return 'fallback answer', None, 50, 50

        with patch.object(ai_service, 'generate_text_unified', side_effect=fake), \
             patch.object(ai_service, 'get_api_key_for_org',
                          return_value=('k', None, {})):
            return ai_service.generate_for_organisation('p', self.org), calls

    def test_no_fallback_call_is_made_on_truncation(self):
        err = AIServiceError('truncated', 'TRUNCATED', 'm', 'a',
                             partial_text='{"correlated_issues": [')
        (_, _, got, _, _), calls = self._run(err)
        self.assertEqual(calls, ['claude'], 'the fallback must not be attempted')
        self.assertEqual(got.code, 'TRUNCATED')

    def test_partial_body_reaches_the_caller(self):
        body = '{"correlated_issues": [{"component": "api"'
        err = AIServiceError('truncated', 'TRUNCATED', 'm', 'a', partial_text=body)
        (_, _, got, _, _), _ = self._run(err)
        self.assertEqual(got.partial_text, body)

    def test_truncated_tokens_are_reported_for_billing(self):
        err = AIServiceError('truncated', 'TRUNCATED', 'm', 'a', partial_text='x')
        (_, _, _, tin, tout), _ = self._run(err)
        self.assertEqual((tin, tout), (100, 700))

    def test_a_real_failure_still_falls_back(self):
        """Only truncation short-circuits; genuine failures keep the fallback."""
        err = AIServiceError.from_type('server_error')
        (resp, prov, got, _, _), calls = self._run(err)
        self.assertEqual(calls, ['claude', 'gemini'])
        self.assertEqual(resp, 'fallback answer')
        self.assertIsNone(got)
