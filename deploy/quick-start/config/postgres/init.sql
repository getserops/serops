-- SerOps Postgres init script.
--
-- Runs once, only when the data directory is first initialised. Adds
-- the pg_stat_statements extension for query-level observability. Any
-- future migrations happen through Django's `manage.py migrate`.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
