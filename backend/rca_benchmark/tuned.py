"""
Tuned incidents: the first twelve, from the October 2026 RCA review. Prompt
rules were changed while some of these failed (one issue per root cause,
the capability gate), so a pass here is expected, not evidence. The
held-out set is the measure; this one guards against regressions.

The bodies are kept as they were run; ``_scenario`` maps their original
answer keys onto the shared format.
"""
from .dataset import UNRELATED_CSS, answer, commit, filler, log, ts

SET = 'tuned'

PY_POOL_DIFF = '\n'.join([
    '@@ -1,6 +1,6 @@ import os',
    ' import os', ' import logging', filler(4, 1, ''),
    '@@ -88,9 +88,9 @@ class DatabaseSettings:',
    filler(6, 88),
    '-    pool_size = int(os.getenv("DB_POOL_SIZE", "50"))',
    '+    pool_size = int(os.getenv("DB_POOL_SIZE", "5"))',
    '     pool_timeout = 30',
])

GO_CACHE_DIFF = '\n'.join([
    '@@ -40,12 +40,18 @@ type Resolver struct {',
    ' func (r *Resolver) Lookup(ctx context.Context, sku string) (*Price, error) {',
    '+\tif p, ok := r.cache[sku]; ok {',
    '+\t\treturn p, nil',
    '+\t}',
    ' \tp, err := r.upstream.Fetch(ctx, sku)',
    ' \tif err != nil {',
    ' \t\treturn nil, err',
    ' \t}',
    '+\tr.cache[sku] = p // cache every price, forever',
    ' \treturn p, nil',
    ' }',
])

NODE_ENV_DIFF = '\n'.join([
    '@@ -12,7 +12,7 @@ spec:',
    '       containers:',
    '         - name: orders-api',
    '           env:',
    '-            - name: DATABASE_URL',
    '+            - name: DATABSE_URL',
    '               valueFrom:',
    '                 secretKeyRef: { name: orders-db, key: url }',
])

MIGRATION_DIFF = '\n'.join([
    '@@ -1,14 +1,12 @@',
    ' from django.db import migrations',
    ' ',
    ' class Migration(migrations.Migration):',
    '     dependencies = [("orders", "0041_order_status")]',
    '     operations = [',
    '-        migrations.AddIndex(',
    '-            model_name="order",',
    '-            index=models.Index(fields=["customer_id", "created_at"], name="order_cust_created"),',
    '-        ),',
    '+        migrations.RemoveIndex(model_name="order", name="order_cust_created"),',
    '     ]',
])

JAVA_NPE_DIFF = '\n'.join([
    '@@ -60,10 +60,16 @@ public class InvoiceService {',
    filler(5, 60, '        '),
    '     public Invoice build(Order order) {',
    '-        BigDecimal discount = BigDecimal.ZERO;',
    '+        BigDecimal discount = order.getCoupon().getAmount();',
    '         return new Invoice(order.getTotal().subtract(discount));',
    '     }',
])

REDIS_VALUES_DIFF = '\n'.join([
    '@@ -20,6 +20,6 @@ redis:',
    '   master:',
    '     persistence: { enabled: true }',
    '   commonConfiguration: |-',
    '-    maxclients 10000',
    '+    maxclients 200',
    '     appendonly yes',
])

DEPS_DIFF = '\n'.join([
    '@@ -14,7 +14,7 @@',
    '   "dependencies": {',
    '-    "date-fns": "^3.6.0",',
    '+    "date-fns": "^4.1.0",',
    '     "react": "^18.3.1",',
])


def s01_db_pool():
    logs = [log(40 + k // 3, 'checkout-api', 'ERROR', m) for k, m in enumerate([
        'Traceback (most recent call last):\n  File "/app/api/views/checkout.py", line 212, in place_order\n    with db.session() as s:\n  File "/app/core/settings/database.py", line 96, in session\n    conn = self.pool.connect(timeout=self.pool_timeout)\nsqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 0 reached, connection timed out, timeout 30.00',
    ] * 9)] + [log(38, 'checkout-api', 'INFO', 'Deployment checkout-api rolled out revision 118')]
    return {
        'name': 'Bad deploy: DB pool shrunk to 5',
        'data': {'logs': logs,
                 'code_changes': [commit('a91f3c27', 35, 'priya', 'perf: tune DB settings for smaller pods',
                                         [{'path': 'core/settings/database.py', 'diff': PY_POOL_DIFF}]),
                                  commit('c03be19d', 30, 'tom', 'style: rounder buttons',
                                         [{'path': 'web/styles/buttons.css', 'diff': UNRELATED_CSS}])],
                 'metrics_summary': {'cpu': {'usage_percent': {'avg': 31, 'max': 44, 'current': 35, 'trend': 'STABLE'}}}},
        'expect_any': [['pool'], ['5', 'size', 'shrunk', 'reduced', 'lowered']],
        'component': 'checkout-api', 'blame_sha': 'a91f3c27', 'wrong_shas': ['c03be19d']}


def s02_memory_leak():
    logs = [log(m, 'pricing-svc', 'WARN', 'GC pause 1840ms, heap 1.7GiB of 2GiB') for m in (10, 25, 40)]
    logs += [log(55, 'pricing-svc', 'ERROR', 'context deadline exceeded calling pricing-svc /v1/price (pricing-svc pod restarting)'),
             log(56, 'cart-api', 'ERROR', 'upstream pricing-svc unavailable: connection refused')]
    return {
        'name': 'Memory leak from an unbounded cache (OOMKilled)',
        'data': {'logs': logs,
                 'code_changes': [commit('5e72d0aa', -120, 'lee', 'perf: cache resolved prices',
                                         [{'path': 'internal/pricing/resolver.go', 'diff': GO_CACHE_DIFF}])],
                 'metrics_summary': {
                     'memory': {'usage_percent': {'avg': 78, 'max': 99, 'current': 41, 'trend': 'INCREASING'},
                                'anomalies': [{'start_time': ts(30), 'peak_value': 99, 'duration_seconds': 1500, 'service': 'pricing-svc'}]},
                     'container_lifecycle': {'terminated': [{'container': 'pricing-svc', 'reason': 'OOMKilled'}],
                                             'restarts': {'pricing-svc': 3}}}},
        'expect_any': [['memory', 'oom', 'leak'], ['cache']],
        'component': 'pricing-svc', 'blame_sha': '5e72d0aa', 'wrong_shas': []}


def s03_env_typo():
    logs = [log(20 + k, 'orders-api', 'ERROR', m) for k, m in enumerate([
        "Error: DATABASE_URL is not set\n    at loadConfig (/srv/app/src/config.ts:18:11)\n    at Object.<anonymous> (/srv/app/src/server.ts:9:1)",
        "orders-api exited with code 1",
        "Back-off restarting failed container orders-api",
    ] * 3)]
    return {
        'name': 'Config typo in the deployment manifest',
        'data': {'logs': logs,
                 'code_changes': [commit('77ab01ce', 18, 'sam', 'chore: tidy orders deployment manifest',
                                         [{'path': 'deploy/k8s/orders-api.yaml', 'diff': NODE_ENV_DIFF}])],
                 'metrics_summary': {'container_lifecycle': {'restarts': {'orders-api': 6}}}},
        'expect_any': [['database_url', 'databse_url', 'env', 'environment variable'], ['typo', 'misspel', 'databse']],
        'component': 'orders-api', 'blame_sha': '77ab01ce', 'wrong_shas': []}


def s04_third_party_outage():
    logs = [log(30 + k // 2, 'payments', 'ERROR', m) for k, m in enumerate([
        'POST https://api.stripe-like.example/v1/charges -> 503 Service Unavailable (attempt 3/3)',
        'charge failed for order 88{k}: upstream payment provider unavailable'.replace('{k}', '1'),
    ] * 8)]
    return {
        'name': 'Third-party payment provider outage (no code at fault)',
        'data': {'logs': logs,
                 'code_changes': [commit('19d2e4bb', 5, 'ana', 'docs: update README badges',
                                         [{'path': 'README.md', 'diff': '@@ -1,3 +1,4 @@\n # Payments\n+[![build](badge.svg)](ci)\n'}])],
                 'traces': {'span_count': 120, 'trace_count': 40, 'error_span_count': 32, 'source': 'otlp',
                            'services_touched': ['payments'],
                            'top_errors': [{'service_name': 'payments', 'operation_name': 'POST /v1/charges (external)',
                                            'status_message': '503 Service Unavailable'}]}},
        'expect_any': [['provider', 'third-party', 'third party', 'external', 'upstream', 'stripe'], ['503', 'unavailable', 'outage']],
        'component': 'payments', 'blame_sha': None, 'wrong_shas': ['19d2e4bb']}


def s05_cert_expiry():
    logs = [log(0 + k * 3, svc, 'ERROR',
                'x509: certificate has expired or is not yet valid: current time 2026-10-18T14:00:12Z is after 2026-10-18T00:00:00Z (dial tcp inventory.internal:443)')
            for k, svc in enumerate(['catalog', 'checkout-api', 'catalog', 'search', 'checkout-api'])]
    return {
        'name': 'Expired internal TLS certificate',
        'data': {'logs': logs, 'code_changes': []},
        'expect_any': [['certificate', 'cert', 'x509', 'tls'], ['expire']],
        'component': 'inventory', 'blame_sha': None, 'wrong_shas': []}


def s06_disk_full():
    logs = [log(10 + k, 'postgres-primary', 'ERROR', m, host='db-1') for k, m in enumerate([
        'PANIC: could not write to file "pg_wal/xlogtemp.112": No space left on device',
        'LOG: database system is shut down',
        'FATAL: the database system is in recovery mode',
    ])] + [log(12, 'orders-api', 'ERROR', 'psycopg2.OperationalError: could not connect to server: Connection refused')]
    return {
        'name': 'Postgres disk full (WAL)',
        'data': {'logs': logs, 'code_changes': []},
        'expect_any': [['disk', 'space', 'storage', 'volume'], ['wal', 'full', 'no space']],
        'component': 'postgres-primary', 'blame_sha': None, 'wrong_shas': []}


def s07_slow_query():
    return {
        'name': 'Latency regression after an index was dropped (no errors)',
        'data': {'logs': [log(5, 'orders-api', 'INFO', 'Applied migration orders.0042_drop_customer_index')],
                 'code_changes': [commit('e4c88a10', 2, 'kim', 'db: drop unused order index',
                                         [{'path': 'orders/migrations/0042_drop_customer_index.py', 'diff': MIGRATION_DIFF}])],
                 'traces': {'span_count': 900, 'trace_count': 300, 'error_span_count': 0, 'source': 'otlp',
                            'services_touched': ['orders-api', 'web'],
                            'top_slow': [{'duration_ms': 4210, 'service_name': 'orders-api', 'operation_name': 'SELECT orders WHERE customer_id = ? ORDER BY created_at', 'trace_id': 'aa11bb22cc33dd44'},
                                         {'duration_ms': 3980, 'service_name': 'orders-api', 'operation_name': 'GET /orders/history', 'trace_id': 'aa11bb22cc33dd45'}]}},
        'expect_any': [['index'], ['slow', 'latency', 'query']],
        'component': 'orders-api', 'blame_sha': 'e4c88a10', 'wrong_shas': []}


def s08_ci_failure():
    return {
        'name': 'CI failure after a major dependency bump',
        'data': {'logs': [],
                 'code_changes': [commit('0f3a9d55', 1, 'dependabot', 'build(deps): bump date-fns from 3.6.0 to 4.1.0',
                                         [{'path': 'web/package.json', 'diff': DEPS_DIFF}])],
                 'cicd_logs': [{'status': 'failed', 'job_name': 'web:test', 'branch': 'main', 'pipeline_id': 4512,
                                'trace_errors': "FAIL src/utils/dates.test.ts\n  TypeError: (0 , _dateFns.format) is not a function\n    at formatOrderDate (src/utils/dates.ts:7:10)\nTests: 14 failed, 212 passed"},
                               {'status': 'success', 'job_name': 'api:test', 'branch': 'main', 'pipeline_id': 4512, 'duration': 300}]},
        'expect_any': [['date-fns', 'dependency', 'upgrade', 'bump'], ['4', 'major', 'breaking', 'format']],
        'component': 'web', 'blame_sha': '0f3a9d55', 'wrong_shas': []}


def s09_benign_noise():
    logs = [log(k * 4, 'search', 'WARN', m) for k, m in enumerate([
        'DeprecationWarning: The "body" parameter of client.search is deprecated, use keyword arguments',
        'slow log: query took 640ms (threshold 500ms)',
    ] * 4)]
    return {
        'name': 'Benign noise only (should not raise a critical)',
        'data': {'logs': logs, 'code_changes': [],
                 'metrics_summary': {'cpu': {'usage_percent': {'avg': 22, 'max': 30, 'current': 21, 'trend': 'STABLE'}},
                                     'memory': {'usage_percent': {'avg': 48, 'max': 52, 'current': 47, 'trend': 'STABLE'}}}},
        'expect_any': [],
        'component': 'search', 'blame_sha': None, 'wrong_shas': [], 'max_severity': 'WARNING'}


def s10_redis_maxclients():
    msgs = [('cart-api', 'redis.exceptions.ConnectionError: max number of clients reached'),
            ('sessions', 'ERR max number of clients reached (redis-cache:6379)'),
            ('checkout-api', 'Error 111 connecting to redis-cache:6379. Connection refused.'),
            ('cart-api', 'redis.exceptions.ConnectionError: max number of clients reached')]
    logs = [log(20 + k, s, 'ERROR', m) for k, (s, m) in enumerate(msgs * 3)]
    return {
        'name': 'Redis maxclients lowered in Helm values (multi-service symptoms)',
        'data': {'logs': logs,
                 'code_changes': [commit('b8e1f904', 15, 'ops-bot', 'chore(redis): tighten connection limits',
                                         [{'path': 'deploy/helm/redis/values.yaml', 'diff': REDIS_VALUES_DIFF}]),
                                  commit('c03be19e', 12, 'tom', 'style: rounder buttons',
                                         [{'path': 'web/styles/buttons.css', 'diff': UNRELATED_CSS}])]},
        'expect_any': [['maxclients', 'max number of clients', 'connection limit', 'client limit'], ['200', 'lowered', 'reduced', 'limit']],
        'component': 'redis-cache', 'blame_sha': 'b8e1f904', 'wrong_shas': ['c03be19e']}


def s11_java_npe():
    trace = ('java.lang.NullPointerException: Cannot invoke "com.acme.billing.Coupon.getAmount()" because the return value of "com.acme.billing.Order.getCoupon()" is null\n'
             '\tat com.acme.billing.InvoiceService.build(InvoiceService.java:66)\n'
             '\tat com.acme.billing.BillingController.invoice(BillingController.java:41)')
    logs = [log(30 + k, 'billing', 'ERROR', trace) for k in range(6)]
    return {
        'name': 'Java NPE from a new code path (orders without a coupon)',
        'data': {'logs': logs,
                 'code_changes': [commit('3d5f8c12', 25, 'raj', 'feat(billing): apply coupon discounts on invoices',
                                         [{'path': 'src/main/java/com/acme/billing/InvoiceService.java', 'diff': JAVA_NPE_DIFF}])]},
        'expect_any': [['coupon', 'getcoupon'], ['null']],
        'component': 'billing', 'blame_sha': '3d5f8c12', 'wrong_shas': []}


def s12_dns():
    logs = [log(k, svc, 'ERROR', f'getaddrinfo ENOTFOUND {host} (dns lookup timed out after 5000ms)')
            for k, (svc, host) in enumerate([('web', 'orders-api.prod.svc.cluster.local'), ('cart-api', 'redis-cache.prod.svc.cluster.local'),
                                              ('checkout-api', 'payments.prod.svc.cluster.local'), ('web', 'catalog.prod.svc.cluster.local')] * 2)]
    logs.append(log(1, 'coredns', 'ERROR', '[ERROR] plugin/errors: 2 SERVFAIL: read udp 10.0.0.12:53: i/o timeout', host='node-b'))
    return {
        'name': 'Cluster DNS failure (CoreDNS)',
        'data': {'logs': logs, 'code_changes': [],
                 'metrics_summary': {'container_lifecycle': {'restarts': {'coredns': 4}}}},
        'expect_any': [['dns', 'coredns', 'name resolution', 'resolve']],
        'component': 'coredns', 'blame_sha': None, 'wrong_shas': []}


CATEGORIES = {
    's01_db_pool': 'bad deploy', 's02_memory_leak': 'bad deploy', 's03_env_typo': 'config',
    's04_third_party_outage': 'third party', 's05_cert_expiry': 'infrastructure', 's06_disk_full': 'infrastructure',
    's07_slow_query': 'bad deploy', 's08_ci_failure': 'dependency', 's09_benign_noise': 'healthy',
    's10_redis_maxclients': 'config', 's11_java_npe': 'bad deploy', 's12_dns': 'infrastructure',
}
# The original grader matched the first word of the component ("redis" for
# redis-cache); the shared scorer matches whole names, so list both.
EXTRA_SERVICES = {'s10_redis_maxclients': ['redis'], 's12_dns': ['dns']}


def _scenario(build):
    def wrapped():
        old = build()
        sid = build.__name__
        return {
            'id': sid, 'set': SET, 'category': CATEGORIES[sid], 'name': old['name'], 'data': old['data'],
            'answer': answer([old['component']] + EXTRA_SERVICES.get(sid, []), cause=old['expect_any'],
                             blame_sha=old['blame_sha'], wrong_shas=old['wrong_shas'],
                             benign_max=old.get('max_severity')),
        }
    wrapped.__name__ = build.__name__
    return wrapped


from .held_out import MOVED_TO_TUNED  # noqa: E402

SCENARIOS = MOVED_TO_TUNED + [_scenario(b) for b in (
    s01_db_pool, s02_memory_leak, s03_env_typo, s04_third_party_outage, s05_cert_expiry, s06_disk_full,
    s07_slow_query, s08_ci_failure, s09_benign_noise, s10_redis_maxclients, s11_java_npe, s12_dns)]
