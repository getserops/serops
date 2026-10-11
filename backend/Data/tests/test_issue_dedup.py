"""
Tests for Issue Deduplication v2
"""
from django.test import TestCase
from unittest.mock import Mock, patch
from Data.models import Issue


class TestIssueFingerprint(TestCase):
    """Test fingerprint generation"""
    
    def test_same_input_same_fingerprint(self):
        """Same inputs should produce same fingerprint"""
        fp1 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        fp2 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        self.assertEqual(fp1, fp2)
    
    def test_different_issue_type_different_fingerprint(self):
        """Different issue_type should produce different fingerprint"""
        fp1 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        fp2 = Issue.generate_fingerprint('CPU_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        self.assertNotEqual(fp1, fp2)
    
    def test_different_component_different_fingerprint(self):
        """Different component should produce different fingerprint"""
        fp1 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        fp2 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'user-service', 'production')
        self.assertNotEqual(fp1, fp2)
    
    def test_different_environment_different_fingerprint(self):
        """Different environment should produce different fingerprint"""
        fp1 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        fp2 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'staging')
        self.assertNotEqual(fp1, fp2)


class TestComponentNormalization(TestCase):
    """Test component name normalization"""
    
    def test_normalize_dashes_to_underscores(self):
        """Dashes should be converted to underscores"""
        self.assertEqual(Issue.normalize_component('payment-service'), 'payment_service')
    
    def test_normalize_lowercase(self):
        """Names should be lowercased"""
        self.assertEqual(Issue.normalize_component('Payment-Service'), 'payment_service')
    
    def test_normalize_strips_whitespace(self):
        """Whitespace should be stripped"""
        self.assertEqual(Issue.normalize_component('  payment-service  '), 'payment_service')
    
    def test_normalize_empty_returns_empty(self):
        """Empty string should return empty"""
        self.assertEqual(Issue.normalize_component(''), '')
        self.assertEqual(Issue.normalize_component(None), '')
    
    def test_normalized_components_same_fingerprint(self):
        """Slightly different component names should produce same fingerprint after normalization"""
        fp1 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        fp2 = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'Payment-Service', 'production')
        self.assertEqual(fp1, fp2)


class TestInfrastructurePromotion(TestCase):
    """Test tiered matching with INFRASTRUCTURE promotion"""
    
    def test_infrastructure_fingerprint_different_from_service(self):
        """INFRASTRUCTURE issue fingerprint should differ from specific service"""
        fp_infra = Issue.generate_fingerprint('MEMORY_HIGH', 'INFRASTRUCTURE', 'project-a', 'INFRASTRUCTURE', 'production')
        fp_service = Issue.generate_fingerprint('MEMORY_HIGH', 'SERVICE', 'project-a', 'payment-service', 'production')
        self.assertNotEqual(fp_infra, fp_service)
    
    # More complex tests would require database fixtures
