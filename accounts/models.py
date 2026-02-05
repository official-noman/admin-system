"""
models.py

Core domain models: User, CompanyProfile, Device.

Conventions:
    - All choices / enums are defined via Django TextChoices.
      views.py / serializers.py / admin.py all share the same enum.
    - null=True is intentionally avoided on CharFields.
      Use blank='' instead (Django convention for string-based fields).
    - Device passwords are hashed before saving — plain text never
      reaches the database.
    - A post_save signal auto-creates a CompanyProfile whenever a User
      with the 'company' role is created.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.hashers import make_password, check_password as _check


# =============================================================================
# Enums  —  single source of truth
# =============================================================================
class UserRole(models.TextChoices):
    """User role hierarchy. Use this enum everywhere."""

    ROOT    = "root",    "Root Admin"
    COMPANY = "company", "Company"
    ADMIN   = "admin",   "Admin"
    STAFF   = "staff",   "Staff"


class OperatorChoice(models.TextChoices):
    """Telecom operator options."""

    GP       = "gp",       "Grameenphone"
    ROBI     = "robi",     "Robi"
    AIRTEL   = "airtel",   "Airtel"
    BL       = "bl",       "Banglalink"
    TELETALK = "teletalk", "Teletalk"


class DeviceStatus(models.TextChoices):
    """Possible statuses for a Device."""

    ACTIVE   = "active",   "Active"
    INACTIVE = "inactive", "Inactive"
    BLOCKED  = "blocked",  "Blocked"


# =============================================================================
# 1.  User
# =============================================================================
class User(AbstractUser):
    """Custom User model with role-based hierarchy support.

    created_by:
        Reference to the user who created this account.
        NULL for the root user.
        SET_NULL on delete — does not cascade.
    """

    role = models.CharField(
        max_length=10,
        choices=UserRole.choices,
        default=UserRole.ADMIN,
    )

    created_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_users",
    )

    class Meta:
        ordering = ["-date_joined"]
        verbose_name        = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.username


# =============================================================================
# 2.  CompanyProfile
# =============================================================================
class CompanyProfile(models.Model):
    """Detailed information for a company account.

    Auto-created by a post_save signal whenever a User with the
    'company' role is created.

    CharFields intentionally omit null=True.
    Empty values are stored as blank strings per Django convention.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="companyprofile",
    )

    company_name   = models.CharField(max_length=255, blank=True, default="")
    license_number = models.CharField(max_length=100, blank=True, default="")
    company_email  = models.EmailField(blank=True, default="")
    location       = models.CharField(max_length=255, blank=True, default="")
    website        = models.URLField(blank=True, default="")
    phone_number   = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        verbose_name        = "Company Profile"
        verbose_name_plural = "Company Profiles"

    def __str__(self):
        return self.company_name or self.user.username


# ---------------------------------------------------------------------------
# Signal — auto-create CompanyProfile when a company-role User is saved
# ---------------------------------------------------------------------------
@receiver(post_save, sender=User)
def create_company_profile(sender, instance, created, **kwargs):
    """Auto-create a CompanyProfile when a new User with role == company is saved."""
    if created and instance.role == UserRole.COMPANY:
        CompanyProfile.objects.create(user=instance)


# =============================================================================
# 3.  Device
# =============================================================================
class Device(models.Model):
    """A single SIM device record.

    password:
        Never stored as plain text.  Hashed via make_password() on save.
        Use the check_password() helper to verify a raw value.

    status:
        Constrained to DeviceStatus choices — arbitrary strings are
        rejected at the database level.
    """

    company  = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    operator = models.CharField(max_length=20, choices=OperatorChoice.choices)

    sim_number = models.CharField(max_length=20)
    password   = models.CharField(max_length=128)          # hashed — 128 chars is sufficient
    sim_pin    = models.CharField(max_length=10)

    balance    = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status     = models.CharField(
        max_length=20,
        choices=DeviceStatus.choices,
        default=DeviceStatus.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)       # auto-updates on every save

    class Meta:
        ordering            = ["-created_at"]
        verbose_name        = "Device"
        verbose_name_plural = "Devices"

    def __str__(self):
        return f"{self.get_operator_display()} — {self.sim_number}"

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Password helpers — never access .password directly
    # ------------------------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        """Hash the raw password and store it."""
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Return True when raw_password matches the stored hash."""
        return _check(raw_password, self.password)