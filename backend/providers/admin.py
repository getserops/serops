from django.contrib import admin

from providers.models import GitlabProject, Job, Pipeline

# Register your models here.

admin.site.register(GitlabProject)
admin.site.register(Pipeline)
admin.site.register(Job)