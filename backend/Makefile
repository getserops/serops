# SerOps backend — common developer commands
#
# Prefer these over the raw manage.py incantations so newcomers don't
# have to memorise the docker exec + settings module invocation. Every
# target here assumes the `serops_backend_dev` and `serops_test_db`
# containers are already up (see the workspace README's docker compose
# section).

# Where the actual test runner lives. All targets shell into the
# already-running dev backend container so they share the developer's
# venv, code mount, and network to the local test Postgres.
DOCKER_EXEC := docker exec -e DJANGO_SETTINGS_MODULE=api.test_settings serops_backend_dev
MANAGE := $(DOCKER_EXEC) python manage.py

.PHONY: help test test-unit test-e2e test-fast check migrations

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

test:  ## Run the full canonical test suite (unit + e2e)
	$(MANAGE) test Middlewares.tests Projects.test.test_views \
		Organisations.test.test_onboarding Data.tests.test_views \
		Services.test.test_views integrations.tests.test_integration_views \
		Data.tests.test_cicd_logs_agnostic tests_e2e \
		--verbosity=2 --keepdb

test-unit:  ## Unit + view tests only (skips e2e)
	$(MANAGE) test Middlewares.tests Projects.test.test_views \
		Organisations.test.test_onboarding Data.tests.test_views \
		Services.test.test_views integrations.tests.test_integration_views \
		Data.tests.test_cicd_logs_agnostic \
		--verbosity=2 --keepdb

test-e2e:  ## End-to-end integration tests only
	$(MANAGE) test tests_e2e --verbosity=2 --keepdb

test-fast:  ## Fast smoke run (e2e + one representative unit suite)
	$(MANAGE) test tests_e2e Data.tests.test_views \
		--verbosity=1 --keepdb

check:  ## Django system check
	$(MANAGE) check

migrations:  ## Detect missing migrations
	$(MANAGE) makemigrations --dry-run --check
