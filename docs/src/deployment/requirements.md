# System Requirements

Minimum hardware, software, and network requirements for running SerOps in production.

---

## Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPU** | 2 cores | 4+ cores |
| **RAM** | 4 GB | 8 GB |
| **Storage** | 20 GB SSD | 50 GB SSD |

!!! note
    Storage requirements increase with the volume of logs and batches retained. Enable [Data Retention](../admin/data-retention.md) auto-cleanup to manage disk usage.

---

## Operating System

SerOps is tested on the following Linux distributions:

- **Ubuntu 22.04 LTS** (recommended)
- **Debian 11+** (Bullseye or newer)
- Any Linux distribution capable of running Docker

!!! info
    macOS and Windows are supported for local development only. Production deployments should use Linux.

---

## Software Dependencies

| Software | Minimum Version | Purpose |
|----------|-----------------|---------|
| **Docker** | v24+ | Container runtime |
| **Docker Compose** | v2+ | Multi-container orchestration |

Verify your Docker installation:

```bash
docker --version
docker compose version
```

---

## Bundled Services

The following services are included in the Docker Compose stack and do not require separate installation:

### PostgreSQL

| Detail | Value |
|--------|-------|
| **Version** | 16 (Alpine) |
| **Purpose** | Primary application database |
| **Container** | `serops-postgres` |

!!! tip "External PostgreSQL"
    You can optionally use an external PostgreSQL 14+ instance instead of the bundled container. See [Production Deployment](production.md#use-an-external-postgres) for instructions.

### Redis

| Detail | Value |
|--------|-------|
| **Version** | 7.2 (Alpine) |
| **Purpose** | Celery message broker, result backend, and cache |
| **Container** | `serops-redis` |

---

## External Services

### Log Storage Provider (At Least One)

SerOps needs at least one log storage backend to ingest and analyze logs:

| Provider | Notes |
|----------|-------|
| **Elasticsearch** | Most common; version 7.x or 8.x |
| **OpenSearch** | AWS-managed alternative to Elasticsearch |
| **Grafana Loki** | Lightweight, label-based log aggregation |
| **Datadog** | SaaS log management |
| **AWS CloudWatch** | AWS-native log storage |

See the [Observability Providers](../integrations/observability-overview.md) section for setup details.

### Metrics Provider (Optional)

| Provider | Notes |
|----------|-------|
| **Prometheus** | Self-hosted metrics collection |
| **VictoriaMetrics** | High-performance Prometheus alternative |
| **Grafana Mimir** | Scalable long-term metrics storage |
| **Datadog** | SaaS metrics |
| **AWS CloudWatch** | AWS-native metrics |

---

## Network Requirements

### Ports

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| **80** | TCP | Inbound | Frontend (React app via Nginx) |
| **443** | TCP | Inbound | HTTPS (when SSL is configured) |
| **8000** | TCP | Inbound | Django API |
| **5432** | TCP | Internal | PostgreSQL database |
| **6379** | TCP | Internal | Redis broker |

!!! warning
    Do not expose ports 5432 (PostgreSQL) or 6379 (Redis) to the public internet. These should only be accessible within your private network or Docker network.

### Outbound Access

SerOps requires outbound HTTPS access to the following services:

| Destination | Purpose |
|-------------|---------|
| Your SCM provider (GitLab, GitHub, Azure DevOps, Bitbucket) | Webhook verification, repository sync |
| Your log storage provider | Log ingestion and querying |
| AI API endpoints (Google, DeepSeek, OpenAI, Anthropic) | Batch analysis and AI chat |
| SMTP server (optional) | Email notifications |

---

## Next Steps

- [Production Deployment](production.md) -- step-by-step deployment guide
- [Configuration Reference](configuration.md) -- complete `.env` variable reference
