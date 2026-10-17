from django.db import migrations


class Migration(migrations.Migration):
    """Drop the Issue-fingerprint cache Sentinel compared log patterns
    against. The two hashes never matched, so the "issue regression" rule
    that read it could not fire; returning errors are caught by the log
    pattern expiry (known_log_patterns) and the error-rate spike rule."""

    dependencies = [
        ('Data', '0049_projectenvironmentstate_known_log_patterns'),
    ]

    operations = [
        migrations.RemoveField(model_name='projectenvironmentstate', name='known_fingerprints'),
    ]
