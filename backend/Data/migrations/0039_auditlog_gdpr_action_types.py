# Adds ACCOUNT_DELETE and ORG_DELETE choices to AuditLog.action
# for the GDPR right-to-erasure endpoint.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0038_issue_memory_lookup_index'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('LOGIN', 'User Login'),
                    ('LOGIN_FAILED', 'Failed Login Attempt'),
                    ('LOGOUT', 'User Logout'),
                    ('PASSWORD_CHANGE', 'Password Changed'),
                    ('SETTINGS_CHANGE', 'Settings Changed'),
                    ('SERVICE_CREATE', 'Service Created'),
                    ('SERVICE_UPDATE', 'Service Updated'),
                    ('SERVICE_DELETE', 'Service Deleted'),
                    ('BATCH_DELETE', 'Batch Deleted'),
                    ('BATCH_CLEANUP', 'Batch Auto-Cleanup'),
                    ('TEAM_INVITE', 'Team Member Invited'),
                    ('TEAM_REMOVE', 'Team Member Removed'),
                    ('TEAM_ROLE_CHANGE', 'Team Role Changed'),
                    ('AI_MODEL_CHANGE', 'AI Model Changed'),
                    ('NOTIFICATION_TEST', 'Notification Test Sent'),
                    ('EXPORT_DATA', 'Data Exported'),
                    ('ACCOUNT_DELETE', 'User Account Deleted (GDPR)'),
                    ('ORG_DELETE', 'Organisation Deleted (GDPR)'),
                ],
                db_index=True,
                max_length=50,
            ),
        ),
    ]
