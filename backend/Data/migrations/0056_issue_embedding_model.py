"""Record which model produced ``Issue.embedding``.

External review (v1.2.13): vectors were stored without their model, so
random SHA-256 "hash embeddings" (no OPENAI_API_KEY) and real OpenAI
vectors sat in one column and were compared with each other. Existing
vectors cannot be attributed to a model, so they are cleared: they
are never compared again anyway, ``find_similar`` falls back to lexical
similarity of the issue text, and issues are re-embedded on their next
resolve or on demand.
"""

from django.db import migrations, models


def clear_unattributed_vectors(apps, schema_editor):
    Issue = apps.get_model('Data', 'Issue')
    Issue.objects.filter(embedding_model__isnull=True).exclude(
        embedding__isnull=True,
    ).update(embedding=None, embedded_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0055_data_run_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='embedding_model',
            field=models.CharField(
                blank=True, max_length=120, null=True,
                help_text='Model / mode that produced embedding. Vectors are '
                          'only compared when this matches.',
            ),
        ),
        migrations.AlterField(
            model_name='issue',
            name='embedding',
            field=models.JSONField(
                blank=True, null=True,
                help_text='Embedding vector of the issue text; the model that '
                          'produced it is in embedding_model.',
            ),
        ),
        migrations.RunPython(clear_unattributed_vectors, migrations.RunPython.noop),
    ]
