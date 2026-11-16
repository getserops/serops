"""Which repository, job or pipeline a webhook payload is about, so that a
correctly signed request is applied only to the binding it was set up for.

The signature or token proves the request comes from the binding's webhook,
not that every repository in the body is the binding's. With a GitHub
organisation webhook, one Jenkins notifier for many jobs, or a Bitbucket
workspace hook, the runs and commits of every other repository were filed
under the one bound service and fed into its root-cause analyses.

The rule for every provider: when the binding names its repository or job
and the payload names one too, they must be the same; otherwise the event
is acknowledged and ignored. A binding or a payload that names nothing is
let through (nothing to compare), as the GitLab receiver already does.
"""
import re
from urllib.parse import unquote


def _norm(value) -> str:
    return str(value or '').strip().strip('{}').lower()


def _add(out, *values):
    for value in values:
        value = _norm(value)
        if value:
            out.add(value)


def repository_identifiers(payload) -> set:
    """Every way the payload names its repository: ids, ``owner/repo``
    paths, UUIDs (GitHub, GitLab, Bitbucket, Gitea, Azure Repos)."""
    out = set()
    if not isinstance(payload, dict):
        return out
    repo = payload.get('repository')
    if isinstance(repo, dict):
        _add(out, repo.get('id'), repo.get('full_name'), repo.get('fullName'), repo.get('uuid'),
             repo.get('path_with_namespace'))
    project = payload.get('project')
    if isinstance(project, dict):
        _add(out, project.get('id'), project.get('path_with_namespace'))
    _add(out, payload.get('project_id'))
    resource = payload.get('resource')
    if isinstance(resource, dict) and isinstance(resource.get('repository'), dict):
        r = resource['repository']
        _add(out, r.get('id'), r.get('name'))
        if isinstance(r.get('project'), dict) and r.get('name'):
            _add(out, f"{r['project'].get('name')}/{r.get('name')}")
    return out


def azure_pipeline_identifiers(payload) -> set:
    """Azure DevOps: the pipeline, build or release definition, the Azure
    project, and the repositories a run built."""
    out = set()
    resource = payload.get('resource') if isinstance(payload, dict) else None
    if not isinstance(resource, dict):
        return out
    run = resource.get('run') if isinstance(resource.get('run'), dict) else resource
    for holder in (run.get('pipeline'), resource.get('pipeline'), resource.get('definition'),
                   (resource.get('release') or {}).get('releaseDefinition'),
                   resource.get('releaseDefinition'), resource.get('project')):
        if isinstance(holder, dict):
            _add(out, holder.get('id'), holder.get('name'))
    for item in resource.get('repositories') or []:
        if isinstance(item, dict) and isinstance(item.get('repository'), dict):
            _add(out, item['repository'].get('fullName'), item['repository'].get('id'))
    return out


def _jenkins_path(value) -> str:
    """``job/folder/job/app/`` (a job URL path) or ``folder/app`` → ``folder/app``."""
    value = unquote(str(value or '')).strip()
    value = re.sub(r'^https?://[^/]+', '', value)
    parts = [p for p in value.split('/') if p]
    if parts and parts[0] == 'job':
        parts = parts[1::2]
    return '/'.join(parts).lower()


def jenkins_job_matches(expected, payload) -> bool:
    """The binding's job path (``folder/job``, or the ``job/folder/job/x``
    form) against the job the notification names. A multibranch job's
    branches (``folder/job/main``) belong to the job. The full path (job
    URL, ``full_name``) is used when the payload has it; the short ``name``
    only when it has nothing else."""
    want = _jenkins_path(expected)
    if not want or not isinstance(payload, dict):
        return True
    full = set()
    url = payload.get('url')
    if isinstance(url, str) and 'job/' in url:
        full.add(_jenkins_path(url[url.index('job/'):]))
    for key in ('full_name', 'fullName'):
        if payload.get(key):
            full.add(_jenkins_path(payload[key]))
    full.discard('')
    if full:
        return any(n == want or n.startswith(want + '/') for n in full)
    short = {_jenkins_path(payload.get(k)) for k in ('name', 'job_name') if payload.get(k)}
    short.discard('')
    if not short:
        return True
    return any(n == want or want.endswith('/' + n) or n.startswith(want + '/') for n in short)


def matches(expected, identifiers) -> bool:
    expected = _norm(expected)
    if not expected or not identifiers:
        return True
    return expected in identifiers
