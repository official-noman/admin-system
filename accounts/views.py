"""
views.py

Combined module:
    1. UserRole   – role constants (single source of truth)
    2. Services   – all permission / business logic
    3. Views      – HTTP-layer only (request → service → response)
"""

import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CompanyProfileForm, DeviceForm, UserCreationFormCustom
from .models import CompanyProfile, Device

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

User = get_user_model()


# =============================================================================
# 1.  ENUMS  —  Role constants
# =============================================================================
class UserRole(models.TextChoices):
    """
    Role options — import এই class থেকে, bare string ব্যবহার করবেন না।

        if user.role == UserRole.ADMIN:
            ...
    """

    ROOT    = "root",    "Root"
    COMPANY = "company", "Company"
    ADMIN   = "admin",   "Admin"
    STAFF   = "staff",   "Staff"


# Mapping: creator role  →  (child role value, human-readable label)
_ROLE_HIERARCHY: dict[str, tuple[str, str]] = {
    UserRole.ROOT:    (UserRole.COMPANY, "Company"),
    UserRole.COMPANY: (UserRole.ADMIN,   "Admin"),
    UserRole.ADMIN:   (UserRole.STAFF,   "Staff"),
}


# =============================================================================
# 2.  SERVICES  —  Business / permission logic
# =============================================================================


class PermissionService:
    """Pure-function permission checks — কোনো DB write নেই।"""

    # -----------------------------------------------------------------
    # Can *viewer* see the profile of *target*?
    # -----------------------------------------------------------------
    @staticmethod
    def can_view_user(viewer, target) -> bool:
        """
        Allowed when viewer is:
            1. root (sees everything)
            2. the target itself
            3. the direct creator of target
            4. the grandparent creator (company → admin → staff)
        """
        if viewer.role == UserRole.ROOT:
            return True

        if viewer.id == target.id:
            return True

        if target.created_by_id == viewer.id:
            return True

        # Grandparent check: company user sees staff of their own admin
        if (
            viewer.role == UserRole.COMPANY
            and target.created_by
            and target.created_by.created_by_id == viewer.id
        ):
            return True

        return False

    # -----------------------------------------------------------------
    # Can *actor* delete *target*?
    # -----------------------------------------------------------------
    @staticmethod
    def can_delete_user(actor, target) -> bool:
        """
        Strict one-tier-down ownership:
            root    → delete company  (no ownership check)
            company → delete own admin
            admin   → delete own staff
        """
        allowed_pairs = {
            (UserRole.ROOT,    UserRole.COMPANY),
            (UserRole.COMPANY, UserRole.ADMIN),
            (UserRole.ADMIN,   UserRole.STAFF),
        }

        if (actor.role, target.role) not in allowed_pairs:
            return False

        if actor.role == UserRole.ROOT:
            return True

        return target.created_by_id == actor.id


class UserService:
    """User creation + listing logic."""

    @staticmethod
    def create_child_user(creator, form) -> str:
        """
        Form already validated হওয়া অবস্থায় এই method call করবেন।
        নতুন user save করে role label টা return করবে।
        """
        child_role, role_label = _ROLE_HIERARCHY[creator.role]

        new_user            = form.save(commit=False)
        new_user.role       = child_role
        new_user.created_by = creator
        new_user.is_staff   = True
        new_user.save()

        return role_label

    @staticmethod
    def label_for_child_role(creator_role: str) -> str:
        """'Company' | 'Admin' | 'Staff' — creator role অনুযায়ী।"""
        return _ROLE_HIERARCHY.get(creator_role, ("", "User"))[1]

    @staticmethod
    def get_child_users(current_user) -> tuple:
        """
        (QuerySet, title) return করে — role অনুযায়ী scope করা।

            root    → all companies
            company → own admins
            admin   → own staff
        """
        if current_user.role == UserRole.ROOT:
            qs    = User.objects.filter(role=UserRole.COMPANY)
            title = "All Registered Companies"

        elif current_user.role == UserRole.COMPANY:
            qs    = User.objects.filter(role=UserRole.ADMIN, created_by=current_user)
            title = "My Admins"

        else:  # admin
            qs    = User.objects.filter(role=UserRole.STAFF, created_by=current_user)
            title = "My Staff List"

        return qs.order_by("-date_joined"), title


class DeviceService:
    """Device creation + query."""

    @staticmethod
    def create_device(owner, form) -> "Device":
        device         = form.save(commit=False)
        device.company = owner
        device.save()
        return device

    @staticmethod
    def get_devices_for_owner(owner):
        return Device.objects.filter(company=owner)


# =============================================================================
# 3.  VIEWS  —  HTTP layer only
# =============================================================================


# -----------------------------------------------------------------------------
# 3-a.  CREATE USER
# -----------------------------------------------------------------------------
@login_required
def create_user_view(request: HttpRequest) -> HttpResponse:
    """
    Strict hierarchy: root → company → admin → staff.
    Target role is determined by the creator — request body influence করতে পারে না।
    """
    current_user = request.user

    if current_user.role == UserRole.STAFF:
        logger.warning("Permission denied — staff user %s tried to create a user.", current_user.id)
        messages.error(request, "Permission Denied.")
        return redirect("user_detail", user_id=current_user.id)

    if request.method == "POST":
        form = UserCreationFormCustom(request.POST)
        if form.is_valid():
            role_title = UserService.create_child_user(creator=current_user, form=form)
            messages.success(request, f"{role_title} created successfully!")
            logger.info("User %s (role=%s) created a new %s.", current_user.id, current_user.role, role_title)
            return redirect("all_users")
    else:
        form = UserCreationFormCustom()

    context = {
        "form":         form,
        "creating_role": UserService.label_for_child_role(current_user.role),
    }
    return render(request, "accounts/create_user.html", context)


# -----------------------------------------------------------------------------
# 3-b.  ALL USERS LIST
# -----------------------------------------------------------------------------
@login_required
def all_users_view(request: HttpRequest) -> HttpResponse:
    """Each role sees only the tier directly beneath it."""
    current_user = request.user

    if current_user.role == UserRole.STAFF:
        return redirect("user_detail", user_id=current_user.id)

    users_list, title = UserService.get_child_users(current_user)

    context = {
        "users":       users_list,
        "total_users": users_list.count(),
        "page_title":  title,
    }
    return render(request, "users/all_users.html", context)


# -----------------------------------------------------------------------------
# 3-c.  USER DETAIL
# -----------------------------------------------------------------------------
@login_required
def user_detail_view(request: HttpRequest, user_id: int) -> HttpResponse:
    """Profile দেখার permission PermissionService থেকে যাচাই করা হয়।"""
    target_user = get_object_or_404(User, id=user_id)

    if not PermissionService.can_view_user(request.user, target_user):
        logger.warning("Access denied — user %s tried to view profile of user %s.", request.user.id, target_user.id)
        messages.error(request, "Access Denied.")
        return redirect("home")

    return render(request, "users/user_detail.html", {"target_user": target_user})


# -----------------------------------------------------------------------------
# 3-d.  DELETE USER
# -----------------------------------------------------------------------------
@login_required
def delete_user_view(request: HttpRequest, user_id: int) -> HttpResponse:
    """GET → confirmation page | POST → delete (atomic)."""
    target_user = get_object_or_404(User, id=user_id)

    if not PermissionService.can_delete_user(request.user, target_user):
        logger.warning("Unauthorized delete — user %s on target %s.", request.user.id, target_user.id)
        messages.error(request, "Unauthorized action.")
        return redirect("all_users")

    if request.method == "POST":
        with transaction.atomic():
            target_user.delete()

        logger.info("User %s deleted user %s.", request.user.id, target_user.id)
        messages.success(request, "User deleted.")
        return redirect("all_users")

    return render(request, "users/confirm_delete.html", {"target_user": target_user})


# -----------------------------------------------------------------------------
# 3-e.  ALL ADMINS  (root only)
# -----------------------------------------------------------------------------
@login_required
def all_admins_view(request: HttpRequest) -> HttpResponse:
    """Global admin list — শুধু root দেখতে পারবে।"""
    if request.user.role != UserRole.ROOT:
        logger.warning("Non-root user %s tried to access all_admins_view.", request.user.id)
        return redirect("home")

    admins = User.objects.filter(role=UserRole.ADMIN).order_by("-date_joined")

    context = {
        "users":       admins,
        "total_users": admins.count(),
        "page_title":  "All System Admins",
    }
    return render(request, "users/all_users.html", context)


# -----------------------------------------------------------------------------
# 3-f.  DASHBOARD HOME
# -----------------------------------------------------------------------------
@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    """Role অনুযায়ী সঠিক dashboard template render করে।"""
    DASHBOARD_MAP = {
        UserRole.ROOT:    "dashboards/root_dashboard.html",
        UserRole.COMPANY: "dashboards/company_dashboard.html",
        UserRole.ADMIN:   "dashboards/admin_dashboard.html",
        UserRole.STAFF:   "dashboards/staff_dashboard.html",
    }

    template = DASHBOARD_MAP.get(request.user.role, "index.html")
    return render(request, template)


# -----------------------------------------------------------------------------
# 3-g.  COMPANY PROFILE (edit)
# -----------------------------------------------------------------------------
@login_required
def edit_company_profile(request: HttpRequest) -> HttpResponse:
    """শুধু company role নিজের profile আপডেট করতে পারবে।"""
    if request.user.role != UserRole.COMPANY:
        messages.error(request, "Access Denied.")
        return redirect("home")

    profile = CompanyProfile.objects.get_or_create(user=request.user)[0]

    if request.method == "POST":
        form = CompanyProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Company profile updated successfully!")
            logger.info("Company profile updated — user %s.", request.user.id)
            return redirect("edit_company_profile")

        messages.error(request, "Error updating profile. Please check the form.")
    else:
        form = CompanyProfileForm(instance=profile)

    return render(request, "accounts/edit_company_profile.html", {"form": form})


# -----------------------------------------------------------------------------
# 3-h.  DEVICE  —  Add / List / Edit
# -----------------------------------------------------------------------------
@login_required
def add_device(request: HttpRequest) -> HttpResponse:
    """শুধু company role device যোগ করতে পারবে।"""
    if request.user.role != UserRole.COMPANY:
        messages.error(request, "Only company accounts can add devices.")
        return redirect("home")

    if request.method == "POST":
        form = DeviceForm(request.POST)
        if form.is_valid():
            DeviceService.create_device(owner=request.user, form=form)
            logger.info("Device created by company user %s.", request.user.id)
            return redirect("device_list")
    else:
        form = DeviceForm()

    return render(request, "devices/add_device.html", {"form": form})


@login_required
def device_list(request: HttpRequest) -> HttpResponse:
    """Current user এর নিজের devices তালিকা।"""
    devices = DeviceService.get_devices_for_owner(request.user)
    return render(request, "devices/device_list.html", {"devices": devices})


@login_required
def edit_device(request: HttpRequest, device_id: int) -> HttpResponse:
    """
    get_object_or_404 এ company=request.user দেওয়া আছে —
    তাই অন্য কেউ নিজের device না হলে edit করতে পারবে না.
    """
    device = get_object_or_404(Device, id=device_id, company=request.user)

    if request.method == "POST":
        form = DeviceForm(request.POST, instance=device)
        if form.is_valid():
            form.save()
            logger.info("Device %s updated by user %s.", device.id, request.user.id)
            return redirect("device_list")
    else:
        form = DeviceForm(instance=device)

    return render(request, "devices/add_device.html", {"form": form, "edit_mode": True})