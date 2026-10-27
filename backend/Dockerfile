FROM python:3.11-slim

WORKDIR /app

# Debian security fixes released since the base image was built. The app
# runs as an unprivileged user (uid 10001); the code stays root-owned, so
# that user can read it but not change it.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* && \
    groupadd --system --gid 10001 serops && \
    useradd --system --uid 10001 --gid serops --home-dir /app --no-create-home --shell /usr/sbin/nologin serops

COPY requirements.txt .
# pip, setuptools and wheel ship with the base image and lag behind their
# security fixes; upgrade them with the rest. pip itself is removed once
# the requirements are in: nothing runs it, and it vendors its own copies
# of urllib3 and msgpack that image scanners report.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pip

COPY . .
RUN mkdir -p /app/logs /app/images && chown serops:serops /app/logs /app/images

# Version metadata baked in at build time (Batch 44, SemVer discipline).
# CI passes these via ``--build-arg`` from the docker/metadata-action
# outputs; manual builds without args fall through to ``1.0.0-dev``
# handled by ``api/version.py``. All three become process ENV so
# Django + celery can read them via ``os.getenv`` and ``/api/version/``
# can serve them.
ARG SEROPS_VERSION=""
ARG SEROPS_GIT_SHA=""
ARG SEROPS_BUILT_AT=""
ENV SEROPS_VERSION=$SEROPS_VERSION \
    SEROPS_GIT_SHA=$SEROPS_GIT_SHA \
    SEROPS_BUILT_AT=$SEROPS_BUILT_AT

USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/')" || exit 1

CMD ["bash", "start.sh"]
