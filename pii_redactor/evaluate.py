"""Reproducible exact-span evaluation on the ORIGINAL supplied DOCX only."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import re

from .detectors import ALL_LABELS
from .docx_redactor import read_records
from .redact import Detector
from .test_data.labeled_examples import SAMPLES, RANDOM_SAMPLES


def build_corpus(source):
    records = {int(r.id.split(':p')[1]): r for r in read_records(source)
               if r.id.startswith('word/document.xml:')}
    corpus = []
    for group, examples in [('targeted_regression', SAMPLES), ('random_source_sample', RANDOM_SAMPLES)]:
        for first, last, annotations in examples:
            text = '\n'.join(records[i].text for i in range(first, last + 1))
            spans = []
            for label, phrase in annotations:
                if phrase == '*':
                    start = len(text) - len(text.lstrip())
                    spans.append({'label': label, 'start': start, 'end': len(text.rstrip()), 'text': text.strip()})
                    continue
                pattern = r'(?<!\w)' + r'\s+'.join(map(re.escape, phrase.split())) + r'(?!\w)'
                matches = list(re.finditer(pattern, text, re.I))
                if not matches:
                    raise ValueError(f'Annotation absent from original paragraph {first}: {phrase}')
                spans.extend({'label': label, 'start': m.start(), 'end': m.end(), 'text': m.group()} for m in matches)
            spans.sort(key=lambda s: s['start'])
            if any(a['end'] > b['start'] for a, b in zip(spans, spans[1:])):
                raise ValueError(f'Overlapping annotations in {first}')
            corpus.append({'id': f'word/document.xml:p{first}-p{last}', 'group': group,
                           'text': text, 'spans': spans})
    return corpus


def measure(corpus, detector):
    counts = {label: Counter(tp=0, fp=0, fn=0) for label in ALL_LABELS}
    errors, exact = [], 0
    for example in corpus:
        gold = {(s['label'], s['start'], s['end']) for s in example['spans']}
        found = detector.detect(example['text'])
        predictions = {(s.label, s.start, s.end) for s in found}
        exact += predictions == gold
        for label, _, _ in predictions & gold:
            counts[label]['tp'] += 1
        for label, _, _ in predictions - gold:
            counts[label]['fp'] += 1
        for label, _, _ in gold - predictions:
            counts[label]['fn'] += 1
        if predictions != gold:
            errors.append({'id': example['id'], 'false_positives': sorted(predictions - gold),
                           'false_negatives': sorted(gold - predictions)})
    total = Counter()
    for c in counts.values():
        total.update(c)
    return {'counts': counts, 'overall': metrics(total), 'passage_accuracy': exact / len(corpus),
            'exact_passages': exact, 'passages': len(corpus), 'errors': errors}


def metrics(c):
    tp, fp, fn = c['tp'], c['fp'], c['fn']
    return {**c, 'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def pct(number):
    return 'N/A' if number is None else f'{number:.2%}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='The original prospectus DOCX')
    parser.add_argument('--profile', default='profiles/prospectus.json')
    parser.add_argument('--output-dir', default='evaluation')
    parser.add_argument('--compare-generic', action='store_true')
    args = parser.parse_args()
    detector = Detector(args.profile)
    source_hash = hashlib.sha256(Path(args.source).read_bytes()).hexdigest()
    if source_hash != detector.profile['source_sha256']:
        parser.error('Source hash does not match the reviewed profile.')
    corpus = build_corpus(args.source)
    result = {'source_file': Path(args.source).name, 'source_sha256': source_hash,
              'profile_sha256': hashlib.sha256(Path(args.profile).read_bytes()).hexdigest(),
              'annotation_author': 'Coding assistant, reviewed against original text; no independent human adjudication',
              'assisted': measure(corpus, detector)}
    for group in ['targeted_regression', 'random_source_sample']:
        result[group] = measure([x for x in corpus if x['group'] == group], detector)
    if args.compare_generic:
        result['generic'] = measure(corpus, Detector())
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'source_annotations.json').write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'metrics.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    main_result = result['assisted']
    lines = ['# Evaluation report — original prospectus only', '',
             '## Scope and provenance', '',
             f'Input: `{Path(args.source).name}`. SHA-256: `{source_hash}`.', '',
             f'Evaluated {len(corpus)} passages copied verbatim from the supplied DOCX. '
             'No synthetic sentences or invented PII were used. Exact text, paragraph IDs and manually assigned character spans '
             'are saved in `source_annotations.json`. Annotations were made by the coding assistant and have not been independently human-adjudicated.', '',
             'The delivered DOCX uses an explicitly selected, source-reviewed entity profile plus automatic structured detectors. '
             'The profile and targeted passages were reviewed during development. These are document-specific regression results, '
             'NOT independent holdout or generalization results. The profile is never loaded from evaluation annotations.', '',
             'Twenty additional passages were selected by seeded random sampling (20260926) from body paragraphs 351–3999 '
             'with more than 30 text characters, then annotated from the original. This small sample mostly contains negatives '
             'and is not a statistically representative estimate of whole-document recall.', '',
             '## Label policy and scoring', '',
             'Label actual people, named businesses/trusts, email addresses, phone numbers and complete mailing addresses. '
             'Named exchanges/depositories are companies. Do not label generic roles/headings, legislation, regulators, '
             'government schemes, newspaper titles, registration/DIN/reference numbers, filing dates, websites or standalone place names. '
             'Company/person names inside a complete postal address are included in the ADDRESS span, without nested labels.', '',
             'A true positive requires the EXACT label, start and end offsets. Partial names/addresses count as both a false positive '
             'and a false negative. Precision = TP/(TP+FP); recall = TP/(TP+FN); F1 = 2TP/(2TP+FP+FN). '
             'Accuracy is explicitly **exact-passage accuracy**: passages with every gold span found and no extra spans, divided by all passages. '
             'No artificial true-negative entity count is invented.', '',
             '## Measured results: assisted delivery configuration', '',
             '| Category | TP | FP | FN | Precision | Recall | F1 |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for label in ALL_LABELS:
        m = metrics(main_result['counts'][label])
        lines.append(f"| {label} | {m['tp']} | {m['fp']} | {m['fn']} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} |")
    m = main_result['overall']
    lines += [f"| Overall | {m['tp']} | {m['fp']} | {m['fn']} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} |", '',
              f"Exact-passage accuracy: **{pct(main_result['passage_accuracy'])}** ({main_result['exact_passages']}/{len(corpus)} passages).", '',
              'SSNs, credit cards, dates of birth and IP addresses have no positive examples in this annotated source sample. '
              'Their recall is **N/A / untested**, not 100%. The code retains detectors for them, but this document cannot establish their detection quality.', '',
              '| Sample | Passages | Precision | Recall | Exact-passage accuracy |',
              '|---|---:|---:|---:|---:|']
    for key in ['targeted_regression', 'random_source_sample']:
        r = result[key]
        lines.append(f"| {key} | {r['passages']} | {pct(r['overall']['precision'])} | {pct(r['overall']['recall'])} | {pct(r['passage_accuracy'])} |")
    if 'generic' in result:
        r = result['generic']
        lines += ['', '## Automatic hybrid configuration (no reviewed profile)', '',
                  f"Same real passages: precision **{pct(r['overall']['precision'])}**, recall **{pct(r['overall']['recall'])}**, "
                  f"F1 **{pct(r['overall']['f1'])}**, exact-passage accuracy **{pct(r['passage_accuracy'])}**.", '',
                  'This comparison shows the effect of document review; assisted scores must not be presented as unassisted model accuracy.']
    lines += ['', '## Limits', '',
              '- These are measured results on an annotated subset, not proof of complete redaction across the entire prospectus.',
              '- The source-specific profile is reviewed configuration; new documents require fresh review or generic mode and QA.',
              '- Images/logos/QR pixels are preserved and not OCR-redacted. Website URLs and company registration identifiers are outside the stated nine-category text policy.',
              '- Fake values are required by the assignment; only evaluation input and labels come from original text.',
              '- Complete errors and counts are in `metrics.json`. End-to-end package checks are recorded separately in `verification.json`.', '',
              '## Reproduce', '', '```powershell',
              'python -m pii_redactor.evaluate "C:\\path\\Red Herring Prospectus.docx" --profile profiles/prospectus.json --compare-generic', '```', '']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: v['overall'] for k, v in result.items() if isinstance(v, dict) and 'overall' in v}, indent=2))


if __name__ == '__main__':
    main()
