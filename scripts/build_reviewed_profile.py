"""Build the disclosed prospectus-specific profile from reviewed source entries.

These are configuration data, not evaluation labels or model training data.
Every entry must have an exact occurrence in the original Word text.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pii_redactor.docx_redactor import read_records, join_records

PEOPLE = '''Kushal Subbayya Hegde|Kushal Hegde
Pushpa Kushal Hegde|Pushpa Hegde
Rajesh Kushal Hegde|Rajesh Hegde
Rohit Kushal Hegde|Rohit Hegde
Rakhi Girija Shetty
Sarthak Malvadkar
Lokesh Shah
Soumavo Sarkar
Kishan Rastogi
Abhijit Diwan
Shanti Gopalkrishnan
Lalit Muljibhai Sarvaiya
Sandesh Bhagwat
Amod Joshi
Sangeeta Ramprasad Rai
Katyayani Balasubramanian
Rupal K. Sancheti
Salil Ajay Bhargava
Jabeen Ajay Menon
Ajay Menon
Ganesh Prasad
DM Shetty
Gopal BO
Karunakar Bhandary
SA Shetty
Jayaram Shetty
Karunakar Hegde
Vijay Hegde
Karunakar N. Bhandary
Narayna B. Shetty
Jayaram N. Shetty
Dinesh Hirachand Munot
Ajay Shriram Patil
Ram Kumar Tiwari
Indu Jacob
Prakash Boricha
Eric Bacha
Sachin Gawade
Pravin Teli
Siddharth Jadhav
Tushar Gavankar
Varun Badai
Hitesh Ramani
Chitra Raste
Sharmila Joshi
Cherag Gyara
Manisha Shukla
Tushar Wakhele
Ashish Mathew Pulloor
Anand Soni'''

COMPANIES = '''KSH International Limited|KSH International Private Limited|KSH International
Bhandary Metal Extrusion Private Limited
Dhaulagiri Family Trust
Everest Family Trust
Makalu Family Trust
Broad Family Trust
Annapurna Family Trust
Kanchenjunga Family Trust
Waterloo Industrial Park VI Private Limited
Kirtane & Pandit LLP|Kirtane & Pandit, LLP|Kirtane & Pandit
BSE Limited|BSE
National Stock Exchange of India Limited|National Stock Exchange|NSE
Nuvama Wealth Management Limited|Nuvama
ICICI Securities Limited|ICICI Securities|I-Sec
MUFG Intime India Private Limited|Link Intime India Private Limited
CARE Analytics and Advisory Private Limited|CareEdge Research
Precision Wires India Limited
Malabar India Fund Limited
Al-Ahleia Switchgear Co.
Bharat Bijlee Limited
CG Power and Industrial Solutions Limited
Emirates Transformer & Switchgear Limited
Georgia Transformer Corporation
Nidec Industrial Automation India Private Limited
Transformers & Rectifiers (India) Limited
Virginia Transformer Corporation
Ahlstrom Sweden AB
Cindus Corporation
Elantas Beck India Limited
Hindalco Industries Limited
Polycom Associates
Savli Copper Products Private Limited
Union Copper Rod LLC
Vedanta Limited Sterlite Copper
Karunakar Hegde HUF
Waterloo Motors Private Limited|Waterloo Motors
KSH Project Management Services Private Limited
KSH Infra Park VI Private Limited
KSH Infra Park 5 Private Limited
KSH Distriparks Private Limited
KSH Integrated Logistics Private Limited
Kushal Motors and Electricals Private Limited|Kushal Motors
Kushal Electricals
Waterloo Industrial Park I Private Limited
Waterloo Industrial Park II Private Limited
Waterloo Industrial Park III Private Limited
Waterloo Industrial Park IV Private Limited
Waterloo Industrial Park V Private Limited
Waterloo Industrial Park VIII Private Limited
Waterloo Industrial Park IX Private Limited
Waterloo Industrial Park IX A Private Limited
Waterloo Industrial Park IX B Private Limited
KSH Infra Park IV Private Limited
CARE Ratings Limited
Shubhkamal Leasing and Investment Private Limited
Parijat Foundation
Trilegal
HDFC Bank Limited|HDFC Bank|HDFC
ICICI Bank Limited|ICICI Bank
Kanj & Co. LLP
Hingne Tare & Associates
Citibank N.A.
Export-Import Bank of India
IndusInd Bank Limited
HDFC Limited
State Bank of India
The Federal Bank Limited
Bajaj Finance Limited
National Securities Depository Limited|NSDL
Central Depository Services (India) Limited|Central Depository Services|CDSL
National Payments Corporation of India|NPCI
Solar Energy Corporation of India Limited
London Metal Exchange'''

# Paragraph ranges manually reviewed as full postal addresses. Optional start
# and end markers exclude adjoining company names, role labels and phone fields.
ADDRESSES = [
    (18, 19, None, None), (20, 21, None, None),
    (135, 135, '11/3', ';'), (136, 136, '201,', ';'),
    (168, 168, None, None), (176, 176, None, None), (185, 185, None, None),
    (324, 324, '11/3', None), (352, 352, 'Plot No.', None), (356, 356, 'Plot No.', None),
    (3499, 3499, 'Plot No.', '. The proposed'),
    (4080, 4082, None, None), (4085, 4086, None, None), (4093, 4093, None, None),
    (4104, 4104, None, None), (4108, 4108, None, None), (4112, 4112, None, None),
    (4116, 4117, None, None), (4121, 4121, None, None), (4125, 4125, None, None),
    (4129, 4129, None, None), (4133, 4133, None, None),
    (4139, 4141, 'Gat No.', None), (4152, 4153, None, None),
    (4159, 4159, 'ICICI Venture', None), (4246, 4248, None, None),
    (4262, 4265, None, None), (4270, 4271, 'C-101', ' Telephone:'),
    (4278, 4279, 'Lodha', None), (4289, 4289, None, ' Telephone:'),
    (4339, 4342, None, None), (4354, 4356, None, None),
    (4363, 4363, 'Flat No.', None), (4374, 4375, None, None),
    (4384, 4386, None, None), (4391, 4393, '2401', None),
    (4397, 4398, '3rd Floor', None), (4402, 4404, None, None),
    (4409, 4411, None, None), (4417, 4417, 'Ground Floor', None),
    (4424, 4425, None, None), (4444, 4445, 'SEBI Bhavan', None),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    args = parser.parse_args()
    records = read_records(args.source)
    body = [r for r in records if r.id.startswith('word/document.xml:')]
    text = join_records(body)
    entities = []
    for label, catalog in [('PERSON', PEOPLE), ('COMPANY', COMPANIES)]:
        for line in catalog.splitlines():
            aliases = line.split('|')
            evidence = []
            for alias in aliases:
                pattern = re.compile(r'(?<!\w)' + r'\s+'.join(map(re.escape, alias.split())) + r'(?!\w)', re.I)
                match = pattern.search(text)
                if not match:
                    raise ValueError(f'Profile entry not found in source: {alias}')
                evidence.append(next(r.id for r in body if r.start <= match.start() < r.start + len(r.text)))
            entities.append({'label': label, 'canonical': aliases[0], 'aliases': aliases[1:], 'source_ids': sorted(set(evidence))})
    by_index = {int(r.id.split(':p')[1]): r for r in body}
    for first, last, start_marker, end_marker in ADDRESSES:
        value = '\n'.join(by_index[i].text for i in range(first, last + 1))
        if start_marker:
            value = value[value.index(start_marker):]
        if end_marker:
            value = value[:value.index(end_marker)]
        entities.append({'label': 'ADDRESS', 'canonical': value, 'aliases': [],
                         'source_ids': [by_index[i].id for i in range(first, last + 1)]})
    data = {'source_file': Path(args.source).name,
            'source_sha256': hashlib.sha256(Path(args.source).read_bytes()).hexdigest(),
            'method': 'Source-reviewed entity catalog; document-specific assisted redaction, not held-out model performance.',
            'reviewer': 'AI-assisted review against the supplied source; not independently human-adjudicated.',
            'entities': entities}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {len(entities)} source-verified entities to {args.output}')


if __name__ == '__main__':
    main()
