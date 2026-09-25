"""Stable pseudonyms keyed by normalized identity, with a working user seed."""
import hashlib
import re
from datetime import date
from faker import Faker


def normalize(value):
    return re.sub(r'\s+', ' ', value).strip().casefold()


class FakeMapper:
    def __init__(self, seed=42, aliases=None):
        self.seed = seed
        self.aliases = aliases or {}
        self._map = {}
        self._originals = {}

    def _key(self, label, original):
        value = normalize(original)
        if label == 'PHONE':
            value = re.sub(r'\D', '', original)
            if len(value) == 10:
                value = '91' + value
        return self.aliases.get(value, value)

    def get(self, label, original):
        key = self._key(label, original)
        if key in self._map:
            return self._map[key]
        digest = hashlib.sha256(f'{self.seed}\0{key}'.encode()).hexdigest()
        fake = Faker('en_IN')
        fake.seed_instance(int(digest, 16))
        if label == 'PERSON':
            value = fake.name()
        elif label == 'COMPANY':
            value = fake.company()
        elif label == 'EMAIL':
            value = f'contact.{digest[:12]}@example.com'
        elif label == 'PHONE':
            value = '+91 ' + fake.numerify('9#########')
        elif label == 'ADDRESS':
            value = fake.address().replace('\n', ', ')
        elif label == 'SSN':
            value = fake.numerify('000-##-####')
        elif label == 'CREDIT_CARD':
            value = fake.credit_card_number(card_type='visa')
        elif label == 'DATE_OF_BIRTH':
            value = fake.date_between_dates(date(1960, 1, 1), date(2000, 12, 31)).strftime('%d %B %Y')
        elif label == 'IP_ADDRESS':
            value = '2001:db8::' + digest[:4] if ':' in original else f'192.0.2.{1 + int(digest[:4], 16) % 254}'
        else:
            value = '[REDACTED]'
        if normalize(value) == normalize(original):
            value = '[REDACTED]'
        self._map[key] = value
        self._originals[key] = (label, original)
        return value

    def mapping_table(self):
        return [(label, original, self._map[key]) for key, (label, original) in self._originals.items()]
