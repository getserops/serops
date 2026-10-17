"""APIClient that signs deploy-webhook requests (X-SerOps-Signature).

Deploy webhooks refuse unsigned events, so tests that are not about the
signature use this client to sign every POST with the binding's secret.
Pass ``HTTP_X_SEROPS_SIGNATURE`` explicitly to send a specific (or empty)
signature instead.
"""
import hashlib
import hmac
import json

from rest_framework.test import APIClient


class SigningAPIClient(APIClient):

    def __init__(self, secret: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.secret = secret

    def post(self, path, data=None, format=None, content_type=None, **extra):
        if 'HTTP_X_SEROPS_SIGNATURE' not in extra:
            body = data if isinstance(data, (bytes, str)) else json.dumps(data or {})
            body = body.encode() if isinstance(body, str) else body
            extra['HTTP_X_SEROPS_SIGNATURE'] = 'sha256=' + hmac.new(
                self.secret.encode(), body, hashlib.sha256).hexdigest()
            return super().post(path, data=body, content_type='application/json', **extra)
        return super().post(path, data=data, format=format, content_type=content_type, **extra)
