---
seo_title: "Jenkins integration (builds and deploys)"
description: "Connect Jenkins to SerOps so build and deployment events are linked to the incidents they cause."
---
# Jenkins Integration

Connect Jenkins pipelines to SerOps for build and deployment tracking.

## Prerequisites

- Jenkins LTS (tested: 2.541.3 — see [Compatibility](compatibility.md))
- User with API Token
- Network access from SerOps to Jenkins URL

---

## Setup

Jenkins integrations are configured in **Integrations**.

1. In Jenkins: **User Profile → Configure → API Token**
2. Click **Add new Token** and give it a name (e.g., "SerOps Integration")
3. Copy the generated token
4. In SerOps: **Integrations**
5. Click **+ Add Integration** and select **Jenkins**
6. Enter:
   - **Name**: Identifier (e.g., "Production Jenkins")
   - **Jenkins URL**: `https://jenkins.example.com`
   - **Username**: Your Jenkins username
   - **API Token**: The token generated above
7. Click **Test Connection** to verify
8. Click **Save**

Once configured, you can link Jenkins to services via the **Add Service Wizard** (Step 3: CI/CD).

---

## Linking to Services

1. Create or edit a service in any project
2. In the **CI/CD** step of the wizard, select **Jenkins**
3. Choose your Jenkins integration from the dropdown
4. Enter the **Pipeline Job Path**: `folder/job-name`
   - For folders: `my-folder/my-job`
   - For multibranch: `my-folder/my-job/branch-name`

---

## Features

| Feature | Description |
|---------|-------------|
| **Build Tracking** | Sync build status (Success/Failure/Unstable) |
| **Log Ingestion** | Fetch console logs for failure analysis |
| **Environment Detection** | Parse branch names to detect environment |

### Console Log Capture

For failed builds, SerOps fetches the console output:
- Up to 1 MB of inline log stored
- Error lines extracted for AI analysis
- Full log available in batch details

---

## Webhook Configuration (Optional)

For real-time updates, configure Jenkins to notify SerOps:

### Generic Webhook Trigger Plugin

1. Install **Generic Webhook Trigger Plugin** in Jenkins
2. In SerOps, find the CI/CD binding for your service and copy the **Webhook URL** and **Token**
   - URL format: `https://your-serops.com/api/webhooks/jenkins/{binding_id}/`
   - Token is auto-generated on binding creation
   - Alternatively, call `POST /api/projects/cicd-bindings/{id}/setup-webhook/` to get the URL
3. In your pipeline configuration, add a post-build action:
   - **URL**: The binding-specific URL from step 2
   - **Content-Type**: `application/json`
   - **Token**: The auto-generated token from step 2

### Jenkinsfile Example

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'make build'
            }
        }
    }
    post {
        always {
            httpRequest(
                url: "https://your-serops.com/api/webhooks/jenkins/${SEROPS_BINDING_ID}/",
                httpMode: 'POST',
                contentType: 'APPLICATION_JSON',
                customHeaders: [[name: 'X-Jenkins-Token', value: "${SEROPS_WEBHOOK_TOKEN}"]],
                requestBody: """{
                    "job_name": "${env.JOB_NAME}",
                    "build_number": "${env.BUILD_NUMBER}",
                    "status": "${currentBuild.result}",
                    "branch": "${env.GIT_BRANCH ?: ''}",
                    "environment": "production"
                }"""
            )
        }
    }
}
```

Set `environment` to where this job deploys (`production`, `staging`, ...).
Without it SerOps guesses from the job and branch names (see
[Environment Mapping](#environment-mapping)); a job that is not built from
Git has no `GIT_BRANCH`, and its deploys were recorded as `development`.

> **Note**: Set `SEROPS_BINDING_ID` and `SEROPS_WEBHOOK_TOKEN` as Jenkins credentials or environment variables from your CI/CD binding in SerOps.

---

## Environment Mapping

When the payload has no `environment`, SerOps detects it from Jenkins job/branch names:

| Pattern | Environment |
|---------|-------------|
| `*-prod*`, `*-production*` | production |
| `*-staging*`, `*-stage*` | staging |
| `*-dev*`, `*-develop*` | development |
| `main`, `master` | production |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "403 Forbidden" | Enable CSRF crumb in Jenkins or disable CSRF for API |
| "Connection Refused" | Check firewall allows traffic from SerOps |
| "401 Unauthorized" | Verify username and token are correct |
| "Job Not Found" | Use full path for folders (e.g., `folder/job`) |
| "No builds syncing" | Check job has recent builds and webhook is configured |

### CSRF Configuration

If using Jenkins 2.x with CSRF protection:

1. Go to **Manage Jenkins → Configure Global Security**
2. Under CSRF Protection, enable "Enable proxy compatibility"

Or add SerOps IP to the CSRF whitelist.
