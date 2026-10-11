from django.db import connection


class QueryTimeoutMiddleware:
    """
    Set statement_timeout on the DB connection for web requests only.
    Tracks the underlying connection identity to re-apply the timeout
    when Django creates a new connection (CONN_MAX_AGE expiry, health check failure).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Ensure a connection exists
        connection.ensure_connection()
        # Track by underlying psycopg2 connection id to detect recycled connections
        conn_id = id(connection.connection)
        if getattr(connection, '_timeout_conn_id', None) != conn_id:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '30s'")
            connection._timeout_conn_id = conn_id
        return self.get_response(request)
