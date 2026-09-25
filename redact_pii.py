#!/usr/bin/env python3
import argparse
import csv
import sys
import hashlib
from pathlib import Path

from pii_redactor import redact_docx


def main():
    parser = argparse.ArgumentParser(description="Redact PII from a .docx file.")
    parser.add_argument("input", help="Path to the source .docx file")
    parser.add_argument("output", help="Path to write the redacted .docx file")
    parser.add_argument("--log", help="Optional path to write a CSV audit log of every redaction", default=None)
    parser.add_argument("--seed", type=int, default=42, help="Random seed for fake-value generation")
    parser.add_argument('--profile', help='Optional source-verified entity profile for this specific document')
    parser.add_argument('--include-originals', action='store_true', help='Include sensitive originals in the private audit CSV')
    args = parser.parse_args()

    from pii_redactor.fake_map import FakeMapper
    from pii_redactor.redact import Detector
    detector = Detector(args.profile)
    if detector.profile:
        actual = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
        if actual != detector.profile['source_sha256']:
            parser.error('The reviewed profile belongs to a different source document.')
    mapper = FakeMapper(seed=args.seed, aliases=detector.aliases)

    print(f"Reading {args.input} ...")
    mapper, log = redact_docx(args.input, args.output, mapper=mapper, detector=detector)
    print(f"Wrote redacted document to {args.output}")
    print(f"Total redactions made: {len(log)}")

    counts = {}
    for row in log:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    for label, count in sorted(counts.items()):
        print(f"  {label:15s} {count}")

    if args.log:
        if Path(args.log).resolve() in {Path(args.input).resolve(), Path(args.output).resolve()}:
            parser.error('Audit log must not overwrite a document.')
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        with open(args.log, "w", newline="", encoding="utf-8") as f:
            fields = ['part', 'paragraph', 'start', 'end', 'label', 'fake']
            if args.include_originals:
                fields.append('original')
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(log)
        print(f"Audit log written to {args.log}")


if __name__ == "__main__":
    sys.exit(main())
