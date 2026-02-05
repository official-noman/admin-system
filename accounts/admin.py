"""
admin.py

Django admin registration for User and CompanyProfile.

Design decisions:
    - CompanyProfile is shown as a StackedInline *inside* the User admin.
      This keeps the workflow in one place: open a User → see their profile
      right below.  A *separate* CompanyProfileAdmin is also registered so
      that the profile list is independently browsable / searchable.
    - get_company_name is wired into list_display so the company name is
      visible directly on the User list page (no extra click).
    - list_select_related is set on both admins to prevent N+1 queries
      when Django renders the list page.
    - created_by is read-only on the add form because it is set
      automatically by the view layer — exposing it as an editable
      dropdown would be confusing and could allow privilege escalation.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CompanyProfile, User


# =============================================================================
# Inline — CompanyProfile inside the User change page
# =============================================================================
class CompanyProfileInline(admin.StackedInline):
    """Show the related CompanyProfile directly on the User form.

    readonly_fields prevents accidental edits from the admin panel;
    the company user manages their own profile through the app UI.
    """

    model               = CompanyProfile
    can_delete          = False
    verbose_name_plural = "Company Profile"
    fk_name             = "user"
    readonly_fields     = [
        "company_name",
        "license_number",
        "company_email",
        "location",
        "website",
        "phone_number",
    ]


# =============================================================================
# CustomUserAdmin
# =============================================================================
class CustomUserAdmin(UserAdmin):
    """Extended User admin with role awareness and company-name display."""

    model = User

    # ------------------------------------------------------------------
    # List page
    # ------------------------------------------------------------------
    list_display        = ["username", "email", "role", "is_staff", "get_company_name", "created_by"]
    list_filter         = ["role", "is_staff", "is_active"]
    search_fields       = ["username", "email"]
    ordering            = ["-date_joined"]
    list_select_related = ["created_by", "companyprofile"]

    # ------------------------------------------------------------------
    # Inline — profile shown on the same page as the user
    # ------------------------------------------------------------------
    inlines = [CompanyProfileInline]

    # ------------------------------------------------------------------
    # Detail / edit page  — fieldsets
    # ------------------------------------------------------------------
    fieldsets = UserAdmin.fieldsets + (
        ("Role & Ownership", {"fields": ("role", "created_by")}),
    )

    # created_by is auto-set by the view; make it read-only so admins
    # cannot accidentally (or maliciously) reassign ownership.
    readonly_fields = ["created_by"]

    # ------------------------------------------------------------------
    # Add page  — created_by is irrelevant here (will be None or set
    # by the view), so we omit it entirely from the add form.
    # ------------------------------------------------------------------
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Role", {"fields": ("role",)}),
    )

    # ------------------------------------------------------------------
    # Custom column: pull company_name from the related profile
    # ------------------------------------------------------------------
    def get_company_name(self, obj):
        """Return the company name if a CompanyProfile exists, else a dash."""
        try:
            return obj.companyprofile.company_name or "-"
        except CompanyProfile.DoesNotExist:
            return "-"

    get_company_name.short_description = "Company Name"


# =============================================================================
# CompanyProfileAdmin  —  standalone list / search for profiles
# =============================================================================
@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    """Standalone admin for CompanyProfile — useful for global searches."""

    list_display        = ["user", "company_name", "company_email", "phone_number", "location"]
    search_fields       = ["company_name", "company_email", "user__username"]
    list_filter         = ["location"]
    ordering            = ["company_name"]
    list_select_related = ["user"]


# =============================================================================
# Register
# =============================================================================
admin.site.register(User, CustomUserAdmin)