from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth import get_user_model
from ..models import ChatSession, ChatMessage, LogAnalysis
import uuid
from datetime import datetime
from django.utils import timezone
from rest_framework.response import Response

User = get_user_model()

class ChatViewsTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
        # Create test chat session
        self.chat_session = ChatSession.objects.create(
            user=self.user,
            title="Test Chat"
        )
        
        # Create some test messages
        self.message = ChatMessage.objects.create(
            chat_session=self.chat_session,
            message="Test message",
            response="Test response"
        )

    def test_list_chat_sessions(self):
        url = reverse('list_chats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data['sessions']), 1)
        self.assertEqual(response_data['sessions'][0]['chat_id'], str(self.chat_session.chat_id))

    def test_get_chat_history(self):
        url = reverse('chat_history', kwargs={'chat_id': self.chat_session.chat_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data['messages']), 1)
        self.assertEqual(response_data['messages'][0]['message'], "Test message")

    def test_delete_chat_session(self):
        url = reverse('delete_chat', kwargs={'chat_id': self.chat_session.chat_id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_session = ChatSession.objects.get(chat_id=self.chat_session.chat_id)
        self.assertFalse(updated_session.is_active)

    """ def test_update_chat_session(self):
        url = reverse('update_chat', kwargs={'chat_id': self.chat_session.chat_id})
        new_title = "Updated Chat Title"
        response = self.client.patch(
            url, 
            data={'title': new_title},
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_session = ChatSession.objects.get(chat_id=self.chat_session.chat_id)
        self.assertEqual(updated_session.title, new_title) """


# LogAnalysisViewsTest removed.
#
# It exercised `list_analyses` and `analysis_detail`, URL names that no longer
# exist: the LogAnalysis list/detail API was superseded by AIAnalyzedBatch and
# the Data app's batch endpoints, which are covered by Data.tests.test_views.
# The tests therefore failed with NoReverseMatch on a surface that was removed
# deliberately — they were invisible until now because an empty
# `ai_model/tests.py` stub shadowed this whole package, so none of these tests
# had been executing.
#
# The LogAnalysis MODEL still exists and is read in one place
# (ai_model/views.py), but has no serializer, view or route. It looks like
# legacy that survived the migration to AIAnalyzedBatch; worth confirming
# before a release, and out of scope for a test fix.
