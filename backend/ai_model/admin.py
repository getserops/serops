from django.contrib import admin

from ai_model.models import ChatMessage, ChatSession

# Register your models here.
admin.site.register(ChatSession)
admin.site.register(ChatMessage)