from django.urls import path
from .views import delete_chat_session, generate_text, get_chat_history, get_chat_sessions, list_chat_sessions, update_chat_session, trigger_batch_analysis
from .admin_views import (
    get_ai_circuit_status, 
    get_ai_rate_status, 
    reset_ai_circuit, 
    trip_ai_circuit,
    get_ai_health
)


urlpatterns = [
    path('generate-text/', generate_text, name='generate_text'),
    path('chats/', list_chat_sessions, name='list_chats'),
    path('chats/<uuid:chat_id>/', get_chat_history, name='chat_history'),
    path('chats/delete/<uuid:chat_id>', delete_chat_session, name='delete_chat'),
    path('chats/<uuid:chat_id>/update/', update_chat_session, name='update_chat'),
    path('analyze-batch/', trigger_batch_analysis, name='trigger_batch_analysis'),
    path('chat-sessions/', get_chat_sessions, name='chat-sessions'),
    
    # Admin endpoints for AI service monitoring
    path('admin/health/', get_ai_health, name='ai_health'),
    path('admin/circuits/', get_ai_circuit_status, name='ai_circuit_status'),
    path('admin/rates/', get_ai_rate_status, name='ai_rate_status'),
    path('admin/circuits/<str:provider>/reset/', reset_ai_circuit, name='reset_ai_circuit'),
    path('admin/circuits/<str:provider>/trip/', trip_ai_circuit, name='trip_ai_circuit'),
]
