from collections import deque
from datetime import datetime, timedelta

class ChatContextManager:
    def __init__(self, max_context_length=10, context_ttl_minutes=30):
        self.contexts = {}
        self.max_context_length = max_context_length
        self.context_ttl = timedelta(minutes=context_ttl_minutes)

    def add_message(self, session_id, message, response):
        """Add a message-response pair to the context"""
        timestamp = datetime.now()
        if session_id not in self.contexts:
            self.contexts[session_id] = deque(maxlen=self.max_context_length)
        
        self.contexts[session_id].append({
            'timestamp': timestamp,
            'message': message,
            'response': response
        })
        self._cleanup_old_contexts()

    def get_context(self, session_id):
        """Get formatted context history for a session"""
        if session_id not in self.contexts:
            return []
        
        context_messages = []
        for item in self.contexts[session_id]:
            context_messages.append(f"User: {item['message']}")
            context_messages.append(f"Assistant: {item['response']}")
        
        return context_messages

    def _cleanup_old_contexts(self):
        """Remove expired contexts"""
        current_time = datetime.now()
        expired_sessions = []
        
        for session_id, context in self.contexts.items():
            if context and (current_time - context[-1]['timestamp']) > self.context_ttl:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self.contexts[session_id]