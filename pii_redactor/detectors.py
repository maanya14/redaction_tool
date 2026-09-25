import re
import ipaddress
from dataclasses import dataclass
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Span type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str
    text: str

    def __len__(self):
        return self.end - self.start


# ---------------------------------------------------------------------------
# Priority: when two spans overlap, the detector earlier in this list wins.
# Structured / high-precision regex types outrank the fuzzier NER types.
# ---------------------------------------------------------------------------
PRIORITY = [
    "EMAIL",
    "IP_ADDRESS",
    "SSN",
    "CREDIT_CARD",
    "PHONE",
    "DATE_OF_BIRTH",
    "ADDRESS",
    "COMPANY",
    "PERSON",
]


# ---------------------------------------------------------------------------
# Regex-based detectors (emails, phones, SSNs, credit cards, IPs, DOB)
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# IPv4: 4 octets 0-255, word-bounded so it doesn't match version numbers
# embedded in longer digit runs.
_OCTET = r"(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
IPV4_RE = re.compile(rf"\b{_OCTET}\.{_OCTET}\.{_OCTET}\.{_OCTET}\b")

# IPv6 (simplified, covers the common fully/partially-compressed forms)
IPV6_RE = re.compile(
    r"\b(?:[A-Fa-f0-9]{1,4}:){2,7}(?:[A-Fa-f0-9]{1,4}|:)\b"
)

# US Social Security Number: NNN-NN-NNNN (also accepts a space variant,
# since that's a common typo/format seen in scanned forms).
SSN_RE = re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b")

# Credit card: 13-19 digits, optionally grouped in 4s with space/dash.
CREDIT_CARD_RE = re.compile(
    r"\b\d(?:[ -]?\d){12,18}\b"
)

# Phone numbers:
#  - Indian mobile: optional +91 / 0 prefix, then 10 digits starting 6-9,
#    optionally split 5+5 or with a space/dash.
#  - Generic international / US style: (XXX) XXX-XXXX, XXX-XXX-XXXX,
#    +<country code> <national number>, etc.
PHONE_RE = re.compile(
    r"""
    (?<!\d)(?:
        (?:\+?91[-\s]?)?[6-9]\d{4}[-\s]?\d{5}                # Indian mobile
        |
        \+\d{1,3}[-.\s]?\(?\d{2,4}\)?(?:[-.\s]?\d{2,4}){2,4} # generic intl
        |
        \(\d{3}\)[-.\s]?\d{3}[-.\s]?\d{4}                    # (NNN) NNN-NNNN
        |
        \d{3}[-.\s]\d{3}[-.\s]\d{4}                          # NNN-NNN-NNNN
    )(?!\d)
    """,
    re.VERBOSE,
)

# Date-of-birth: only redact a date if it is near a DOB-style keyword, so we
# don't nuke every date in the document (filing dates, board-meeting dates,
# incorporation dates, etc. are not PII).
DOB_KEYWORD_RE = re.compile(
    r"\b(?:date of birth|d\.?o\.?b\.?|born on)\b\s*[:\-]?\s*",
    re.IGNORECASE,
)
DATE_VALUE_RE = re.compile(
    r"""
    (?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})                 # 12/05/1990
    |
    (?:\d{1,2}\s+(?:January|February|March|April|May|June|July|August|
        September|October|November|December)\s+\d{4})    # 12 May 1990
    |
    (?:(?:January|February|March|April|May|June|July|August|
        September|October|November|December)\s+\d{1,2},?\s+\d{4})  # May 12, 1990
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Indian PIN code, used as an anchor for address detection.
PIN_CODE_RE = re.compile(r"\b\d{3}\s?\d{3}\b")

# Anchored so it only walks back through consecutive Title-Case (or "&")
# tokens immediately before the suffix - it stops at the first lowercase
# word, so it can't swallow "...was raised by Waterloo Industries Ltd"
# down to "The invoice was raised by ...".
COMPANY_SUFFIX_RE = re.compile(
    r"""
    \b(?:(?:[A-Z][A-Za-z0-9.\-]*|&)\s+){1,6}
    (?:Private\ Limited|Pvt\.?\ Ltd\.?|Limited|Ltd\.?|LLP|LLC|Inc\.?|
       Corporation|Corp\.?|Trust|Bank|Securities(?:\ Limited)?|Capital|
       Chartered\ Accountants)\b
    """,
    re.VERBOSE,
)


def detect_email(text: str) -> List[Span]:
    return [Span(m.start(), m.end(), "EMAIL", m.group()) for m in EMAIL_RE.finditer(text)]


def detect_ip(text: str) -> List[Span]:
    spans = [Span(m.start(), m.end(), "IP_ADDRESS", m.group()) for m in IPV4_RE.finditer(text)]
    for match in re.finditer(r'(?<![\w:])[0-9a-fA-F:]*:[0-9a-fA-F:]+(?![\w:])', text):
        try:
            ipaddress.IPv6Address(match.group())
        except ValueError:
            continue
        spans.append(Span(match.start(), match.end(), 'IP_ADDRESS', match.group()))
    return spans


def detect_ssn(text: str) -> List[Span]:
    return [Span(m.start(), m.end(), "SSN", m.group()) for m in SSN_RE.finditer(text)]


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def detect_credit_card(text: str) -> List[Span]:
    spans = []
    for m in CREDIT_CARD_RE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            spans.append(Span(m.start(), m.end(), "CREDIT_CARD", m.group()))
    return spans


# Plain 10-digit numbers preceded by one of these words are almost always
# an identifier (order/ticket/invoice/reference/account number), not a
# phone number. This is a precision/recall trade-off we make explicitly
# (see README): we choose NOT to treat bare order/ticket numbers as PII.
_NON_PHONE_CONTEXT_RE = re.compile(
    r"(order|ticket|invoice|reference|account|transaction|case|ref\.?)"
    r"\s*(?:no\.?|number|id)?\s*[:#]?\s*$",
    re.IGNORECASE,
)


def detect_phone(text: str) -> List[Span]:
    spans = []
    # Horizontal whitespace only: do not swallow the next table cell/paragraph.
    phone_pattern = re.compile(r'(?<!\w)(?:\+[ \t]*\d{1,3}[ \t.-]*(?:\(?\d{1,4}\)?[ \t.-]*){2,6}\d|0\d{2,4}[ -]\d{6,8}|(?:91[ \t.-]+|0)?[6-9]\d{4}[ \t.-]?\d{5}|\(\d{3}\)[ \t.-]*\d{3}[ \t.-]\d{4}|\d{3}[ .-]\d{3}[ .-]\d{4})(?!\d)')
    for m in phone_pattern.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if not (10 <= len(digits) <= 15):
            continue
        preceding = text[max(0, m.start() - 25): m.start()]
        if _NON_PHONE_CONTEXT_RE.search(preceding):
            continue
        spans.append(Span(m.start(), m.end(), "PHONE", m.group()))
    return spans


def detect_date_of_birth(text: str) -> List[Span]:
    spans = []
    for kw in DOB_KEYWORD_RE.finditer(text):
        window = text[kw.end(): kw.end() + 30]
        dm = DATE_VALUE_RE.search(window)
        if dm:
            start = kw.end() + dm.start()
            end = kw.end() + dm.end()
            spans.append(Span(start, end, "DATE_OF_BIRTH", text[start:end]))
    return spans


def detect_company_regex(text: str) -> List[Span]:
    """Regex safety-net for company names spaCy's ORG tagger misses on
    repeat / abbreviated mentions (e.g. after the first full mention)."""
    return [Span(m.start(), m.end(), "COMPANY", m.group().strip()) for m in COMPANY_SUFFIX_RE.finditer(text)]


# Abbreviations whose trailing period must NOT be treated as a sentence
# boundary when we walk backwards looking for where an address clause starts.
_ABBREVIATIONS = {
    "no", "rs", "ltd", "pvt", "mr", "mrs", "dr", "ms", "st", "jr", "sr",
    "vs", "etc", "co", "inc", "corp", "govt", "regd", "flr", "blk",
}


def _prev_clause_boundary(text: str, pos: int) -> int:
    """Find the index just after the nearest real clause boundary
    (. ; : or newline) before `pos`, skipping periods that are actually
    part of an abbreviation like 'Plot No.' or 'Rs.'."""
    best = -1
    for m in re.finditer(r"[.;:\n]", text[:pos]):
        idx = m.start()
        if text[idx] == ".":
            word_match = re.search(r"(\w+)\.$", text[: idx + 1])
            if word_match and word_match.group(1).lower() in _ABBREVIATIONS:
                continue
        best = idx
    return best + 1 if best != -1 else max(0, pos - 80)


def detect_address_regex(text: str) -> List[Span]:
    """Heuristic: grab the clause ending in an Indian PIN code, walking
    back to the nearest sentence/field boundary, as an address block."""
    spans = []
    for m in PIN_CODE_RE.finditer(text):
        start = m.start()
        left = _prev_clause_boundary(text, start)
        window = text[left:m.end()]
        stripped = window.lstrip()
        real_start = left + (len(window) - len(stripped))
        candidate = stripped.strip()
        if len(candidate) < 8:
            continue
        # require it to look address-y: has a comma, or digits, before the pin
        body = candidate[: -len(m.group())]
        if "," not in body and not re.search(r"\d", body):
            continue
        # trim a leading "our registered office is at " / "residing at " etc.
        trimmed = _ADDRESS_LEADIN_RE.sub("", candidate, count=1)
        if trimmed and trimmed != candidate:
            real_start += len(candidate) - len(trimmed)
            candidate = trimmed
        spans.append(Span(real_start, m.end(), "ADDRESS", candidate))
    return spans


INDIAN_STATES_UTS = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    "Chandigarh",
]
_INDIAN_STATE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in INDIAN_STATES_UTS) + r")\b"
)


def detect_indian_state_in_address_context(text: str) -> List[Span]:
    """spaCy's small English model frequently mis-tags Indian state names
    (e.g. 'Maharashtra') as ORG instead of GPE. Since we already know
    which paragraphs are address blocks (PIN code or address-introducing
    phrase present), a small gazetteer catches these reliably and, being
    higher priority than COMPANY, overrides the mislabel."""
    if not (PIN_CODE_RE.search(text) or _ADDRESS_CONTEXT_RE.search(text)):
        return []
    return [Span(m.start(), m.end(), "ADDRESS", m.group()) for m in _INDIAN_STATE_RE.finditer(text)]


REGEX_DETECTORS = [
    detect_email,
    detect_ip,
    detect_ssn,
    detect_credit_card,
    detect_phone,
    detect_date_of_birth,
    detect_address_regex,
    detect_indian_state_in_address_context,
    detect_company_regex,
]


# ---------------------------------------------------------------------------
# spaCy-based detectors (person names, organizations as a supplement to the
# regex company detector, and GPE/LOC as a supplement to address detection)
# ---------------------------------------------------------------------------

_NLP = None


def get_nlp():
    import spacy
    global _NLP
    if _NLP is None:
        try:
            _NLP = spacy.load("en_core_web_sm", disable=["lemmatizer"])
        except OSError as exc:
            raise RuntimeError('Install the model with: python -m spacy download en_core_web_sm') from exc
    return _NLP


# Words spaCy sometimes mis-tags as PERSON/ORG in financial documents.
_NAME_BLOCKLIST = {
    "equity shares", "offer", "bidders", "book running lead managers",
    "red herring prospectus", "companies act", "sebi", "icdr regulations",
    "the offer", "the offer price", "offer price", "floor price", "cap price",
    "book building process", "draft red herring prospectus", "board",
    "the company", "our company", "the board", "stock exchange",
    "securities and exchange board of india", "company",
    # Capitalized "Defined Terms" that are common in Indian IPO prospectuses
    # but are legal/process jargon, not the name of a real company or person.
    "prospectus", "registrar", "syndicate", "promoter group", "equity",
    "equity share", "bids", "allotment", "operations", "statutory auditors",
    "asba", "upi", "upi id", "icdr master circular", "mutual funds",
    "inter alia", "i-sec", "designated intermediaries", "anchor investors",
    "non-institutional investors", "retail individual investors", "bse",
    "nse", "rbi", "cdsl", "nsdl", "net proceeds", "care report",
    "restated financial statements", "net qib portion",
    "non-institutional portion", "offered shares", "bid/offer period",
    "offer for sale", "promoter selling shareholders", "qualified institutional buyers",
    "qibs", "niis", "riis", "gst", "rtgs", "neft", "ifsc",
    "board of directors", "registered office", "corporate office",
    "ind as", "working days", "monitoring agency", "group companies",
    "indian rupees", "proposed capital", "proposed capital expenditure",
    "short term bank", "short term bank facilities", "asba forms",
    "asba account", "public offer account bank", "regd. office",
}

# A trailing floor/suite reference ("5th Floor", "2nd Floor") is an address
# fragment, not a company name, even though it's Title Case.
_FLOOR_RE = re.compile(r"^\d+(?:st|nd|rd|th)\s+Floor$", re.IGNORECASE)

# A capitalized phrase that *starts* with an article/determiner is almost
# certainly a legal "Defined Term" reference (e.g. "the Promoter Selling
# Shareholders", "the Net Proceeds"), not a company name.
_DETERMINER_PREFIX_RE = re.compile(
    r"^(the|a|an|our|this|that|these|those|such|its|their)\s", re.IGNORECASE
)

# Short acronyms spaCy occasionally tags as ORG/PERSON that are actually
# generic terms (including PII *type* names themselves) rather than the
# name of a real company or person.
_ACRONYM_BLOCKLIST = {
    "ssn", "pan", "ip", "cin", "kyc", "din", "gst", "tan", "rtgs", "neft",
    "ifsc", "isin", "dob", "ceo", "cfo", "cs", "llp", "hr", "hdfc", "ipo",
}


# A lone place name ("Pune", "India") mentioned in running narrative text
# is not, by itself, a "physical/mailing address" - only treat GPE/LOC/FAC
# hits as address PII when they occur in a paragraph that looks like it's
# actually giving an address (has a PIN code, or an address-introducing
# phrase).
_ADDRESS_CONTEXT_RE = re.compile(
    r"(situated at|residing at|located at|lives at|lives in|registered office|"
    r"corporate office|regd\.?\s*office|address\s*:|resident of)",
    re.IGNORECASE,
)

# Trim common English lead-ins so the redacted span is the address itself,
# not the whole "Our registered office is at ..." sentence fragment.
_ADDRESS_LEADIN_RE = re.compile(
    r"^.*?\b(?:is\s+at|situated\s+at|located\s+at|residing\s+at|lives\s+at|"
    r"lives\s+in|registered\s+office(?:\s+is)?(?:\s+at)?|"
    r"corporate\s+office(?:\s+is)?(?:\s+at)?|address\s*:|resident\s+of)\s*:?\s*",
    re.IGNORECASE,
)


_TRAILING_STOPWORDS = {"and", "or", "the", "of", "in", "at", "for", "to", "&"}


def _trim_trailing_stopword(ent_text: str, start_char: int, end_char: int):
    """spaCy occasionally over-extends an entity span onto a trailing
    conjunction (e.g. tagging 'Axis Bank Limited and' as one ORG when a
    second company follows). Trim a single trailing stopword token."""
    stripped = ent_text.rstrip()
    trailing_ws = len(ent_text) - len(stripped)
    words = stripped.split(" ")
    if len(words) > 1 and words[-1].lower() in _TRAILING_STOPWORDS:
        new_len = len(stripped) - len(words[-1])
        return stripped[:new_len].rstrip(), start_char, start_char + len(stripped[:new_len].rstrip())
    return ent_text, start_char, end_char - trailing_ws if trailing_ws else end_char


def _looks_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 8:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.8


def run_ner(text: str) -> List[Span]:
    nlp = get_nlp()
    spans = []
    has_address_context = bool(_ADDRESS_CONTEXT_RE.search(text) or PIN_CODE_RE.search(text))

    # spaCy's tagger is trained on standard-cased text and misses most
    # entities in ALL-CAPS runs (cover pages, headers, all-caps clauses -
    # common in Indian prospectuses/legal docs). Title-casing a copy of the
    # text before tagging fixes this; str.title() preserves string length,
    # so the character offsets still line up and we slice the *original*
    # text for the actual redacted value (so casing/spelling stays exact).
    titled = text.title()
    ner_text = titled if _looks_all_caps(text) and len(titled) == len(text) else text

    for ent in nlp(ner_text).ents:
        original_slice = text[ent.start_char:ent.end_char]
        norm = original_slice.strip().lower()
        if norm in _NAME_BLOCKLIST or norm in _ACRONYM_BLOCKLIST or len(norm) < 2:
            continue
        ent_text, start_char, end_char = _trim_trailing_stopword(original_slice, ent.start_char, ent.end_char)
        if not ent_text:
            continue
        if ent.label_ == "PERSON":
            if len(ent_text.split()) >= 2 and not re.search(r'\d', ent_text) and not _DETERMINER_PREFIX_RE.match(ent_text):
                spans.append(Span(start_char, end_char, "PERSON", ent_text))
        elif ent.label_ == "ORG":
            if _DETERMINER_PREFIX_RE.match(ent_text) or len(ent_text.split()) < 2 or _FLOOR_RE.match(ent_text):
                continue
            spans.append(Span(start_char, end_char, "COMPANY", ent_text))
        elif ent.label_ in ("GPE", "LOC", "FAC") and re.search(r"[A-Za-z]{3,}", ent_text):
            if has_address_context:
                spans.append(Span(start_char, end_char, "ADDRESS", ent_text))
    return spans


ALL_LABELS = [
    "PERSON", "EMAIL", "PHONE", "COMPANY", "ADDRESS",
    "SSN", "CREDIT_CARD", "DATE_OF_BIRTH", "IP_ADDRESS",
]
