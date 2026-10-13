FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /app/logs

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

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

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/')" || exit 1

CMD ["bash", "start.sh"]
