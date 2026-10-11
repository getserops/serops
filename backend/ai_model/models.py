from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class ChatSession(models.Model):
    chat_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    batch_id = models.CharField(max_length=100, blank=True, null=True)
    project_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Chat {self.chat_id} - {self.user.username}"

    def add_message(self, message, response):
        """Add a new message and response to the chat session"""
        return ChatMessage.objects.create(
            chat_session=self,
            message=message,
            response=response
        )

    def get_messages(self, limit=None):
        """Get chat messages, optionally limited to a specific number"""
        messages = self.messages.all()
        if limit:
            messages = messages[:limit]
        return messages

class ChatMessage(models.Model):
    chat_session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    message = models.TextField()
    response = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['timestamp']

class LogAnalysis(models.Model):
    batch_id = models.CharField(max_length=100, unique=True)
    timestamp = models.DateTimeField()
    environment = models.CharField(max_length=50)
    analysis_result = models.TextField()
    services_analyzed = models.IntegerField()
    logs_analyzed = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='log_analyses')
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Log Analyses'

    def __str__(self):
        return f"Analysis of batch {self.batch_id} at {self.timestamp}"


class AITokenUsage(models.Model):
    """
    Cost-visibility record for every AI API call.

    Each row is one call (batch analysis, chat message, manual re-analysis)
    with input/output token counts and an estimated USD cost. Used for
    per-organisation cost reporting on the dashboard. There is no quota
    enforcement — this is observability, not billing.
    """

    USAGE_TYPES = [
        ('batch_analysis', 'Batch Analysis'),
        ('chat_message', 'Chat Message'),
        ('manual_analysis', 'Manual Analysis'),
        ('batch_reanalysis', 'Batch Re-analysis'),
    ]

    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='ai_token_usages',
    )
    batch = models.ForeignKey(
        'Data.AIAnalyzedBatch',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Batch that was analyzed (null for chat usage)",
    )
    model_name = models.CharField(max_length=50)
    tokens_input = models.IntegerField(default=0)
    tokens_output = models.IntegerField(default=0)
    tokens_total = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    usage_type = models.CharField(max_length=20, choices=USAGE_TYPES, default='batch_analysis')

    class Meta:
        db_table = 'ai_model_token_usage'
        indexes = [
            models.Index(fields=['organisation', 'timestamp']),
            models.Index(fields=['model_name', 'timestamp']),
        ]
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.model_name}: {self.tokens_total} tokens (${self.cost_usd})"