# Evaluation report — original prospectus only

## Scope and provenance

Input: `Red Herring Prospectus.docx`. SHA-256: `8b5c93f7642d659e64b51be9f6172c86c2825417f376ca1800ed331515e6f929`.

Evaluated 108 passages copied verbatim from the supplied DOCX. No synthetic sentences or invented PII were used. Exact text, paragraph IDs and manually assigned character spans are saved in `source_annotations.json`. Annotations were made by the coding assistant and have not been independently human-adjudicated.

The delivered DOCX uses an explicitly selected, source-reviewed entity profile plus automatic structured detectors. The profile and targeted passages were reviewed during development. These are document-specific regression results, NOT independent holdout or generalization results. The profile is never loaded from evaluation annotations.

Twenty additional passages were selected by seeded random sampling (20260926) from body paragraphs 351–3999 with more than 30 text characters, then annotated from the original. This small sample mostly contains negatives and is not a statistically representative estimate of whole-document recall.

## Label policy and scoring

Label actual people, named businesses/trusts, email addresses, phone numbers and complete mailing addresses. Named exchanges/depositories are companies. Do not label generic roles/headings, legislation, regulators, government schemes, newspaper titles, registration/DIN/reference numbers, filing dates, websites or standalone place names. Company/person names inside a complete postal address are included in the ADDRESS span, without nested labels.

A true positive requires the EXACT label, start and end offsets. Partial names/addresses count as both a false positive and a false negative. Precision = TP/(TP+FP); recall = TP/(TP+FN); F1 = 2TP/(2TP+FP+FN). Accuracy is explicitly **exact-passage accuracy**: passages with every gold span found and no extra spans, divided by all passages. No artificial true-negative entity count is invented.

## Measured results: assisted delivery configuration

| Category | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| PERSON | 53 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| EMAIL | 13 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| PHONE | 18 | 0 | 1 | 100.00% | 94.74% | 97.30% |
| COMPANY | 33 | 1 | 0 | 97.06% | 100.00% | 98.51% |
| ADDRESS | 29 | 0 | 0 | 100.00% | 100.00% | 100.00% |
| SSN | 0 | 0 | 0 | N/A | N/A | N/A |
| CREDIT_CARD | 0 | 0 | 0 | N/A | N/A | N/A |
| DATE_OF_BIRTH | 0 | 0 | 0 | N/A | N/A | N/A |
| IP_ADDRESS | 0 | 0 | 0 | N/A | N/A | N/A |
| Overall | 146 | 1 | 1 | 99.32% | 99.32% | 99.32% |

Exact-passage accuracy: **98.15%** (106/108 passages).

SSNs, credit cards, dates of birth and IP addresses have no positive examples in this annotated source sample. Their recall is **N/A / untested**, not 100%. The code retains detectors for them, but this document cannot establish their detection quality.

| Sample | Passages | Precision | Recall | Exact-passage accuracy |
|---|---:|---:|---:|---:|
| targeted_regression | 88 | 99.32% | 99.32% | 97.73% |
| random_source_sample | 20 | 100.00% | 100.00% | 100.00% |

## Automatic hybrid configuration (no reviewed profile)

Same real passages: precision **52.53%**, recall **56.46%**, F1 **54.43%**, exact-passage accuracy **47.22%**.

This comparison shows the effect of document review; assisted scores must not be presented as unassisted model accuracy.

## Limits

- These are measured results on an annotated subset, not proof of complete redaction across the entire prospectus.
- The source-specific profile is reviewed configuration; new documents require fresh review or generic mode and QA.
- Images/logos/QR pixels are preserved and not OCR-redacted. Website URLs and company registration identifiers are outside the stated nine-category text policy.
- Fake values are required by the assignment; only evaluation input and labels come from original text.
- Complete errors and counts are in `metrics.json`. End-to-end package checks are recorded separately in `verification.json`.

## Reproduce

```powershell
python -m pii_redactor.evaluate "C:\path\Red Herring Prospectus.docx" --profile profiles/prospectus.json --compare-generic
```
