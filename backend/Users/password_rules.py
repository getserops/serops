"""The password rule of the sign-up form, on the server.

The sign-up form (frontend/src/components/Register.jsx and RegisterPart2.jsx)
asks for at least 10 characters with an upper-case letter, a lower-case
letter and a number; the server then applies AUTH_PASSWORD_VALIDATORS.
``check_signup_password`` applies both, so a first admin created from the
command line meets the same rule as one created through the form.
"""
import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

# Same expression as the form.
SIGNUP_PASSWORD_RE = re.compile(r'^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{10,}$')
SIGNUP_PASSWORD_RULE = 'at least 10 characters, with an upper-case letter, a lower-case letter and a number'


def check_signup_password(password, user=None):
    """Raise ValidationError listing every reason ``password`` is refused."""
    messages = []
    if not SIGNUP_PASSWORD_RE.match(password or ''):
        messages.append(f'The password must have {SIGNUP_PASSWORD_RULE}.')
    try:
        validate_password(password or '', user)
    except ValidationError as exc:
        messages.extend(exc.messages)
    if messages:
        raise ValidationError(messages)
