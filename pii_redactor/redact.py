import re
import json
from pathlib import Path
from typing import List

from .detectors import (
    Span, PRIORITY, REGEX_DETECTORS, run_ner,
)
from .fake_map import FakeMapper


def _resolve_overlaps(spans: List[Span]) -> List[Span]:
    """Greedy interval scheduling: sort by priority then length (longer /
    more specific spans win), keep a span only if it doesn't overlap
    anything already accepted."""
    def sort_key(s: Span):
        return (PRIORITY.index(s.label), -(s.end - s.start), s.start)

    accepted: List[Span] = []
    for span in sorted(spans, key=sort_key):
        if not any(span.start < a.end and a.start < span.end for a in accepted):
            accepted.append(span)
    return sorted(accepted, key=lambda s: s.start)


def _merge_adjacent(text: str, spans: List[Span]) -> List[Span]:
    """Merge same-label spans that are only separated by punctuation/
    whitespace (e.g. an ADDRESS regex hit for the street+PIN followed by
    a separate spaCy GPE hit for the trailing ", Maharashtra, India") so
    we redact one clean block instead of leaving fragments in between."""
    if not spans:
        return spans
    # ADDRESS spans are allowed a slightly wider gap (e.g. one extra plain
    # word like "Maharashtra" between two GPE hits) than PERSON/COMPANY.
    gap_patterns = {
        "ADDRESS": re.compile(r"[\s,\-]{0,3}(?:[A-Za-z0-9]{1,20}[\s,\-]{1,3}){0,3}"),
        "PERSON": re.compile(r"[\s\-]{0,3}"),  # no comma: avoid merging two distinct people in a list
        "COMPANY": re.compile(r"[\s,\-]{0,3}"),
    }

    merged = [spans[0]]
    for span in spans[1:]:
        prev = merged[-1]
        gap = text[prev.end:span.start]
        pattern = gap_patterns.get(span.label)
        if span.label == prev.label and pattern and pattern.fullmatch(gap):
            merged[-1] = Span(prev.start, span.end, prev.label, text[prev.start:span.end])
        else:
            merged.append(span)
    return merged


def detect_all(text: str) -> List[Span]:
    spans: List[Span] = []
    for detector in REGEX_DETECTORS:
        spans.extend(detector(text))
    spans.extend(run_ner(text))
    resolved = _resolve_overlaps(spans)
    return _merge_adjacent(text, resolved)


class Detector:
    """Generic hybrid detection, or explicitly selected reviewed-document mode.

    In reviewed mode, named entities/addresses come from a source-verified
    catalog. Structured detectors remain automatic. This is assisted redaction,
    not a claim that the model learned these names or generalizes to other files.
    """
    def __init__(self, profile=None):
        self.profile = json.loads(Path(profile).read_text(encoding='utf-8')) if profile else None
        self.aliases = {}
        self.patterns = []
        if self.profile:
            from .fake_map import normalize
            for entry in self.profile['entities']:
                aliases = [entry['canonical'], *entry.get('aliases', [])]
                for alias in aliases:
                    self.aliases[normalize(alias)] = normalize(entry['canonical'])
                    pattern = r'(?<!\w)' + r'\s+'.join(re.escape(w) for w in alias.split()) + r'(?!\w)'
                    self.patterns.append((re.compile(pattern, re.IGNORECASE), entry['label']))

    def detect(self, text):
        if not text.strip():
            return []
        candidates = []
        if self.profile:
            from .detectors import detect_email, detect_phone, detect_ssn, detect_credit_card, detect_ip, detect_date_of_birth
            for detector in (detect_email, detect_phone, detect_ssn, detect_credit_card, detect_ip, detect_date_of_birth):
                candidates.extend(detector(text))
            urls = [(m.start(), m.end()) for m in re.finditer(r'(?:https?://|www\.)[^\s<>]+', text, re.I)]
            for pattern, label in self.patterns:
                candidates.extend(Span(m.start(), m.end(), label, m.group()) for m in pattern.finditer(text)
                                  if not any(m.start() < end and start < m.end() for start, end in urls))
            # A reviewed whole address wins over company/person names within it;
            # adjacent companies or people remain distinct entities.
            return _resolve_overlaps(candidates)
        offset = 0
        for line in text.splitlines(keepends=True):
            candidates.extend(Span(s.start + offset, s.end + offset, s.label, s.text) for s in detect_all(line))
            offset += len(line)
        return _resolve_overlaps(candidates)

    def redact(self, text, mapper):
        for span in reversed(self.detect(text)):
            text = text[:span.start] + mapper.get(span.label, span.text) + text[span.end:]
        return text


def redact_text(text: str, mapper: FakeMapper):
    """Return (redacted_text, spans_found) for one string of text."""
    if not text or not text.strip():
        return text, []

    spans = detect_all(text)
    if not spans:
        return text, []

    out = []
    cursor = 0
    for span in spans:
        out.append(text[cursor:span.start])
        out.append(mapper.get(span.label, span.text))
        cursor = span.end
    out.append(text[cursor:])
    return "".join(out), spans
