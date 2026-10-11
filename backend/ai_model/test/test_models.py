from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from ..models import ChatSession, ChatMessage
import uuid

class ChatSessionTest(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.test_user = self.User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
    def test_chat_session_creation(self):
        chat_session = ChatSession.objects.create(
            user=self.test_user
        )
        self.assertIsInstance(chat_session.chat_id, uuid.UUID)
        self.assertEqual(chat_session.user, self.test_user)
        self.assertTrue(chat_session.is_active)
        self.assertIsNone(chat_session.title)
        self.assertIsNotNone(chat_session.created_at)
        self.assertIsNotNone(chat_session.last_message_at)

    def test_chat_session_str_representation(self):
        chat_session = ChatSession.objects.create(
            user=self.test_user
        )
        expected_str = f"Chat {chat_session.chat_id} - {self.test_user.username}"
        self.assertEqual(str(chat_session), expected_str)

    def test_add_message(self):
        chat_session = ChatSession.objects.create(user=self.test_user)
        message = "Test message"
        response = "Test response"
        
        chat_message = chat_session.add_message(message, response)
        
        self.assertIsInstance(chat_message, ChatMessage)
        self.assertEqual(chat_message.message, message)
        self.assertEqual(chat_message.response, response)
        self.assertEqual(chat_message.chat_session, chat_session)

    def test_get_messages(self):
        chat_session = ChatSession.objects.create(user=self.test_user)
        # Create 3 messages
        messages = [
            chat_session.add_message(f"Message {i}", f"Response {i}")
            for i in range(3)
        ]
        
        # Test without limit
        retrieved_messages = chat_session.get_messages()
        self.assertEqual(len(retrieved_messages), 3)
        
        # Test with limit
        limited_messages = chat_session.get_messages(limit=2)
        self.assertEqual(len(limited_messages), 2)



    def test_title_optional(self):
        # Test with title
        chat_with_title = ChatSession.objects.create(
            user=self.test_user,
            title="Test Chat"
        )
        self.assertEqual(chat_with_title.title, "Test Chat")
        
        # Test without title
        chat_without_title = ChatSession.objects.create(
            user=self.test_user
        )
        self.assertIsNone(chat_without_title.title)



    """    def test_ordering(self):
        # Create chats with specific timestamps for deterministic ordering
        chat1 = ChatSession.objects.create(
            user=self.test_user,
            created_at=timezone.now() - timezone.timedelta(days=2)
        )
        chat2 = ChatSession.objects.create(
            user=self.test_user,
            created_at=timezone.now() - timezone.timedelta(days=1)
        )
        chat3 = ChatSession.objects.create(
            user=self.test_user,
            created_at=timezone.now()
        )

        ordered_chats = ChatSession.objects.all()
        self.assertEqual(list(ordered_chats), [chat3, chat2, chat1]) """