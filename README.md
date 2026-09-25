# PII Redaction Tool — README

## What this is

A Python tool that reads a `.docx` file, finds personally identifiable
information, and replaces it with realistic-looking **fake** values (the
same fake value every time a given real value repeats), producing a
redacted `.docx`. Built and tested against the attached *Red Herring
Prospectus* (KSH International Limited's IPO prospectus — a real, public
SEBI filing that contains real promoter/director names, company names,
emails, phone numbers and addresses).

```
python redact_pii.py Red_Herring_Prospectus.docx Red_Herring_Prospectus_REDACTED.docx --log audit_log.csv
```

## Approach: regex + spaCy NER, hybrid

- **Structured PII** (email, phone, SSN, credit card, IP address, and
  contextual date-of-birth) is detected with **regex**. These have a
  reliable shape, so regex gives high precision and recall with no
  dependencies. Credit card numbers are additionally checked with a Luhn
  checksum to cut down on false positives from random 13–19 digit runs.
- **Unstructured PII** (person names, company names, addresses) is
  detected with **spaCy's `en_core_web_sm`** NER model (PERSON / ORG /
  GPE-LOC-FAC), plus a small regex safety net for company legal suffixes
  (Ltd, LLP, Private Limited, Bank, Trust, etc.) that catches repeat/
  abbreviated mentions spaCy's NER sometimes misses.
- A **consistent fake-value mapper** (built on `Faker`, seeded
  deterministically per input string) makes sure "Rashi Patil" maps to
  the same fake name everywhere in the document, matching the style of
  the assignment's own example.
- Detections are merged (overlap resolution + adjacent-span merging, e.g.
  joining a street address with a trailing "..., Maharashtra, India")
  before being applied to the `.docx` paragraph by paragraph, including
  paragraphs nested in tables, and document headers/footers.

### Why this hybrid, and not pure regex / pure NER / Presidio?

Pure regex can't find names, company names, or addresses — those don't
have a fixed shape. Pure NER (no regex) is unreliable for
emails/phones/SSNs/credit cards/IPs, which are exactly the categories
regex is *best* at. Presidio (Microsoft's PII library) would have been a
reasonable choice too — it's essentially this same regex+NER architecture
packaged as a library — but building it directly kept the dependency
footprint small and made every design decision (and its tradeoffs)
visible and explainable, which matters for a document type (Indian legal/
financial prose) that off-the-shelf recognizers aren't tuned for anyway.

## Known tradeoffs and false positives/negatives

This is the most important section — see `evaluation/report.md` for the
numbers behind these claims.

1. **Order/ticket/invoice/reference numbers are deliberately NOT treated
   as phone numbers or PII**, even though some are 10 digits and could
   look like an Indian mobile number. We check the ~25 characters before
   a phone-shaped number for words like "Order", "Ticket", "Invoice",
   "Reference", "Account" and skip if found. This is an explicit choice
   in line with the assignment's own framing ("reasonable either way,
   just be explicit").

2. **Legal "Defined Terms" in prospectuses are the single biggest source
   of false positives.** Indian IPO prospectuses capitalize generic terms
   as a legal convention — "the Promoter Selling Shareholders", "Bids",
   "Registrar", "Net Proceeds", "Bid/Offer Period" — and a generic English
   NER model tags many of these as ORG/PERSON because they *look* like
   proper nouns. We built a blocklist of ~50 such terms found during
   testing, and two structural filters (skip determiner-led phrases like
   "the X"; skip single-word ORG matches), which cut real-document
   false-positive company/person tags by roughly 60%. This blocklist is
   inherently incomplete — a document from a different domain (medical
   records, retail tickets) would need its own list. **This is the
   single most impactful thing to extend if reusing this tool elsewhere.**

3. **ALL-CAPS text** (cover pages, headers) is much harder for spaCy's
   tagger than normally-cased text. We title-case a copy of the text
   before tagging when a paragraph is mostly uppercase (offsets stay
   aligned since `.title()` preserves string length), which recovered
   most — not all — of the names spaCy otherwise missed entirely in
   ALL-CAPS runs.

4. **Multi-word names occasionally lose their first token** (e.g. "Sanjay
   Kumar Mehta" detected as just "Kumar Mehta"). This is a limitation of
   the small spaCy model itself (`en_core_web_sm`); a larger model
   (`en_core_web_trf`) would likely do better at the cost of a much
   heavier dependency. This means a small amount of a name occasionally
   survives redaction even when "most" of it is caught — noted as a
   residual risk, not something we consider solved.

5. **Non-Indian address formats get partial coverage.** Address detection
   is anchored on Indian 6-digit PIN codes and Indian-English
   address-introducing phrases ("registered office", "residing at"); a UK
   postcode or US ZIP+4 format address is only caught via spaCy's GPE/LOC
   tags, which is less reliable and was the weakest category in testing.

6. **Entities are sometimes redacted under the "wrong" category label**
   (e.g. a person's name tagged COMPANY by spaCy, or vice versa). The
   *value* still gets redacted correctly in these cases — it's a labeling
   accuracy issue, not a privacy leak — but it means the per-category
   counts in the audit log slightly understate/overstate true category
   volume.

7. We chose **not** to redact company registration identifiers like CIN
   numbers (`L65190GJ1994PLC021012`) or generic government scheme names
   (`Pradhan Mantri Awas Yojana`) — they aren't in the assignment's list
   of categories, and they're public registry/government identifiers
   rather than personal information.

## Code structure

```
pii_redactor/
  detectors.py        # every individual PII detector (regex + spaCy)
  fake_map.py          # consistent original -> fake value mapping (Faker)
  redact.py             # merges detector output, applies replacements
  docx_redactor.py     # walks a .docx (incl. tables/headers/footers), redacts
  evaluate.py           # precision/recall/F1 harness
  test_data/
    labeled_examples.py    # dev set (used while building the detectors)
    holdout_examples.py    # held-out set (written after tuning, untouched since)
redact_pii.py           # CLI entry point
```

### Extending to a new PII type

1. Write a `detect_xxx(text) -> List[Span]` function in `detectors.py`
   (see any existing one for the `Span(start, end, label, text)` shape).
2. Register it in `REGEX_DETECTORS` (regex-based) or fold it into
   `run_ner` (NER-based), and add its label to `PRIORITY` in
   `detectors.py` (position determines who wins on overlap) and to
   `ALL_LABELS`.
3. Add a case in `FakeMapper.get()` in `fake_map.py` for the new label's
   fake-value generator.
4. Add a few labeled examples to `test_data/labeled_examples.py` (and,
   ideally, some to `holdout_examples.py` you don't look at again) and
   re-run `python -m pii_redactor.evaluate`.

No other file needs to change — `redact.py`, `docx_redactor.py`, and the
CLI are all generic over whatever's in `REGEX_DETECTORS`/`run_ner`.

## Files in this delivery

- `redact_pii.py`, `pii_redactor/` — source code
- `Red_Herring_Prospectus_REDACTED.docx` — the redacted output
- `audit_log.csv` — every redaction made (label, original, fake value)
- `README.md` — this file
- `evaluation/report.md` — accuracy/precision/recall numbers and methodology

## Streamlit UI

A basic web UI is included in `app.py`. Run it locally with:

```
pip install -r requirements.txt
streamlit run app.py
```

Upload a `.docx`, click **Redact PII**, and download the redacted file plus
a CSV audit log. It's a thin wrapper around the same `redact_docx()` /
`FakeMapper` used by `redact_pii.py` — no detection/redaction logic lives
in the UI itself.

## Deploying on Render

This repo includes `render.yaml`, so the fastest path is a Blueprint deploy:

1. Push this folder to a GitHub (or GitLab) repo.
2. In the Render dashboard: **New** → **Blueprint**, point it at the repo.
   Render will read `render.yaml` and set everything up automatically —
   build command (`pip install -r requirements.txt`), start command
   (`streamlit run app.py --server.port $PORT --server.address 0.0.0.0
   --server.headless true`), and the Python version.
3. Click **Apply**. First build takes a few minutes (spaCy + its model are
   the slow part). Once it's live, Render gives you a `https://<name>.onrender.com` URL.

**No `render.yaml`? Manual setup instead:**
- New → Web Service → connect your repo
- Runtime: `Python 3`
- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`

**Notes:**
- On Render's **free plan**, the service spins down after 15 minutes of
  no traffic and takes ~30-60s to wake back up on the next request —
  expected, not a bug.
- `.streamlit/config.toml` caps uploads at 50MB (`maxUploadSize`) and
  disables CORS/XSRF checks and usage-stat collection, which is the usual
  setup for a single-purpose hosted Streamlit app. Raise `maxUploadSize`
  there if you need to handle larger `.docx` files.
- Nothing in `app.py` or `pii_redactor/` changes between local and Render
  use — it's the same code path as running `streamlit run app.py` on your
  own machine.

