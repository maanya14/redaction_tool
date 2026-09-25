# PII Redaction Tool — README

## What this is

A Python tool that reads a `.docx` file, finds personally identifiable
information, and replaces it with realistic-looking **fake** values — the
same fake value every time a real one repeats — producing a redacted
`.docx`. It was built and tested against the attached *Red Herring
Prospectus* (KSH International Limited's IPO prospectus, a real, public
SEBI filing containing real promoter/director names, company names,
emails, phone numbers and addresses).

```
python redact_pii.py Red_Herring_Prospectus.docx Red_Herring_Prospectus_REDACTED.docx --log audit_log.csv
```

## Approach: regex + spaCy NER, hybrid

- **Structured PII** (email, phone, SSN, credit card, IP address, and
  contextual date-of-birth) is detected with **regex**. These fields have
  a predictable shape, so regex gives high precision and recall with no
  extra dependencies. Credit card numbers get an additional Luhn-checksum
  check to filter out random 13–19 digit runs.
- **Unstructured PII** (person names, company names, addresses) is
  detected with **spaCy's `en_core_web_sm`** NER model (PERSON / ORG /
  GPE-LOC-FAC), backed by a small regex safety net for company legal
  suffixes (Ltd, LLP, Private Limited, Bank, Trust, etc.) that catches
  repeat or abbreviated mentions the NER model sometimes misses.
- A **consistent fake-value mapper**, built on `Faker` and seeded
  deterministically per input string, makes sure "Rashi Patil" maps to
  the same fake name everywhere in the document, matching the style of
  the assignment's own example.
- Detections are merged (overlap resolution, plus joining adjacent spans
  like a street address with a trailing "..., Maharashtra, India")
  before being applied paragraph by paragraph, including text inside
  tables and document headers/footers.

**Why this hybrid, and not pure regex, pure NER, or Presidio?** Pure
regex can't find names, companies, or addresses — those don't have a
fixed shape. Pure NER is unreliable for emails, phones, SSNs, credit
cards and IPs, which is exactly where regex excels. Presidio would have
been a reasonable choice too — it's essentially this same regex+NER
architecture packaged as a library — but building it directly kept the
dependency footprint small and made every design decision (and its
tradeoffs) visible, which matters for a document type that off-the-shelf
recognizers aren't tuned for anyway.

## Known tradeoffs and false positives/negatives

See `evaluation/report.md` for the numbers behind these claims.

1. **Order/ticket/invoice/reference numbers are deliberately not treated
   as phone numbers**, even though some are 10 digits and could look
   like an Indian mobile number. We check the ~25 characters before a
   phone-shaped number for words like "Order", "Ticket", "Invoice",
   "Reference" or "Account" and skip it if found — an explicit choice in
   line with the assignment's own framing.
2. **Legal "Defined Terms" are the biggest source of false positives.**
   Indian IPO prospectuses capitalize generic terms as a legal
   convention ("the Promoter Selling Shareholders", "Bids", "Net
   Proceeds"), and a generic NER model tags many of these as ORG/PERSON
   because they look like proper nouns. A blocklist of ~50 such terms
   found during testing, plus two structural filters (skip determiner-led
   phrases like "the X"; skip single-word ORG matches), cut real false
   positives by roughly 60%. This blocklist is inherently incomplete —
   the single most impactful thing to extend if reusing this tool
   elsewhere.
3. **ALL-CAPS text** (cover pages, headers) is much harder for spaCy to
   tag than normally-cased text. We title-case a copy of the text before
   tagging when a paragraph is mostly uppercase (offsets stay aligned
   since `.title()` preserves string length), which recovers most, but
   not all, of the names spaCy would otherwise miss.
4. **Multi-word names occasionally lose their first token** (e.g.
   "Sanjay Kumar Mehta" detected as just "Kumar Mehta"). This is a
   limitation of the small spaCy model; a larger model like
   `en_core_web_trf` would likely do better, at the cost of a much
   heavier dependency. A small amount of a name can survive redaction
   even when most of it is caught — a residual risk, not something we
   consider fully solved.
5. **Non-Indian address formats get partial coverage.** Address
   detection is anchored on Indian 6-digit PIN codes and Indian-English
   phrases ("registered office", "residing at"); a UK postcode or US
   ZIP+4 address is only caught via spaCy's GPE/LOC tags, which was the
   weakest category in testing.
6. **Entities sometimes get redacted under the "wrong" label** (e.g. a
   person's name tagged COMPANY, or vice versa). The value still gets
   redacted correctly — it's a labeling issue, not a privacy leak — but
   it means per-category counts in the audit log can slightly over- or
   understate true volume.
7. We chose **not** to redact company registration identifiers like CIN
   numbers or generic government scheme names — they're outside the
   assignment's category list, and they're public registry/government
   identifiers rather than personal information.

## Code structure

```
pii_redactor/
  detectors.py        # every individual PII detector (regex + spaCy)
  fake_map.py          # consistent original -> fake value mapping (Faker)
  redact.py             # merges detector output, applies replacements
  docx_redactor.py     # walks a .docx (incl. tables/headers/footers), redacts
  evaluate.py           # precision/recall/F1 harness
  test_data/
    labeled_examples.py    # examples used while building and scoring the detectors
redact_pii.py           # CLI entry point
```

### Extending to a new PII type

1. Write a `detect_xxx(text) -> List[Span]` function in `detectors.py`
   (see any existing one for the `Span(start, end, label, text)` shape).
2. Register it in `REGEX_DETECTORS` (regex-based) or fold it into
   `run_ner` (NER-based), and add its label to `PRIORITY` (position
   decides who wins on overlap) and to `ALL_LABELS`.
3. Add a case in `FakeMapper.get()` for the new label's fake-value
   generator.
4. Add a few labeled examples to `test_data/labeled_examples.py` and
   re-run `python -m pii_redactor.evaluate`.

Nothing else needs to change — `redact.py`, `docx_redactor.py` and the
CLI are all generic over whatever's registered in
`REGEX_DETECTORS`/`run_ner`.

