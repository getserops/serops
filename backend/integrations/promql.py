"""PromQL label matchers built from organisation, project, environment and
service names.

Every label value SerOps puts into PromQL goes through here. An unescaped
``"`` used to end the string literal: a project called ``ops "eu"`` got a
parse error (and no metrics), and a project named
``x"} or up{organisation_name=~".+`` read other organisations' series from a
Prometheus they share.
"""
import re

_LABEL_NAME = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')


def promql_escape(value) -> str:
    """The content of a double-quoted PromQL string literal."""
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def promql_matchers(labels) -> str:
    """``k="v",k2="v2"`` for the non-empty values of ``labels``.

    A label name that is not a valid PromQL name is refused rather than
    dropped: dropping the project or organisation matcher would widen the
    query to other tenants' series.
    """
    parts = []
    for key, value in (labels or {}).items():
        if value is None or value == '':
            continue
        if not _LABEL_NAME.fullmatch(str(key)):
            raise ValueError(f'invalid PromQL label name: {key!r}')
        parts.append(f'{key}="{promql_escape(value)}"')
    return ','.join(parts)
