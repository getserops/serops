"""
Provider errors a user can act on: no credit left, and a quota that says
when it resets. Both were seen on real accounts (2026-11-04/05): Anthropic
"credit balance is too low" showed as UNKNOWN_ERROR, and Gemini's free-tier
daily limit as QUOTA_EXCEEDED "Will retry automatically".
"""
import json

from django.test import SimpleTestCase

from ai_model.adapters.base import AIServiceError
from ai_model.adapters.claude import ClaudeAdapter
from ai_model.adapters.gemini import GeminiAdapter
from ai_model.adapters.openai_generic import GenericOpenAIAdapter
from ai_model.views import _ai_failure_response

ANTHROPIC_NO_CREDIT = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API. Please go to "
    "Plans & Billing to upgrade or purchase credits.'}}"
)
OPENAI_NO_CREDIT = (
    "Error code: 429 - {'error': {'message': 'You exceeded your current quota, please check "
    "your plan and billing details.', 'type': 'insufficient_quota', 'code': 'insufficient_quota'}}"
)
GEMINI_DAILY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, "
    "please check your plan and billing details. * Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20\\nPlease retry "
    "in 46m6.458663059s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'quotaId': "
    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}, {'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '2766s'}]}}"
)
OPENAI_RATE = "Error code: 429 - Rate limit reached for gpt-4o. Please try again in 20s."


class OutOfCreditTest(SimpleTestCase):
    def test_anthropic_no_credit_is_out_of_credit_not_unknown(self):
        error = ClaudeAdapter().normalize_error(Exception(ANTHROPIC_NO_CREDIT))
        self.assertEqual(error.code, 'OUT_OF_CREDIT')
        self.assertIn('no credit', error.get_user_message())

    def test_openai_insufficient_quota_is_out_of_credit_not_a_rate_limit(self):
        error = GenericOpenAIAdapter().normalize_error(Exception(OPENAI_NO_CREDIT))
        self.assertEqual(error.code, 'OUT_OF_CREDIT')

    def test_deepseek_insufficient_balance_is_out_of_credit(self):
        error = GenericOpenAIAdapter().normalize_error(Exception('Error code: 402 - Insufficient Balance'))
        self.assertEqual(error.code, 'OUT_OF_CREDIT')

    def test_gemini_free_tier_billing_hint_is_still_a_quota(self):
        # Google's quota message says "check your plan and billing details";
        # that alone must not read as an empty account.
        error = GeminiAdapter().normalize_error(Exception(GEMINI_DAILY))
        self.assertEqual(error.code, 'QUOTA_EXCEEDED')


class QuotaResetTest(SimpleTestCase):
    def test_gemini_daily_limit_says_daily_and_when_it_resets(self):
        error = GeminiAdapter().normalize_error(Exception(GEMINI_DAILY))
        self.assertEqual(error.retry_after_seconds, 2766)
        self.assertIn('daily quota', error.message)
        self.assertIn('about 46 min', error.message)
        self.assertNotIn('automatically', error.get_user_message())
        self.assertEqual(error.to_dict()['retry_after_seconds'], 2766)

    def test_openai_rate_limit_retry_in_seconds(self):
        error = GenericOpenAIAdapter().normalize_error(Exception(OPENAI_RATE))
        self.assertEqual(error.code, 'QUOTA_EXCEEDED')
        self.assertEqual(error.retry_after_seconds, 20)
        self.assertIn('about 1 min', error.message)

    def test_quota_without_a_delay_does_not_invent_one(self):
        error = ClaudeAdapter().normalize_error(Exception('Error code: 429 - rate_limit_error'))
        self.assertEqual(error.code, 'QUOTA_EXCEEDED')
        self.assertIsNone(error.retry_after_seconds)
        self.assertNotIn('resets in', error.message)

    def test_hours_and_minutes(self):
        self.assertEqual(AIServiceError._retry_after_seconds('Please retry in 1h2m3s.'), 3723)


class ChatFailureResponseTest(SimpleTestCase):
    def test_chat_names_the_provider_problem(self):
        response = _ai_failure_response(AIServiceError.from_type('out_of_credit'), 'Failed')
        self.assertEqual(response.status_code, 502)
        body = json.loads(response.content)
        self.assertEqual(body['error'], 'out_of_credit')
        self.assertIn('billing', body['message'])

    def test_no_error_keeps_the_old_answer(self):
        response = _ai_failure_response(None, 'Failed to process chat request')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.content)['error'], 'Failed to process chat request')
