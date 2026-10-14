from django.db import migrations, models


def oidc_only(apps, schema_editor):
    SecuritySettings = apps.get_model('Users', 'SecuritySettings')
    # Old provider names were OIDC under another label.
    SecuritySettings.objects.filter(
        sso_provider__in=['okta', 'azure_ad', 'google', 'keycloak'],
    ).update(sso_provider='oidc')
    # SAML never worked: the login endpoint always refused it.
    SecuritySettings.objects.exclude(sso_provider__in=['oidc', 'none']).update(
        sso_provider='none', sso_enabled=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('Users', '0010_alter_user_managers'),
    ]

    operations = [
        migrations.RunPython(oidc_only, migrations.RunPython.noop),
        migrations.RemoveField(model_name='securitysettings', name='saml_entity_id'),
        migrations.RemoveField(model_name='securitysettings', name='saml_sso_url'),
        migrations.RemoveField(model_name='securitysettings', name='saml_x509_cert'),
        # The discovery URL already names the realm; this was never read.
        migrations.RemoveField(model_name='securitysettings', name='sso_realm'),
        migrations.AlterField(
            model_name='securitysettings',
            name='sso_provider',
            field=models.CharField(
                choices=[('none', 'Disabled'), ('oidc', 'OpenID Connect (OIDC)')],
                default='none', max_length=50,
            ),
        ),
    ]
