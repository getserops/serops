"""
Held-out incidents: written and committed before any model saw them, and
never used to change a prompt rule. A prompt change made because one of
these failed moves it to the tuned set (and says so in the commit).

The workloads emit symptoms the way real services do. A log line may name
its own error (an x509 message does), but never the change that caused it.
"""
from .dataset import UNRELATED_CSS, answer, commit, filler, log, stats

SET = 'held_out'


CONN_LEAK_DIFF = '\n'.join([
    '@@ -54,11 +54,15 @@ class StockService:',
    filler(3, 54),
    '     def reserve(self, sku, qty):',
    '-        with self.db.session() as s:',
    '-            row = s.get(Stock, sku, with_for_update=True)',
    '-            row.reserved += qty',
    '+        s = self.db.session()',
    '+        row = s.get(Stock, sku, with_for_update=True)',
    '+        if row.available < qty:',
    '+            raise OutOfStock(sku)  # session stays open',
    '+        row.reserved += qty',
    '+        s.commit()',
    '+        s.close()',
])

TIMEOUT_TWEAK_DIFF = '\n'.join([
    '@@ -3,4 +3,4 @@ http:',
    '   server:',
    '-    read_timeout: 30s',
    '+    read_timeout: 25s',
])


def h01_connection_leak():
    logs = [log(5 + k * 6, 'inventory-api', 'WARN', f'db pool: {n} of 40 connections checked out')
            for k, n in enumerate((14, 21, 27, 33, 38))]
    logs += [log(36 + k, 'inventory-api', 'ERROR',
                 'Traceback (most recent call last):\n  File "/app/inventory/views.py", line 88, in reserve_view\n'
                 '    StockService(db).reserve(sku, qty)\n  File "/app/inventory/stock.py", line 57, in reserve\n'
                 '    s = self.db.session()\nsqlalchemy.exc.TimeoutError: QueuePool limit of size 40 overflow 0 reached, '
                 'connection timed out, timeout 30.00') for k in range(6)]
    logs += [log(20 + k * 3, 'inventory-api', 'INFO', f'OutOfStock raised for sku=SKU-{400 + k}') for k in range(5)]
    return {
        'id': 'h01_connection_leak', 'set': SET, 'category': 'bad deploy',
        'name': 'Connection leak on an error path (pool size unchanged)',
        'data': {'logs': logs,
                 'code_changes': [commit('4b0e77d1', -90, 'mo', 'feat(stock): reject reservations above availability',
                                         [{'path': 'inventory/stock.py', 'diff': CONN_LEAK_DIFF}]),
                                  commit('9c1d2e3f', -20, 'ines', 'chore: lower read timeout',
                                         [{'path': 'config/http.yaml', 'diff': TIMEOUT_TWEAK_DIFF}])],
                 'metrics_summary': {'cpu': {'usage_percent': stats(24, 31, 25)}}},
        'answer': answer(['inventory-api'], cause=[['leak', 'not closed', 'never closed', 'stays open', 'left open',
                                                    'not released', 'never released', 'not returned', 'close']],
                         blame_sha='4b0e77d1', wrong_shas=['9c1d2e3f'])}


RETRY_DIFF = '\n'.join([
    '@@ -18,9 +18,9 @@ export const ratingsClient = createClient({',
    "   baseUrl: process.env.RATINGS_URL,",
    '   retry: {',
    '-    attempts: 3,',
    '-    backoff: { type: "exponential", initialMs: 200, maxMs: 5000, jitter: true },',
    '+    attempts: 10,',
    '+    backoff: { type: "fixed", delayMs: 0 },',
    '   },',
])


def h02_retry_storm():
    logs = [log(30 + k // 2, 'product-page', 'WARN', f'ratings request failed, retrying (attempt {a}/10)')
            for k, a in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 2)]
    logs += [log(31 + k, 'ratings-svc', 'ERROR', '503 Service Unavailable: request queue full (1024 waiting)')
             for k in range(6)]
    return {
        'id': 'h02_retry_storm', 'set': SET, 'category': 'bad deploy',
        'name': 'Retry storm from a client change overloads a healthy service',
        'data': {'logs': logs,
                 'code_changes': [commit('e5a91b02', 26, 'zoe', 'fix(product-page): make ratings calls more resilient',
                                         [{'path': 'web/src/clients/ratings.ts', 'diff': RETRY_DIFF}])],
                 'metrics_summary': {
                     'cpu': {'usage_percent': stats(61, 99, 97, 'INCREASING')},
                     'per_service': {'cpu_usage_percent': {'ratings-svc': stats(83, 99, 98, 'INCREASING'),
                                                           'product-page': stats(35, 41, 39)}}},
                 'traces': {'span_count': 4200, 'trace_count': 300, 'error_span_count': 2600, 'source': 'otlp',
                            'services_touched': ['product-page', 'ratings-svc'],
                            'top_errors': [{'service_name': 'ratings-svc', 'operation_name': 'GET /ratings/{sku}',
                                            'status_message': '503'}]}},
        'answer': answer(['product-page'], cause=[['retry', 'retries', 'retrying'],
                                                  ['backoff', 'back-off', 'storm', 'amplif', '10 attempts', 'attempts',
                                                   'delay']],
                         blame_sha='e5a91b02')}


KAFKA_DIFF = '\n'.join([
    '@@ -7,7 +7,7 @@ spring:',
    '     consumer:',
    '       group-id: order-events',
    '-      max-poll-records: 500',
    '+      max-poll-records: 5000',
    '       properties:',
    '         max.poll.interval.ms: 300000',
])


def h03_kafka_rebalance():
    logs = []
    for k in range(4):
        m = 22 + k * 6
        logs += [log(m, 'order-events-consumer', 'WARN',
                     'consumer poll timeout has expired. This means the time between subsequent calls to poll() was '
                     'longer than the configured max.poll.interval.ms, which typically implies that the poll loop is '
                     'spending too much time processing messages.'),
                 log(m, 'order-events-consumer', 'INFO', '[Consumer clientId=consumer-order-events-1] Member sending '
                     'LeaveGroup request to coordinator'),
                 log(m + 1, 'order-events-consumer', 'INFO', 'Revoking previously assigned partitions [order-events-0, '
                     'order-events-1, order-events-2]'),
                 log(m + 2, 'order-events-consumer', 'ERROR', 'CommitFailedException: Commit cannot be completed since '
                     'the group has already rebalanced and assigned the partitions to another member.')]
    logs.append(log(40, 'fulfilment', 'WARN', 'no new paid orders received for 18 minutes'))
    return {
        'id': 'h03_kafka_rebalance', 'set': SET, 'category': 'config',
        'name': 'Kafka consumer rebalance loop after a poll-size change',
        'data': {'logs': logs,
                 'code_changes': [commit('71f0c3aa', 15, 'li', 'perf(consumer): fetch more records per poll',
                                         [{'path': 'consumer/src/main/resources/application.yaml', 'diff': KAFKA_DIFF}])],
                 'metrics_summary': {'cpu': {'usage_percent': stats(58, 88, 61)}}},
        'answer': answer(['order-events-consumer'],
                         cause=[['poll', 'max-poll-records', 'max.poll'], ['5000', 'records', 'rebalanc', 'interval',
                                                                           'processing time']],
                         blame_sha='71f0c3aa')}


def h04_clock_skew():
    logs = [log(10 + k * 2, 'auth-gateway', 'ERROR',
                'JWT rejected: token used before issued (iat=1792332094, now=1792332000)', host='node-c')
            for k in range(8)]
    logs += [log(11 + k * 5, 'auth-gateway', 'INFO', 'JWT accepted for subject user-81', host=h)
             for k, h in enumerate(['node-a', 'node-b', 'node-a', 'node-b'])]
    logs.append(log(2, 'chronyd', 'WARN', 'System clock wrong by -94.018 seconds, adjustment started; '
                    'no selectable sources', host='node-c'))
    return {
        'id': 'h04_clock_skew', 'set': SET, 'category': 'infrastructure',
        'name': 'Clock skew on one node rejects valid tokens',
        'data': {'logs': logs,
                 'code_changes': [commit('2aa7d19c', -30, 'eva', 'chore(auth): structured logging for token checks',
                                         [{'path': 'gateway/auth/logging.go',
                                           'diff': '@@ -1,3 +1,4 @@\n package auth\n+import "log/slog"\n'}])]},
        'answer': answer(['node-c', 'chronyd', 'auth-gateway'],
                         cause=[['clock', 'time sync', 'ntp', 'chrony', 'skew', 'drift']],
                         wrong_shas=['2aa7d19c'])}


HPA_DIFF = '\n'.join([
    '@@ -6,8 +6,8 @@ spec:',
    '   scaleTargetRef:',
    '     kind: Deployment',
    '     name: search-api',
    '   minReplicas: 2',
    '-  maxReplicas: 20',
    '+  maxReplicas: 2',
])


def h05_hpa_cap():
    logs = [log(40 + k, 'ingress-nginx', 'ERROR', 'upstream timed out (110: Connection timed out) while reading '
                'response header from upstream, upstream: "http://search-api.prod.svc:8080/search"') for k in range(6)]
    logs += [log(39 + k * 2, 'kube-events', 'WARN', 'HorizontalPodAutoscaler search-api: ScalingLimited: the desired '
                 'replica count is more than the maximum replica count') for k in range(3)]
    logs.append(log(30, 'marketing-cron', 'INFO', 'newsletter "Autumn sale" sent to 412000 recipients'))
    return {
        'id': 'h05_hpa_cap', 'set': SET, 'category': 'config',
        'name': 'Autoscaler capped at 2 replicas during a traffic spike',
        'data': {'logs': logs,
                 'code_changes': [commit('d3c4b5a6', -300, 'ops-bot', 'chore(search): right-size autoscaling',
                                         [{'path': 'deploy/k8s/search-api-hpa.yaml', 'diff': HPA_DIFF}]),
                                  commit('a0b1c2d3', -60, 'nora', 'dash: add search latency panel',
                                         [{'path': 'dashboards/search.json',
                                           'diff': '@@ -40,3 +40,9 @@\n   "panels": [\n+    {"title": "p99"}\n'}])],
                 'metrics_summary': {'per_service': {'cpu_usage_percent': {'search-api': stats(91, 100, 99, 'INCREASING'),
                                                                           'web': stats(30, 38, 33)}},
                                     'cpu': {'usage_percent': stats(64, 100, 70, 'INCREASING')}},
                 'traces': {'span_count': 3000, 'trace_count': 1000, 'error_span_count': 410, 'source': 'otlp',
                            'services_touched': ['web', 'search-api'],
                            'top_slow': [{'duration_ms': 30000, 'service_name': 'search-api',
                                          'operation_name': 'GET /search', 'trace_id': 'f00d0001'}]}},
        'answer': answer(['search-api'], cause=[['replica', 'hpa', 'autoscal', 'scale', 'scaling'],
                                                 ['2', 'max', 'cap', 'limit']],
                         blame_sha='d3c4b5a6', wrong_shas=['a0b1c2d3'])}


LOCK_MIGRATION_DIFF = '\n'.join([
    '@@ -0,0 +1,14 @@',
    '+from django.db import migrations, models',
    '+',
    '+class Migration(migrations.Migration):',
    '+    dependencies = [("orders", "0057_order_channel")]',
    '+    operations = [',
    '+        migrations.AlterField(',
    '+            model_name="order",',
    '+            name="total",',
    '+            field=models.DecimalField(max_digits=14, decimal_places=4),',
    '+        ),',
    '+    ]',
])


def h06_migration_lock():
    logs = [log(12, 'orders-api', 'INFO', 'Running migrations: Applying orders.0058_order_total_precision...')]
    logs += [log(12 + k, 'postgres', 'LOG', 'process 4411 still waiting for AccessShareLock on relation 16502 of '
                 'database 16384 after 1000.112 ms', host='db-1') for k in range(4)]
    logs += [log(13 + k // 2, 'orders-api', 'ERROR', 'django.db.utils.OperationalError: canceling statement due to '
                 'lock timeout\nCONTEXT: while locking tuple (412,7) in relation "orders_order"') for k in range(10)]
    return {
        'id': 'h06_migration_lock', 'set': SET, 'category': 'bad deploy',
        'name': 'Migration rewrites a large table and locks it',
        'data': {'logs': logs,
                 'code_changes': [commit('5f6e7d8c', 8, 'omar', 'orders: more precision for totals',
                                         [{'path': 'orders/migrations/0058_order_total_precision.py',
                                           'diff': LOCK_MIGRATION_DIFF}])],
                 'metrics_summary': {'cpu': {'usage_percent': stats(40, 72, 45)}}},
        'answer': answer(['orders-api', 'postgres', 'orders_order'],
                         cause=[['lock', 'locked', 'locking'], ['migration', 'alter', 'rewrite', '0058']],
                         blame_sha='5f6e7d8c')}


def h07_feature_flag():
    logs = [log(20, 'flags-svc', 'INFO', 'flag "new-tax-engine" rollout changed 0% -> 50% by ana@example.com')]
    logs += [log(21 + k // 2, 'tax-svc', 'ERROR', f'TaxRuleNotFound: no rule for region=CA-QC (engine=v2, order={7700 + k})')
             for k in range(12)]
    logs += [log(22 + k * 3, 'tax-svc', 'INFO', 'tax computed (engine=v1, region=CA-QC)') for k in range(4)]
    return {
        'id': 'h07_feature_flag', 'set': SET, 'category': 'config',
        'name': 'Feature-flag rollout with no deploy',
        'data': {'logs': logs,
                 'code_changes': [commit('8a9b0c1d', -45, 'jo', 'test(tax): more fixtures',
                                         [{'path': 'tax/tests/fixtures.py',
                                           'diff': '@@ -1,2 +1,3 @@\n FIXTURES = [\n+    "US-NY",\n'}])]},
        'answer': answer(['tax-svc', 'flags-svc'],
                         cause=[['flag', 'rollout', 'new-tax-engine', 'engine=v2', 'v2'],
                                ['rule', 'region', 'ca-qc', 'quebec']],
                         wrong_shas=['8a9b0c1d'])}


CRON_DIFF = '\n'.join([
    '@@ -9,7 +9,7 @@ spec:',
    '-  schedule: "*/15 * * * *"',
    '+  schedule: "* * * * *"',
    '   jobTemplate:',
    '     spec:',
    '       template:',
])


def h08_rate_limited():
    logs = [log(10 + k, 'shipping-rates', 'ERROR', 'GET https://api.carrier.example/v2/rates -> 429 Too Many Requests '
                '(Retry-After: 3600, X-RateLimit-Remaining: 0)') for k in range(10)]
    logs += [log(10 + k * 3, 'checkout-api', 'WARN', 'shipping quote unavailable, showing flat rate') for k in range(4)]
    return {
        'id': 'h08_rate_limited', 'set': SET, 'category': 'bad deploy',
        'name': 'Carrier API rate limit after a polling schedule change',
        'data': {'logs': logs,
                 'code_changes': [commit('c1d2e3f4', -50, 'tim', 'feat(shipping): fresher carrier rates',
                                         [{'path': 'deploy/k8s/rates-refresh-cronjob.yaml', 'diff': CRON_DIFF}])]},
        'answer': answer(['shipping-rates'],
                         cause=[['429', 'rate limit', 'rate-limit', 'too many requests', 'quota'],
                                ['schedule', 'cron', 'every minute', 'polling', 'frequency', '15']],
                         blame_sha='c1d2e3f4')}


def h09_benign_deploy():
    logs = [log(1, 'catalog', 'INFO', 'Deployment catalog rolled out revision 41 (3/3 replicas ready)'),
            log(2, 'catalog', 'INFO', 'GET /healthz 200 3ms'),
            log(3, 'catalog', 'WARN', 'request to pricing-svc failed (connection reset), retrying (1/3)'),
            log(3, 'catalog', 'INFO', 'request to pricing-svc succeeded on retry 1'),
            log(6, 'catalog', 'INFO', 'cache warmed: 18211 products in 4.2s')]
    return {
        # Moved to the tuned set on 2026-10-25: its first run raised a WARNING,
        # and the log filter was changed to keep recovery lines because of it.
        'id': 'h09_benign_deploy', 'set': 'tuned', 'category': 'healthy',
        'name': 'Clean deploy with one retried request (nothing wrong)',
        'data': {'logs': logs,
                 'code_changes': [commit('e7f8a9b0', -5, 'kai', 'feat(catalog): show product badges',
                                         [{'path': 'catalog/templates/badge.html',
                                           'diff': '@@ -0,0 +1,2 @@\n+<span class="badge">{{ label }}</span>\n'}])],
                 'metrics_summary': {'cpu': {'usage_percent': stats(18, 34, 17)},
                                     'memory': {'usage_percent': stats(44, 47, 45)}}},
        'answer': answer(['catalog'], benign_max='INFO', wrong_shas=['e7f8a9b0'])}


def h10_benign_spike():
    logs = [log(k * 5, 'kube-events', 'INFO', f'HorizontalPodAutoscaler web: SuccessfulRescale New size: {n}; reason: '
                'cpu resource utilization (percentage of request) above target') for k, n in enumerate((4, 6, 8))]
    logs += [log(16, 'web', 'INFO', 'p99 latency 410ms (SLO 800ms)')]
    return {
        'id': 'h10_benign_spike', 'set': SET, 'category': 'healthy',
        'name': 'Traffic spike absorbed by autoscaling (nothing wrong)',
        'data': {'logs': logs, 'code_changes': [],
                 'metrics_summary': {'cpu': {'usage_percent': stats(52, 74, 41, 'DECREASING')},
                                     'memory': {'usage_percent': stats(50, 55, 51)}},
                 'traces': {'span_count': 9000, 'trace_count': 3000, 'error_span_count': 0, 'source': 'otlp',
                            'services_touched': ['web', 'catalog'],
                            'top_slow': [{'duration_ms': 412, 'service_name': 'web', 'operation_name': 'GET /',
                                          'trace_id': 'beef0001'}]}},
        'answer': answer(['web'], benign_max='WARNING')}


def h11_red_herring():
    logs = [log(k, 'mobile-gateway', 'WARN', 'GET /v1/legacy/profile 404 (client app 3.2.1)') for k in range(0, 60, 3)]
    logs.append(log(31, 'vault', 'INFO', 'secret "smtp/notifications" rotated (version 7 -> 8) by policy rotate-90d'))
    logs += [log(32 + k, 'notifications-svc', 'ERROR', 'smtplib.SMTPAuthenticationError: (535, b"5.7.8 Authentication '
                 'credentials invalid")') for k in range(8)]
    logs.append(log(45, 'notifications-svc', 'WARN', 'email queue depth 2210 (oldest 13m)'))
    return {
        'id': 'h11_red_herring', 'set': SET, 'category': 'infrastructure',
        'name': 'Rotated SMTP password, next to old unrelated 404 noise',
        'data': {'logs': logs, 'code_changes': []},
        'answer': answer(['notifications-svc'],
                         cause=[['smtp', 'email', 'mail'], ['credential', 'password', 'auth', '535', 'rotat']],
                         decoy_services=['mobile-gateway'])}


def h12_es_watermark():
    logs = [log(5, 'elasticsearch', 'WARN', 'flood stage disk watermark [95%] exceeded on [es-data-2][/data] free: '
                '4.1gb[4.9%], all indices on this node will be marked read-only', host='es-data-2')]
    logs += [log(6 + k, svc, 'ERROR', 'ClusterBlockException: index [' + idx + '] blocked by: [TOO_MANY_REQUESTS/12/'
                 'disk usage exceeded flood-stage watermark, index has read-only-allow-delete block]')
             for k, (svc, idx) in enumerate([('logging-api', 'app-logs-2026.10.18'), ('search-api', 'products-v7'),
                                             ('audit-svc', 'audit-2026.10'), ('logging-api', 'app-logs-2026.10.18'),
                                             ('search-api', 'products-v7'), ('audit-svc', 'audit-2026.10')])]
    return {
        'id': 'h12_es_watermark', 'set': SET, 'category': 'infrastructure',
        'name': 'Elasticsearch disk watermark blocks writes for three services',
        'data': {'logs': logs, 'code_changes': [commit('f1e2d3c4', -15, 'tom', 'style: rounder buttons',
                                                       [{'path': 'web/styles/buttons.css', 'diff': UNRELATED_CSS}])]},
        'answer': answer(['elasticsearch', 'es-data-2'],
                         cause=[['disk', 'watermark', 'flood'], ['read-only', 'read only', 'readonly', 'block']],
                         wrong_shas=['f1e2d3c4'])}


SCENARIOS = [h01_connection_leak, h02_retry_storm, h03_kafka_rebalance, h04_clock_skew, h05_hpa_cap,
             h06_migration_lock, h07_feature_flag, h08_rate_limited, h10_benign_spike,
             h11_red_herring, h12_es_watermark]
# Written here, then tuned on: see tuned.MOVED.
MOVED_TO_TUNED = [h09_benign_deploy]
