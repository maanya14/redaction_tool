"""Print remaining model suggestions for source review; never auto-label gold."""
import json
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pii_redactor.docx_redactor import read_records
from pii_redactor.redact import Detector
from pii_redactor.detectors import get_nlp, _NAME_BLOCKLIST

source, profile = sys.argv[1:]
detector = Detector(profile)
records = [r for r in read_records(source) if r.text.strip()]
nlp = get_nlp()
counts = Counter()
examples = {}
for record, doc in zip(records, nlp.pipe((r.text for r in records), batch_size=64)):
    known = detector.detect(record.text)
    for ent in doc.ents:
        if ent.label_ not in {'PERSON', 'ORG'} or ent.text.lower() in _NAME_BLOCKLIST:
            continue
        if any(s.start <= ent.start_char and s.end >= ent.end_char for s in known):
            continue
        key = (ent.label_, ent.text)
        counts[key] += 1
        examples[key] = record.id + ': ' + record.text[:350]
for (label, value), count in counts.most_common():
    if len(value) > 2:
        print(json.dumps({'label': label, 'text': value, 'count': count, 'context': examples[label, value]}, ensure_ascii=True))
