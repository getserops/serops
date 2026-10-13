"""A deliberately fragile three-tier service, for chaos-RCA scoring.

One image, three roles (``checkout`` -> ``api`` -> ``cache``) plus a load
generator, selected by ``SVC_ROLE``. Faults are toggled at runtime over HTTP
so a scenario can start a failure mid-flight without a redeploy — which is
what real incidents look like, and what makes the metric and trace signals
show a *change* rather than a constant.

Why this exists at all: the previous demo workload was a busybox loop
echoing a hardcoded line that named its own root cause ("PaymentGatewayTimeout
upstream=stripe"). An AI reading that is doing string extraction, not
diagnosis. Here the logs describe *symptoms* — a timeout, a 503, a slow
call — and the cause has to be inferred from which service degraded, what
its metrics did, and where the trace spent its time.

Emits all three signals the RCA pipeline consumes:
  * logs   — stdout, `<iso> LEVEL <service> <message> k=v`, parsed by the
             shippers into SerOps' canonical fields
  * traces — OTLP spans to the collector, one server span per request plus a
             client span per downstream hop
  * metrics — via cAdvisor, by actually consuming CPU/memory
"""
import json
import logging
import os
import random
import socket
import sys
import threading
import time

import requests
from flask import Flask, jsonify, request

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

ROLE = os.getenv('SVC_ROLE', 'checkout')
DOWNSTREAM = os.getenv('DOWNSTREAM_URL', '').strip()
PORT = int(os.getenv('PORT', '8080'))
OTLP = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', '').strip()

# ---------------------------------------------------------------------------
# Logging — plain text with the level as the second field. The shippers parse
# severity out of the line (it is not a pod label), so the format has to put
# it in the prefix where their 200-char scan will find it.
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stdout, level=logging.INFO,
    format=f'%(asctime)s.%(msecs)03dZ %(levelname)s {ROLE} %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
log = logging.getLogger(ROLE)

# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------
if OTLP:
    provider = TracerProvider(resource=Resource.create({'service.name': ROLE}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f'{OTLP}/v1/traces'))
    )
    trace.set_tracer_provider(provider)
tracer = trace.get_tracer(ROLE)

app = Flask(__name__)
# Flask's per-request access log would drown the signal we care about.
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Fault state
# ---------------------------------------------------------------------------
FAULTS = {}
_ballast = []            # holds leaked memory
_lock = threading.Lock()
# Bounded worker slots, so pool exhaustion is a real queue wait rather than
# a printed message.
_slots = threading.Semaphore(int(os.getenv('POOL_SIZE', '8')))


def fault(name, default=None):
    return FAULTS.get(name, default)


@app.post('/fault')
def set_fault():
    body = request.get_json(force=True, silent=True) or {}
    with _lock:
        FAULTS.update(body)
    log.warning('fault configuration changed active=%s', json.dumps(FAULTS))
    return jsonify(FAULTS)


@app.post('/fault/clear')
def clear_fault():
    global _ballast
    with _lock:
        FAULTS.clear()
        _ballast = []
    log.info('fault configuration cleared')
    return jsonify({})


@app.get('/health')
def health():
    if fault('unhealthy'):
        return jsonify({'status': 'degraded'}), 503
    return jsonify({'status': 'ok', 'role': ROLE})


@app.get('/faults')
def get_faults():
    return jsonify(FAULTS)


# ---------------------------------------------------------------------------
# Fault primitives
# ---------------------------------------------------------------------------

def _burn_cpu(ms):
    """Occupy the CPU, so cAdvisor reports a real rate increase."""
    end = time.time() + ms / 1000.0
    x = 0
    while time.time() < end:
        x += sum(i * i for i in range(400))
    return x


def _leak(mb):
    """Grow RSS for real, so the container trips its memory limit."""
    with _lock:
        _ballast.append(bytearray(int(mb * 1024 * 1024)))


def _apply_pre_faults(span):
    """Faults that act before any downstream call."""
    if fault('cpu_ms'):
        span.set_attribute('chaos.cpu_ms', fault('cpu_ms'))
        _burn_cpu(int(fault('cpu_ms')))

    if fault('leak_mb'):
        _leak(float(fault('leak_mb')))
        total = sum(len(b) for b in _ballast) / 1048576
        # No mention of "leak" — a real service does not narrate its own bug.
        log.warning('heap grew rss_mb=%.0f', total)

    if fault('latency_ms'):
        ms = int(fault('latency_ms'))
        span.set_attribute('chaos.latency_ms', ms)
        time.sleep(ms / 1000.0)

    if fault('refuse'):
        log.error('rejecting request reason=capacity')
        return jsonify({'error': 'service unavailable'}), 503

    if fault('exception'):
        log.error('unhandled failure during request processing op=%s', fault('exception'))
        raise RuntimeError(str(fault('exception')))
    return None


def _call_downstream(span):
    """One hop, as a child span, so latency is attributable in the trace."""
    timeout = float(fault('downstream_timeout_s', 3.0))
    with tracer.start_as_current_span(f'{ROLE} -> downstream') as child:
        child.set_attribute('http.url', DOWNSTREAM)
        # Propagate W3C traceparent. Without this each service starts its own
        # root trace, and a cascade looks like three unrelated incidents
        # instead of one — which is precisely the correlation the RCA is
        # supposed to make.
        headers = {}
        inject(headers)
        try:
            with _slots:
                resp = requests.get(f'{DOWNSTREAM}/work', timeout=timeout, headers=headers)
            child.set_attribute('http.status_code', resp.status_code)
            if resp.status_code >= 500:
                log.error('upstream dependency returned status=%s', resp.status_code)
                child.set_status(Status(StatusCode.ERROR))
                return None, resp.status_code
            return resp.json(), resp.status_code
        except requests.exceptions.Timeout:
            log.error('dependency call exceeded timeout after=%.0fms', timeout * 1000)
            child.set_status(Status(StatusCode.ERROR, 'timeout'))
            return None, 504
        except requests.exceptions.ConnectionError as exc:
            reason = 'name resolution' if isinstance(
                getattr(exc, 'args', [None])[0], socket.gaierror) else 'connection refused'
            log.error('dependency unreachable reason=%s', reason)
            child.set_status(Status(StatusCode.ERROR, reason))
            return None, 503


@app.get('/work')
def work():
    # Continue the caller's trace when a traceparent is present.
    #
    # Keys MUST be lowercased. Flask preserves the wire casing, so
    # dict(request.headers) gives "Traceparent", while the W3C propagator
    # looks up "traceparent" with a plain case-sensitive dict get — it finds
    # nothing, silently starts a new root trace, and a cascade then appears
    # as N unrelated incidents.
    parent = extract({k.lower(): v for k, v in request.headers.items()})
    with tracer.start_as_current_span(f'{ROLE} /work', context=parent) as span:
        span.set_attribute('service.role', ROLE)

        early = _apply_pre_faults(span)
        if early is not None:
            span.set_status(Status(StatusCode.ERROR, 'refused'))
            return early

        payload = {'role': ROLE, 'ok': True}
        if DOWNSTREAM:
            data, code = _call_downstream(span)
            if data is None:
                span.set_status(Status(StatusCode.ERROR))
                return jsonify({'error': 'dependency failure', 'upstream': code}), 503
            payload['downstream'] = data

        if random.random() < float(fault('error_rate', 0.0)):
            log.error('request failed validation stage=commit')
            span.set_status(Status(StatusCode.ERROR))
            return jsonify({'error': 'internal'}), 500

        log.info('request completed status=200')
        return jsonify(payload)


# ---------------------------------------------------------------------------
# Load generator role — keeps traffic flowing so metrics and traces have a
# baseline to deviate from. Without a baseline there is no anomaly to detect.
# ---------------------------------------------------------------------------

def loadgen():
    target = os.getenv('TARGET_URL', 'http://checkout:8080')
    rps = float(os.getenv('RPS', '2'))
    log.info('load generator starting target=%s rps=%.1f', target, rps)
    while True:
        started = time.time()
        try:
            r = requests.get(f'{target}/work', timeout=10)
            if r.status_code >= 500:
                log.error('synthetic client saw status=%s', r.status_code)
        except Exception as exc:
            log.error('synthetic client failed error=%s', type(exc).__name__)
        time.sleep(max(0.0, (1.0 / rps) - (time.time() - started)))


if __name__ == '__main__':
    if ROLE == 'loadgen':
        loadgen()
    else:
        log.info('service starting role=%s port=%s downstream=%s', ROLE, PORT, DOWNSTREAM or 'none')
        if fault('crash_on_boot'):
            log.error('startup failed dependency_check=false')
            sys.exit(1)
        from werkzeug.serving import make_server
        make_server('0.0.0.0', PORT, app, threaded=True).serve_forever()
