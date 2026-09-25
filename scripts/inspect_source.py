"""Export paragraph IDs and verbatim source text for annotation (no detection)."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile
from lxml import etree

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def paragraphs(path):
    rows = []
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith('word/') or not name.endswith('.xml'):
                continue
            root = etree.fromstring(archive.read(name))
            for i, p in enumerate(root.iter(W + 'p')):
                text = ''.join(n.text or '' for n in p.iter(W + 't')
                               if next(n.iterancestors(W + 'p'), None) is p)
                if text.strip():
                    rows.append({'id': f'{name}:p{i}', 'text': text})
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(paragraphs(args.input), ensure_ascii=False, indent=2), encoding='utf-8')
