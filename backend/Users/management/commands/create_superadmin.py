"""
Bootstrap command to create the first admin user.

Usage:
    # Interactive (recommended - secure password entry)
    python manage.py create_superadmin --email admin@company.com --org "My Company"
    
    # With password argument (less secure - visible in shell history)
    python manage.py create_superadmin --email admin@company.com --password Pass123 --org "My Company"
    
    # With environment variable (good for Docker/CI)
    ADMIN_PASSWORD=Pass123 python manage.py create_superadmin --email admin@company.com --org "My Company"
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
import getpass
import os

from Users.models import User
from Organisations.models import Organisations


class Command(BaseCommand):
    help = 'Create the first admin user and organisation for bootstrapping the application'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            required=True,
            help='Email address for the admin user'
        )
        parser.add_argument(
            '--password',
            type=str,
            required=False,
            help='Password for the admin user (optional - will prompt if not provided)'
        )
        parser.add_argument(
            '--org',
            type=str,
            required=True,
            help='Name of the organisation to create'
        )
        parser.add_argument(
            '--first-name',
            type=str,
            default='Admin',
            help='First name for the admin user (default: Admin)'
        )
        parser.add_argument(
            '--last-name',
            type=str,
            default='User',
            help='Last name for the admin user (default: User)'
        )
        parser.add_argument(
            '--website',
            type=str,
            default='',
            help='Website for the organisation (optional)'
        )

    def handle(self, *args, **options):
        email = options['email']
        org_name = options['org']
        first_name = options['first_name']
        last_name = options['last_name']
        website = options['website']
        
        # Get password from: argument > environment variable > prompt
        password = options.get('password')
        if not password:
            password = os.environ.get('ADMIN_PASSWORD')
        if not password:
            password = getpass.getpass('Enter admin password: ')
            password_confirm = getpass.getpass('Confirm admin password: ')
            if password != password_confirm:
                raise CommandError('Passwords do not match!')
        
        if len(password) < 8:
            raise CommandError('Password must be at least 8 characters long')
        
        # Check if user already exists
        if User.objects.filter(email=email).exists():
            raise CommandError(f'User with email {email} already exists!')
        
        try:
            with transaction.atomic():
                # Create or get organisation
                organisation, org_created = Organisations.objects.get_or_create(
                    name=org_name,
                    defaults={'website': website}
                )
                
                if org_created:
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Created organisation: {org_name}')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'! Organisation "{org_name}" already exists, using existing')
                    )
                
                # Create admin user with all required fields
                user = User(
                    email=email,
                    username=email.split('@')[0],  # Use email prefix as username
                    first_name=first_name,
                    last_name=last_name,
                    role='admin',
                    is_active=True,  # No email verification needed for bootstrap
                    organisation=organisation,
                    phone=''  # Optional field
                )
                user.set_password(password)
                user.save()
                
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Created admin user: {email}')
                )
                self.stdout.write('')
                self.stdout.write(
                    self.style.SUCCESS('=' * 50)
                )
                self.stdout.write(
                    self.style.SUCCESS('Bootstrap complete! You can now login with:')
                )
                self.stdout.write(f'  Email: {email}')
                self.stdout.write(f'  Organisation: {org_name}')
                self.stdout.write(
                    self.style.SUCCESS('=' * 50)
                )
                
        except Exception as e:
            raise CommandError(f'Failed to create admin user: {str(e)}')
