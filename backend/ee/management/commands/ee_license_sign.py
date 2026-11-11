"""Sign a SerOps Enterprise license key (maintainers only).

    python manage.py ee_license_sign --private-key /secure/serops-license-ed25519-private.pem \\
        --licensee "Acme Corp" --features saml,scim --expires 2027-10-21 > acme.license.json

The private key never goes in the repository or a container image. A new
keypair: ``--generate-keypair DIR`` writes it there and prints the public key
for ee/licensing/keys.py.
"""

import base64
import json
import os
import uuid
from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ee.licensing.features import FEATURES
from ee.licensing.verify import FORMAT, canonical


class Command(BaseCommand):
    help = 'Sign a SerOps Enterprise license key, or generate a signing keypair.'

    def add_arguments(self, parser):
        parser.add_argument('--private-key', help='PEM file of the Ed25519 signing key')
        parser.add_argument('--licensee', help='Customer name, as it should appear in Settings')
        parser.add_argument('--features', help=f'Comma-separated: {", ".join(FEATURES)}')
        parser.add_argument('--expires', help='Last valid day, YYYY-MM-DD')
        parser.add_argument('--id', help='License id (default: generated)')
        parser.add_argument('--generate-keypair', metavar='DIR', help='Write a new keypair to DIR and exit')

    def handle(self, *args, **opts):
        if opts['generate_keypair']:
            return self._generate(opts['generate_keypair'])
        for name in ('private_key', 'licensee', 'features', 'expires'):
            if not opts[name]:
                raise CommandError(f'--{name.replace("_", "-")} is required')
        features = sorted({f.strip() for f in opts['features'].split(',') if f.strip()})
        unknown = [f for f in features if f not in FEATURES]
        if unknown:
            raise CommandError(f'Unknown features: {", ".join(unknown)}')
        try:
            expires = date.fromisoformat(opts['expires'])
        except ValueError:
            raise CommandError('--expires must be YYYY-MM-DD')
        with open(opts['private_key'], 'rb') as fh:
            key = serialization.load_pem_private_key(fh.read(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise CommandError('The private key is not an Ed25519 key')
        payload = {
            'id': opts['id'] or f'lic_{uuid.uuid4().hex[:12]}',
            'licensee': opts['licensee'].strip(),
            'features': features,
            'issued': timezone.now().date().isoformat(),
            'expires': expires.isoformat(),
        }
        signature = base64.b64encode(key.sign(canonical(payload))).decode()
        self.stdout.write(json.dumps({'format': FORMAT, 'payload': payload, 'signature': signature}, indent=2))

    def _generate(self, directory):
        os.makedirs(directory, mode=0o700, exist_ok=True)
        path = os.path.join(directory, 'serops-license-ed25519-private.pem')
        if os.path.exists(path):
            raise CommandError(f'{path} exists; refusing to overwrite a signing key')
        key = Ed25519PrivateKey.generate()
        with open(path, 'wb') as fh:
            fh.write(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
            ))
        os.chmod(path, 0o600)
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.stdout.write(f'Private key: {path}\nPublic key (add to ee/licensing/keys.py): {base64.b64encode(public).decode()}')
