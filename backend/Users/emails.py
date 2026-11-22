"""Email identity rules shared by every place that creates or renames an
account (audit 2026-11-20, item 8)."""


def normalize_email(value):
    """Addresses are stored lowercase and trimmed: 'Ann@X.com' and
    'ann@x.com' are one person, and the database keeps one account for both
    (Users.User constraint users_email_lower_unique)."""
    return (value or '').strip().lower()


def sso_domain_claimed_elsewhere(email, organisation_id):
    """Whether another organisation's single sign-on claims this address's
    domain. Such an address stays free for its owner: it may not be invited,
    provisioned, registered or moved to anywhere else."""
    from Users.models import SecuritySettings
    if '@' not in (email or ''):
        return False
    domain = normalize_email(email).rsplit('@', 1)[1]
    return SecuritySettings.objects.filter(sso_enabled=True, sso_domains__contains=[domain]).exclude(
        organisation_id=organisation_id).exists()
