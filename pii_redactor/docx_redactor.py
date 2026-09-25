"""Replace only matched XML text; preserve runs, tables, drawings and sections.

Each Word XML part is visited once, including headers, footers, text boxes,
footnotes, comments and deleted text. Images are preserved, not OCR-redacted.
"""
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from .fake_map import FakeMapper
from .redact import Detector

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


@dataclass
class ParagraphText:
    id: str
    nodes: list
    text: str
    start: int = 0


def paragraph_records(root, part):
    records = []
    for index, paragraph in enumerate(root.iter(W + 'p')):
        nodes = [n for n in paragraph.iter()
                 if n.tag in {W + 't', W + 'delText', W + 'tab', W + 'br', W + 'cr'}
                 and next(n.iterancestors(W + 'p'), None) is paragraph]
        text = ''.join(node_text(n) for n in nodes)
        records.append(ParagraphText(f'{part}:p{index}', nodes, text))
    return records


def node_text(node):
    if node.tag == W + 'tab':
        return '\t'
    if node.tag in {W + 'br', W + 'cr'}:
        return '\n'
    return node.text or ''


def join_records(records):
    cursor = 0
    for record in records:
        record.start = cursor
        cursor += len(record.text) + 1
    return '\n'.join(r.text for r in records)


def read_records(path):
    records = []
    with ZipFile(path) as archive:
        for part in sorted(archive.namelist()):
            if part.startswith('word/') and part.endswith('.xml'):
                records.extend(paragraph_records(etree.fromstring(archive.read(part), PARSER), part))
    return records


def _replace_nodes(records, spans, mapper, part, log):
    segments = []
    for record in records:
        pos = record.start
        for node in record.nodes:
            size = len(node_text(node))
            if size:
                segments.append((pos, pos + size, node, record.id))
            pos += size
    for span in reversed(spans):
        touched = [(a, b, n, pid) for a, b, n, pid in segments
                   if a < span.end and b > span.start]
        if not touched:
            continue
        fake = mapper.get(span.label, span.text)
        first = True
        for start, end, node, _ in touched:
            if node.tag not in {W + 't', W + 'delText'}:
                continue
            value = node.text or ''
            left, right = max(0, span.start - start), min(end - start, span.end - start)
            node.text = value[:left] + (fake if first else '') + value[right:]
            node.set(XML_SPACE, 'preserve')
            first = False
        if first:
            raise ValueError(f'No writable text for detection in {part}')
        log.append({'part': part, 'paragraph': touched[0][3], 'start': span.start,
                    'end': span.end, 'label': span.label, 'original': span.text, 'fake': fake})


def redact_docx(input_path, output_path, mapper=None, detector=None):
    source, destination = Path(input_path), Path(output_path)
    if source.resolve() == destination.resolve():
        raise ValueError('Input and output must be different files.')
    mapper = mapper or FakeMapper()
    detector = detector or Detector()
    log = []
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp.docx')
    try:
        with ZipFile(source) as original, ZipFile(temporary, 'w') as output:
            for entry in original.infolist():
                content = original.read(entry.filename)
                if entry.filename.startswith('word/') and entry.filename.endswith('.xml'):
                    root = etree.fromstring(content, PARSER)
                    records = paragraph_records(root, entry.filename)
                    story = join_records(records)
                    spans = detector.detect(story)
                    _replace_nodes(records, spans, mapper, entry.filename, log)
                    changed = bool(spans)
                    for node in root.iter():
                        if node.tag == W + 'instrText' and node.text:
                            value = detector.redact(node.text, mapper)
                            changed |= value != node.text
                            node.text = value
                        for key, value in list(node.attrib.items()):
                            if etree.QName(key).localname in {'descr', 'title', 'author', 'initials'}:
                                replacement = detector.redact(value, mapper)
                                changed |= replacement != value
                                node.set(key, replacement)
                    if changed:
                        content = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                elif entry.filename.endswith('.rels'):
                    root = etree.fromstring(content, PARSER)
                    changed = False
                    for rel in root:
                        if rel.get('TargetMode') == 'External':
                            target = rel.get('Target', '')
                            if target.lower().startswith(('mailto:', 'tel:')):
                                prefix, value = target.split(':', 1)
                                from urllib.parse import unquote, quote
                                value = detector.redact(unquote(value), mapper)
                                rel.set('Target', prefix + ':' + quote(value, safe='@.+:-'))
                                changed = True
                    if changed:
                        content = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                elif entry.filename in {'docProps/core.xml', 'docProps/custom.xml'}:
                    root = etree.fromstring(content, PARSER)
                    for node in root.iter():
                        if etree.QName(node).localname in {'creator', 'lastModifiedBy'}:
                            node.text = 'Redacted'
                        elif node.text:
                            node.text = detector.redact(node.text, mapper)
                    content = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                output.writestr(entry, content)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return mapper, sorted(log, key=lambda r: (r['part'], r['start']))
