from django.test import TestCase
from django.core.exceptions import ValidationError
from Users.models import User
from Organisations.models import Organisations


class UserModelTest(TestCase):
    """Unit tests for User model"""

    def setUp(self):
        self.org = Organisations.objects.create(
            name="Test Org",
            website="http://test.com"
        )

        self.user_data = {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone": "1234567890",
            "role": "user",
            "organisation": self.org,
            "password": "testpass123"  # Ensure password is included
        }

    def test_create_user(self):
        """Test creating a user with valid data"""
        user = User.objects.create(**self.user_data)
        user.set_password(self.user_data["password"])  # Hash password
        user.save()

        self.assertEqual(user.email, self.user_data["email"])
        self.assertEqual(user.role, "user")
        self.assertEqual(user.organisation, self.org)
        self.assertTrue(user.check_password("testpass123"))  # Ensure password hashing

    def test_user_str_method(self):
        """Test user string representation"""
        user = User.objects.create(**self.user_data)
        expected_str = f"{user.first_name} {user.last_name}"
        self.assertEqual(str(user), expected_str) 

    def test_user_status_choices(self):
        """Test user status choices validation"""
        user = User.objects.create(**self.user_data)
        user.set_password(self.user_data["password"])  # Fix missing password
        user.full_clean()  # Should not raise error

        # Test invalid status
        user.status = "invalid"
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_user_role_choices(self):
        """Test user role choices validation"""
        user = User.objects.create(**self.user_data)
        user.set_password(self.user_data["password"])  # Fix missing password
        user.full_clean()  # Should not raise error

        # Test valid roles
        valid_roles = ["admin", "user", "viewer"]
        for role in valid_roles:
            user.role = role

            user.full_clean()  # Should not raise error

        # Test invalid role
        user.role = "invalid"
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_avatar_optional(self):
        """Test avatar field is optional"""
        user = User.objects.create(**self.user_data)
        self.assertIsNone(user.avatar.name)  # Fix: Check name instead of avatar

    def test_unique_email(self):
        """Test email uniqueness constraint"""
        User.objects.create(**self.user_data)

        duplicate_data = self.user_data.copy()
        duplicate_data["phone"] = "0987654321"  # Change phone to avoid conflict

        user = User(**duplicate_data)
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_phone_is_optional_and_not_unique(self):
        """Phone is currently a free-form, non-unique field."""
        User.objects.create(**self.user_data)

        duplicate_data = self.user_data.copy()
        duplicate_data["email"] = "other@example.com"

        # Should succeed — duplicate phones are allowed by the schema.
        second = User.objects.create(**duplicate_data)
        self.assertEqual(second.phone, self.user_data["phone"])

    def test_password_hashing(self):
        """Test password is properly hashed"""
        user = User.objects.create(**self.user_data)
        user.set_password("testpass123")
        user.save()

        self.assertNotEqual(user.password, "testpass123")
        self.assertTrue(user.check_password("testpass123"))

    def test_is_active_default(self):
        """New users are inactive until email verification completes."""
        user = User.objects.create(**self.user_data)
        self.assertFalse(user.is_active)

    def test_status_default(self):
        """Test status default value"""
        user = User.objects.create(**self.user_data)
        self.assertEqual(user.status, "active")

    def test_organisation_optional(self):
        """Test organisation field is optional"""
        data = self.user_data.copy()
        data.pop("organisation")  # Remove organisation field
        user = User.objects.create(**data)
        self.assertIsNone(user.organisation)

    def test_required_fields(self):
        """Only email is required at the model level (first_name and
        last_name are optional to support invitation-based signups
        where the invitee fills them in later)."""
        data = self.user_data.copy()
        data["email"] = None

        user = User(**data)
        with self.assertRaises(ValidationError):
            user.full_clean()



