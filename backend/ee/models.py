from django.conf import settings
from django.db import models


class InstalledLicense(models.Model):
    """The Enterprise license key of this install (at most one row).

    Install-wide: one install can host several organisations, and the key
    covers all of them. Removing the row, or the key expiring, switches the
    Enterprise features off; no other data depends on it.
    """

    raw = models.TextField(help_text='The license key exactly as uploaded (signed JSON).')
    installed_at = models.DateTimeField(auto_now=True)
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    def __str__(self):
        return f'Enterprise license (installed {self.installed_at:%Y-%m-%d})'
