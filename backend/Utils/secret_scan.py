"""Secret scan for committed configuration: literal passwords.

Run by pre-commit (backend/.pre-commit-config.yaml) on staged files and by CI
(.gitlab-ci.yml and .github/workflows/ci.yml, job secret-scan) on every tracked file.
Standard library only, so it runs without the backend's dependencies:

    python backend/Utils/secret_scan.py [--all] [FILE ...]

Why it exists: backend/fluentd/conf/fluent.conf was committed with a real
Elasticsearch host, user and password in fluentd syntax (`password <value>`,
no `=` or `:`), which detect-private-key and the .env guard do not look at.

What it reports (rule names in the output):

- password-literal: a password key followed by a literal value, in any of the
  forms `password value`, `password: value`, `password=value`, `"password":
  "value"`, and prefixed keys (`db_password`, `POSTGRES_PASSWORD`). Only in
  configuration files (see CONFIG_SUFFIXES); code is left to the reviewers
  and its tests use throwaway passwords on purpose.
- user-password-pair: the same, when a `user`/`username` key with a literal
  value sits within PAIR_WINDOW lines: the shape of a working login.
- encoded-password: a password key followed by a long base64- or hex-looking
  value, in any text file, code included.

Not reported: placeholders (`${VAR}`, `#{ENV[...]}`, `<...>`, `{{ ... }}`,
`change-me`, `example`, `xxx`, empty values...), and lines carrying the marker
`secret-scan: allow` (say why next to it). Output names the file, line, and
rule, never the value.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOW_MARKER = 'secret-scan: allow'
PAIR_WINDOW = 3

CONFIG_SUFFIXES = {
    '.conf', '.cfg', '.cnf', '.ini', '.properties', '.toml', '.yml', '.yaml',
    '.json', '.env', '.tf', '.tfvars', '.hcl', '.xml', '.service',
}
CONFIG_NAMES = {'.env', 'Caddyfile', 'Dockerfile', '.npmrc', '.pypirc', '.netrc', 'pg_hba.conf'}
SKIP_SUFFIXES = {
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp', '.pdf', '.woff', '.woff2',
    '.ttf', '.eot', '.gz', '.tgz', '.zip', '.lock', '.min.js', '.map',
}
SKIP_NAMES = {'package-lock.json'}
MAX_FILE_BYTES = 2_000_000

# `key: value`, `key=value`, `"key": "value"` anywhere on a line ...
_KEY = r'(?:[A-Za-z0-9]+[_.-])*(?:password|passwd|passphrase|pwd)'
_USER_KEY = r'(?:[A-Za-z0-9]+[_.-])*(?:user|username|user_name|login)'
_KV = r'''(?ix)
    (?:^|[\s{,"'(])
    ["']?(?P<key>%s)["']?
    \s*[:=]\s*
    (?P<q>["']?)(?P<value>[^\s"',;]+)(?P=q)
    '''
# ... and directive style, the whole line being `key value` (fluentd, nginx,
# Caddy, my.cnf without `=`), so prose such as "password is required" is not
# taken for a value.
_DIRECTIVE = r'''(?ix)
    ^\s*(?P<key>%s)\s+(?P<q>["']?)(?P<value>[^\s"']+)(?P=q)\s*$
    '''
PASSWORD_RES = [re.compile(_KV % _KEY), re.compile(_DIRECTIVE % _KEY)]
USER_RES = [re.compile(_KV % _USER_KEY), re.compile(_DIRECTIVE % _USER_KEY)]
B64_RE = re.compile(r'^[A-Za-z0-9+/_-]{20,}={0,2}$')
HEX_RE = re.compile(r'^[0-9a-fA-F]{24,}$')

PLACEHOLDER_RE = re.compile(
    r'''(?ix)
    ^(?:
        \$ | \#\{ | % | < | \{\{ | \[ | @ | \* | \.\.\. | ` | ENC\[      # templating, references
      | (?:true|false|none|null|nil|required|optional|str|string|bool|int)$
    )
    | change.?me | changeit | replace.?me | your[_-] | example | placeholder | dummy
    | redacted | x{3,} | \*{3,} | ^-+$ | ^\.+$ | ^_+$ | fake | sample | not.?set | todo
    | ^(?:empty|generated|password|passwd|pwd|passphrase)$          # prose, UI labels
    | ^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\)?$                         # code reference: u.password
    ''')


def _is_placeholder(value: str) -> bool:
    v = value.strip().strip('"\'')
    return not v or bool(PLACEHOLDER_RE.search(v))


def _looks_encoded(value: str) -> bool:
    v = value.strip().strip('"\'')
    if HEX_RE.match(v):
        return True
    if B64_RE.match(v):
        classes = sum(bool(re.search(p, v)) for p in (r'[a-z]', r'[A-Z]', r'[0-9]'))
        return classes >= 3
    return False


def _is_config(path: Path) -> bool:
    name = path.name
    return (name in CONFIG_NAMES or name.startswith('.env') or path.suffix.lower() in CONFIG_SUFFIXES
            or name.endswith('.conf.example') or name.endswith('.yml.example'))


def scan_text(text: str, path: str = '<text>') -> list[tuple[str, int, str]]:
    """Return (path, line number, rule) for every finding. Never the value."""
    p = Path(path)
    config = _is_config(p)
    lines = text.splitlines()
    users = {i for i, line in enumerate(lines) for rx in USER_RES
             for m in [rx.search(line)] if m and not _is_placeholder(m.group('value'))}
    findings = []
    for i, line in enumerate(lines):
        if ALLOW_MARKER in line:
            continue
        for m in (m for rx in PASSWORD_RES for m in rx.finditer(line)):
            value = m.group('value')
            if _is_placeholder(value) or line[:m.start('key')].endswith('${'):
                continue  # placeholder, or the name inside a ${VAR:?msg} reference
            if _looks_encoded(value):
                findings.append((path, i + 1, 'encoded-password'))
            elif config:
                near_user = any(abs(i - j) <= PAIR_WINDOW for j in users)
                findings.append((path, i + 1, 'user-password-pair' if near_user else 'password-literal'))
            break
    return findings


def scan_file(path: Path) -> list[tuple[str, int, str]]:
    name = path.name
    if name in SKIP_NAMES or any(name.endswith(s) for s in SKIP_SUFFIXES):
        return []
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    if b'\0' in data[:8192]:
        return []
    return scan_text(data.decode('utf-8', 'replace'), str(path))


def _tracked_files() -> list[Path]:
    out = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, check=True).stdout
    return [Path(p) for p in out.decode().split('\0') if p]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--all', action='store_true', help='scan every file git tracks')
    ap.add_argument('files', nargs='*')
    args = ap.parse_args(argv)
    files = _tracked_files() if args.all else [Path(f) for f in args.files]
    findings = [f for path in files if path.is_file() for f in scan_file(path)]
    for path, line, rule in findings:
        print(f'{path}:{line}: {rule} (value not shown). Remove it, use a placeholder, '
              f'or mark the line "{ALLOW_MARKER}" with the reason.')
    if findings:
        print(f'secret scan: {len(findings)} finding(s) in {len(files)} file(s)', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
