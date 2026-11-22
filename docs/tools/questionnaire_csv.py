"""Write the security questionnaire's spreadsheet from its docs page.

    python3 docs/tools/questionnaire_csv.py          # rewrite the CSV
    python3 docs/tools/questionnaire_csv.py --check  # exit 1 if it is stale

The table in docs/src/legal/security-questionnaire.md is the one source;
the CSV next to the security pack is generated from it, so the page and the
download never say different things. Markdown links become "text (url)".
"""
import csv
import io
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / 'src'
PAGE = DOCS / 'legal' / 'security-questionnaire.md'
OUT = DOCS / 'assets' / 'security-pack' / 'serops-security-questionnaire.csv'
BASE = 'https://serops.ai/docs/legal/'


def plain(cell):
    def link(m):
        text, url = m.group(1), m.group(2)
        if not url.startswith('http'):
            url = BASE + url.replace('.md', '/')
            url = re.sub(r'/[^/]+/\.\./', '/', url)
        return f'{text} ({url})'
    cell = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, cell)
    return cell.replace('`', '').strip()


def render():
    rows = [l for l in PAGE.read_text().splitlines() if re.match(r'^\| [A-Z&]+-\d+ ', l)]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(['ID', 'Domain (CSA CCM v4)', 'Question', 'Answer', 'Source'])
    for line in rows:
        writer.writerow([plain(c) for c in line.strip().strip('|').split(' | ')])
    return buf.getvalue()


if __name__ == '__main__':
    text = render()
    if '--check' in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            sys.exit(f'{OUT} is out of date: run python3 docs/tools/questionnaire_csv.py')
        print(f'{OUT.name} is up to date')
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text)
        print(f'wrote {OUT} ({text.count(chr(10)) - 1} answers)')
