from django.db import models
from django.db.models.functions import Lower
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from model_utils import Choices
from Organisations.models import Organisations


class SeropsUserManager(UserManager):
    """Custom manager so `createsuperuser` produces a usable admin.

    Two guarantees for ops running `python manage.py createsuperuser`
    per the quick-start docs:

      * ``is_active=True`` (E1-1, 2026-09-09) — the User model overrides
        Django's default with False for the email-verification signup
        gate. Without this override, the fresh superuser can't log in
        with "account not activated".

      * ``organisation`` auto-provisioned (E1-4, 2026-09-09) — the whole
        product is multi-tenant, so every model FK's off ``organisation``.
        A superuser with ``organisation=None`` hard-crashes the
        onboarding endpoint on first login. If the caller doesn't
        supply an org, we create a bootstrap "<Admin>'s Organisation"
        and attach the superuser + set role=admin.
    """

    @classmethod
    def normalize_email(cls, email):
        """The whole address lowercase, not only the domain (audit
        2026-11-20, item 8)."""
        from Users.emails import normalize_email
        return normalize_email(email)

    def get_by_natural_key(self, username):
        """Sign-in by email whatever its case."""
        return self.get(**{f'{self.model.USERNAME_FIELD}__iexact': username})

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_active", True)
        # Role must be `admin` for the RBAC middleware to grant write
        # access — otherwise the superuser lands with the default
        # `viewer` role and can browse but can't configure anything.
        extra_fields.setdefault("role", "admin")

        organisation = extra_fields.pop("organisation", None)
        user = super().create_superuser(
            username=username, email=email, password=password, **extra_fields
        )

        # Auto-provision a bootstrap org if the caller didn't pass one.
        # Uses the email local-part for the slug so re-running
        # `createsuperuser` for the same person doesn't collide.
        if organisation is None and user.organisation_id is None:
            slug_seed = (email or username or f"admin-{user.pk}").split("@")[0].lower()
            slug_seed = "".join(c if c.isalnum() or c == "-" else "-" for c in slug_seed)[:40]
            org, _ = Organisations.objects.get_or_create(
                slug=slug_seed,
                defaults={"name": f"{slug_seed.title()}'s Organisation"},
            )
            user.organisation = org
            user.save(update_fields=["organisation"])

        return user


class User(AbstractUser):
    username=models.CharField(max_length=20,unique=False,default="user")
    first_name = models.CharField(max_length=255, blank=True, default='')  # Optional for invitation
    last_name = models.CharField(max_length=255, blank=True, default='')  # Optional for invitation
    email = models.CharField(unique=True,max_length=255)
    password = models.CharField(unique=False,null=True,max_length=255)
    phone = models.CharField(unique=False,null=True,blank=True,max_length=255)  # Not unique, optional
    # A small PNG, stored in the database (see Utils/images.py). It is
    # served without authentication (an <img> cannot send the token) at
    # /api/auth/avatar/<avatar_key>; the key is random and changes on
    # every upload, so the URL cannot be guessed and can be cached forever.
    avatar_png = models.BinaryField(null=True, blank=True, editable=False)
    avatar_key = models.CharField(max_length=32, blank=True, default='', db_index=True)
    STATUS = Choices('active','suspended','disabled')
    status = models.CharField(choices=STATUS,null=False,default=STATUS.active,max_length=255)
    # 'custom' means the permissions of ``custom_role`` (Middlewares/rbac.py).
    ROLE = Choices('viewer', 'user', 'admin', 'custom')
    role = models.CharField(choices=ROLE, default=ROLE.viewer, max_length=255)
    is_active = models.BooleanField(default=False)
    organisation = models.ForeignKey(Organisations,null=True,blank=True,on_delete=models.CASCADE)
    custom_role = models.ForeignKey(
        'CustomRole', null=True, blank=True, on_delete=models.PROTECT, related_name='members')
    
    # Password tracking for expiry
    password_changed_at = models.DateTimeField(null=True, blank=True)
    password_policy_warning_dismissed = models.BooleanField(default=False)

    # Marks a user as the public demo identity. Demo users are read-only
    # at the application layer (see Middlewares.DemoUserMiddleware) on
    # top of whatever their RBAC role permits — typically `viewer`. They
    # cannot mutate data, send chat messages, or modify settings.
    is_demo = models.BooleanField(
        default=False,
        db_index=True,
        help_text='True for the public demo user; blocked from all writes.',
    )
    
    def save(self, *args, **kwargs):
        """Override save to enforce role validation and store the email
        lowercase (every write path: sign-up, invitation, SSO, SCIM, email
        change, createsuperuser)."""
        if self.email:
            from Users.emails import normalize_email
            self.email = normalize_email(self.email)
        if self.role and self.role not in [r[0] for r in self.ROLE]:
            raise ValidationError(f"Invalid role: '{self.role}'. Valid roles are: {', '.join([r[0] for r in self.ROLE])}")
        if self.role == 'custom':
            if self.custom_role_id is None or self.custom_role.organisation_id != self.organisation_id:
                raise ValidationError("A custom role must be one of the user's organisation")
        else:
            self.custom_role = None
        super().save(*args, **kwargs)

    # Custom manager to fix createsuperuser vs is_active-default clash (E1-1).
    objects = SeropsUserManager()

    class Meta:
        db_table = 'Users'
        # One account per address whatever its case (audit 2026-11-20,
        # item 8). Migration 0018 refuses to add it while case duplicates
        # exist, and lists them.
        constraints = [
            models.UniqueConstraint(Lower('email'), name='users_email_lower_unique'),
        ]

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = [
        'username',
        ]  # first_name, last_name no longer required
    
    def __str__(self):
        """Return the user's full name"""
        return f"{self.first_name} {self.last_name}"


class CustomRole(models.Model):
    """A role an organisation builds from the permission catalogue."""
    organisation = models.ForeignKey(Organisations, on_delete=models.CASCADE, related_name='custom_roles')
    name = models.CharField(max_length=50)
    description = models.CharField(max_length=255, blank=True, default='')
    # Permission codes (Middlewares/rbac.py), normalised on save by the API.
    permissions = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'custom_role'
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['organisation', 'name'], name='custom_role_unique_name')]

    def __str__(self):
        return f"{self.name} ({self.organisation_id})"

    @property
    def key(self):
        return f'custom:{self.pk}'


class SecuritySettings(models.Model):
    """Organization-level security settings"""
    
    organisation = models.OneToOneField(
        Organisations, 
        on_delete=models.CASCADE,
        related_name='security_settings'
    )
    
    # Password policy: NOT USED. Nothing reads these columns; the screen and
    # the API no longer show them (audit 2026-11-20, item 17). Passwords are
    # checked by AUTH_PASSWORD_VALIDATORS (api/settings.py). Kept to avoid a
    # migration; enforcing a configurable policy is on the after-launch list.
    min_password_length = models.IntegerField(default=8)
    require_uppercase = models.BooleanField(default=True)
    require_lowercase = models.BooleanField(default=True)
    require_numbers = models.BooleanField(default=True)
    require_special_chars = models.BooleanField(default=False)
    password_expiry_days = models.IntegerField(default=0)  # 0 = never expires
    
    # Session Management
    SESSION_TIMEOUT_CHOICES = [
        (30, '30 minutes'),
        (60, '1 hour'),
        (240, '4 hours'),
        (480, '8 hours'),
        (1440, '24 hours'),
        (0, 'Never'),
    ]
    session_timeout_minutes = models.IntegerField(
        choices=SESSION_TIMEOUT_CHOICES,
        default=480  # 8 hours
    )
    
    # SSO: OpenID Connect (Community), or SAML 2.0 (Enterprise, feature
    # "saml", configured in backend/ee/saml). The group mapping below
    # serves both.
    SSO_TYPES = [
        ('none', 'Disabled'),
        ('oidc', 'OpenID Connect (OIDC)'),
        ('saml', 'SAML 2.0'),
    ]
    sso_enabled = models.BooleanField(default=False)
    sso_provider = models.CharField(max_length=50, choices=SSO_TYPES, default='none')
    # Members sign in only through SSO: password sign-in is refused for
    # them, except for the organisation's admins (a way back in when the
    # identity provider is down or misconfigured). Applies only while the
    # SSO above can actually be used (on, and licensed for SAML).
    sso_enforced = models.BooleanField(default=False)

    sso_client_id = models.CharField(max_length=255, blank=True, null=True, help_text="OIDC Client ID")
    sso_client_secret_encrypted = models.TextField(blank=True, null=True)
    sso_discovery_url = models.URLField(blank=True, null=True, help_text="OIDC Discovery URL")
    # Email domains whose people sign in with this organisation's SSO even
    # before they have an account: it is created at the first sign-in, and
    # only for these domains. On installs with several organisations only
    # platform staff set them (they route sign-ins install-wide).
    sso_domains = models.JSONField(
        default=list, blank=True,
        help_text="Email domains (example.com) that may sign in with SSO without an invitation",
    )

    # Roles from the identity provider's groups (Users/sso_roles.py).
    # The claim is a dotted path into the userinfo / ID token claims, e.g.
    # "groups" (Okta, Keycloak with a group mapper, Entra ID) or
    # "realm_access.roles" (Keycloak realm roles). With SAML it is the
    # name of the assertion attribute that lists the groups, taken whole
    # (Entra ID: http://schemas.microsoft.com/ws/2008/06/identity/claims/groups).
    sso_groups_claim = models.CharField(max_length=255, blank=True, default='groups')
    # Scopes requested on top of "openid email profile" (e.g. "groups").
    sso_extra_scopes = models.CharField(max_length=255, blank=True, default='')
    # Ordered rules [{"group": "...", "role": "..."}]: the first rule whose
    # group the user is in sets the role.
    sso_role_mappings = models.JSONField(default=list, blank=True)
    # Role when no rule matches; "deny" refuses the sign-in.
    sso_default_role = models.CharField(max_length=64, default='viewer')
    # Re-apply the rules at every sign-in (the identity provider decides),
    # rather than only when the account is created.
    sso_sync_role = models.BooleanField(default=False)
    # [{"group": "...", "team_id": 3}]: members of the group are put in the
    # team at each sign-in (and taken out when they leave the group). Only
    # memberships SSO added are removed.
    sso_team_mappings = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'security_settings'
        verbose_name = 'Security Settings'
        verbose_name_plural = 'Security Settings'
    
    def __str__(self):
        return f"Security Settings for {self.organisation.name}"

    def set_client_secret(self, raw_secret):
        """Encrypt and store the client secret."""
        from Utils import crypto
        self.sso_client_secret_encrypted = crypto.encrypt(raw_secret) if raw_secret else None

    def get_client_secret(self):
        """The client secret, or None if there is none or it cannot be read (crypto logs which)."""
        from Utils import crypto
        if not self.sso_client_secret_encrypted:
            return None
        try:
            return crypto.decrypt(self.sso_client_secret_encrypted)
        except crypto.DecryptionError:
            return None

    def validate_password(self, password):
        """
        Validate a password against NIST-compliant policy.
        Fixed minimum 8 characters (no configurable complexity).
        Returns (is_valid, error_messages)
        """
        MIN_LENGTH = 8
        MAX_LENGTH = 128
        errors = []
        
        if len(password) < MIN_LENGTH:
            errors.append(f"Password must be at least {MIN_LENGTH} characters")
        
        if len(password) > MAX_LENGTH:
            errors.append(f"Password must be {MAX_LENGTH} characters or less")
        
        return (len(errors) == 0, errors)
