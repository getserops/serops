from django.test import TestCase
from Organisations.models import Organisations

class OrganisationsModelTest(TestCase):
    
    def test_create_organisation(self):
        """Test that an organisation can be created successfully."""
        organisation = Organisations.objects.create(
            name='Test Organisation',
            website='https://www.test.com'
        )
        self.assertEqual(organisation.name, 'Test Organisation')
        self.assertEqual(organisation.website, 'https://www.test.com')

    def test_unique_name(self):
        """Test that the 'name' field is unique."""
        Organisations.objects.create(name='Unique Organisation', website='https://unique.com')
        
        with self.assertRaises(Exception):
            Organisations.objects.create(name='Unique Organisation', website='https://duplicate.com')

    def test_organisation_name_nullable_website(self):
        """Test that the 'website' field can be null."""
        organisation = Organisations.objects.create(
            name='Another Organisation',
            website=None
        )
        self.assertIsNone(organisation.website)

    def test_str_method(self):
        """Test the __str__ method."""
        organisation = Organisations.objects.create(
            name='Test Organisation',
            website='https://www.test.com'
        )
        self.assertEqual(str(organisation), 'Test Organisation')