"""
views.py
Combined module for Django views following service-oriented architecture.
Organized into three main sections:
    1. Constants and Configurations
    2. Services - Business logic and permissions
    3. Views - HTTP request handlers
"""
import json
import logging
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CompanyProfileForm, DeviceForm, UserCreationFormCustom
from .models import CompanyProfile, Device, UserRole 
from .services.playwright_login import get_operator_session
from .services.playwright_manager import PlaywrightSessionManager


logger = logging.getLogger(__name__)
User = get_user_model()


# =============================================================================
# SECTION 1: CONSTANTS AND CONFIGURATIONS
# =============================================================================

ROLE_HIERARCHY: dict[str, tuple[str, str]] = {
    UserRole.ROOT: (UserRole.COMPANY, "Company"),
    UserRole.COMPANY: (UserRole.ADMIN, "Admin"),
    UserRole.ADMIN: (UserRole.STAFF, "Staff"),
}

OPERATOR_LOGIN_URLS = {
    'gp': 'https://www.grameenphone.com/personal/login',
    'robi': 'https://www.robi.com.bd/en/personal/my-robi',
    'banglalink': 'https://www.banglalink.net/en/login',
}

DASHBOARD_TEMPLATES = {
    UserRole.ROOT: "dashboards/root_dashboard.html",
    UserRole.COMPANY: "dashboards/company_dashboard.html",
    UserRole.ADMIN: "dashboards/admin_dashboard.html",
    UserRole.STAFF: "dashboards/staff_dashboard.html",
}


# =============================================================================
# SECTION 2: SERVICES
# =============================================================================

class PermissionService:
    """
    Permission validation service.
    Contains pure functions for authorization checks without side effects.
    """
    
    @staticmethod
    def can_view_user(viewer, target) -> bool:
        """
        Determine if viewer has permission to view target user's profile.
        
        Args:
            viewer: User attempting to view
            target: User being viewed
            
        Returns:
            bool: True if access is allowed
        """
        if viewer.role == UserRole.ROOT:
            return True
        if viewer.id == target.id:
            return True
        if target.created_by_id == viewer.id:
            return True
        if (
            viewer.role == UserRole.COMPANY
            and target.created_by
            and target.created_by.created_by_id == viewer.id
        ):
            return True
        return False

    @staticmethod
    def can_delete_user(actor, target) -> bool:
        """
        Determine if actor has permission to delete target user.
        
        Args:
            actor: User attempting deletion
            target: User being deleted
            
        Returns:
            bool: True if deletion is allowed
        """
        allowed_pairs = {
            (UserRole.ROOT, UserRole.COMPANY),
            (UserRole.COMPANY, UserRole.ADMIN),
            (UserRole.ADMIN, UserRole.STAFF),
        }
        if (actor.role, target.role) not in allowed_pairs:
            return False
        if actor.role == UserRole.ROOT:
            return True
        return target.created_by_id == actor.id


class UserService:
    """User management service for creation and querying operations."""
    
    @staticmethod
    def create_child_user(creator, form) -> str:
        """
        Create a new user one tier below the creator in the hierarchy.
        
        Args:
            creator: User creating the new account
            form: Validated UserCreationFormCustom instance
            
        Returns:
            str: Human-readable role label of created user
        """
        child_role, role_label = ROLE_HIERARCHY[creator.role]
        new_user = form.save(commit=False)
        new_user.role = child_role
        new_user.created_by = creator
        new_user.is_staff = True
        new_user.save()
        return role_label

    @staticmethod
    def label_for_child_role(creator_role: str) -> str:
        """
        Get human-readable label for the role that creator can create.
        
        Args:
            creator_role: Role of the creating user
            
        Returns:
            str: Label like 'Company', 'Admin', or 'Staff'
        """
        return ROLE_HIERARCHY.get(creator_role, ("", "User"))[1]

    @staticmethod
    def get_child_users(current_user) -> tuple:
        """
        Retrieve users in the tier directly below current user.
        
        Args:
            current_user: User requesting the list
            
        Returns:
            tuple: (QuerySet, title string)
        """
        if current_user.role == UserRole.ROOT:
            qs = User.objects.filter(role=UserRole.COMPANY)
            title = "All Registered Companies"
        elif current_user.role == UserRole.COMPANY:
            qs = User.objects.filter(role=UserRole.ADMIN, created_by=current_user)
            title = "My Admins"
        else:
            qs = User.objects.filter(role=UserRole.STAFF, created_by=current_user)
            title = "My Staff List"
        return qs.order_by("-date_joined"), title


class DeviceService:
    """Device management service for CRUD and connection operations."""
    
    @staticmethod
    def create_device(owner, form) -> "Device":
        """
        Create a new device for the specified owner.
        
        Args:
            owner: User who owns the device
            form: Validated DeviceForm instance
            
        Returns:
            Device: Created device instance
        """
        device = form.save(commit=False)
        device.company = owner
        device.save()
        return device

    @staticmethod
    def get_devices_for_owner(owner):
        """
        Retrieve all devices belonging to specified owner.
        
        Args:
            owner: User who owns the devices
            
        Returns:
            QuerySet: Filtered device queryset
        """
        return Device.objects.filter(company=owner)

    @staticmethod
    def connect_device_session(device, otp: str) -> dict:
        """
        Initiate Playwright automation to establish and save device session.
        
        This method:
            1. Determines operator login URL
            2. Executes Playwright automation
            3. Saves session data to device
            4. Returns standardized result dictionary
        
        Args:
            device: Device instance to connect
            otp: One-time password for authentication
            
        Returns:
            dict: Contains 'status', 'message', and 'status_code' keys
        """
        operator_url = OPERATOR_LOGIN_URLS.get(device.operator)
        
        if not operator_url:
            return {
                'status': 'error',
                'message': f'Operator URL not found for "{device.operator}".',
                'status_code': 404
            }
        
        try:
            session_data_json = get_operator_session(
                operator_url=operator_url,
                sim_number=device.sim_number,
                otp=otp
            )
            
            if session_data_json:
                device.session_data = session_data_json
                device.save(update_fields=['session_data'])
                logger.info("Playwright session established for device %s.", device.id)
                return {
                    'status': 'success',
                    'message': 'Device connected successfully and session saved.',
                    'status_code': 200
                }
            else:
                logger.error("Playwright automation failed for device %s.", device.id)
                return {
                    'status': 'error',
                    'message': 'Failed to connect. The automation may have failed (e.g., incorrect OTP).',
                    'status_code': 500
                }
        
        except Exception as e:
            logger.exception("Unexpected error during Playwright execution for device %s.", device.id)
            return {
                'status': 'error',
                'message': f'An unexpected error occurred: {str(e)}',
                'status_code': 500
            }


# =============================================================================
# SECTION 3: VIEWS
# =============================================================================

@login_required
def create_user_view(request: HttpRequest) -> HttpResponse:
    """
    Create a new user one tier below current user in hierarchy.
    
    Hierarchy: root → company → admin → staff
    Target role is determined by creator's role.
    """
    current_user = request.user
    
    if current_user.role == UserRole.STAFF:
        logger.warning("Permission denied - staff user %s attempted user creation.", current_user.id)
        messages.error(request, "Permission Denied.")
        return redirect("user_detail", user_id=current_user.id)
    
    if request.method == "POST":
        form = UserCreationFormCustom(request.POST)
        if form.is_valid():
            role_title = UserService.create_child_user(creator=current_user, form=form)
            messages.success(request, f"{role_title} created successfully!")
            logger.info("User %s (role=%s) created new %s.", current_user.id, current_user.role, role_title)
            return redirect("all_users")
    else:
        form = UserCreationFormCustom()
    
    context = {
        "form": form,
        "creating_role": UserService.label_for_child_role(current_user.role),
    }
    return render(request, "accounts/create_user.html", context)


@login_required
def all_users_view(request: HttpRequest) -> HttpResponse:
    """Display list of users in tier directly below current user."""
    current_user = request.user
    
    if current_user.role == UserRole.STAFF:
        return redirect("user_detail", user_id=current_user.id)
    
    users_list, title = UserService.get_child_users(current_user)
    
    context = {
        "users": users_list,
        "total_users": users_list.count(),
        "page_title": title,
    }
    return render(request, "users/all_users.html", context)


@login_required
def user_detail_view(request: HttpRequest, user_id: int) -> HttpResponse:
    """
    Display detailed user profile.
    Access control enforced via PermissionService.
    """
    target_user = get_object_or_404(User, id=user_id)
    
    if not PermissionService.can_view_user(request.user, target_user):
        logger.warning("Access denied - user %s attempted to view user %s.", request.user.id, target_user.id)
        messages.error(request, "Access Denied.")
        return redirect("home")
    
    return render(request, "users/user_detail.html", {"target_user": target_user})


@login_required
def delete_user_view(request: HttpRequest, user_id: int) -> HttpResponse:
    """
    Delete user with confirmation.
    GET: Show confirmation page
    POST: Execute deletion within atomic transaction
    """
    target_user = get_object_or_404(User, id=user_id)
    
    if not PermissionService.can_delete_user(request.user, target_user):
        logger.warning("Unauthorized deletion attempt - user %s targeting user %s.", request.user.id, target_user.id)
        messages.error(request, "Unauthorized action.")
        return redirect("all_users")
    
    if request.method == "POST":
        with transaction.atomic():
            target_user.delete()
        
        logger.info("User %s deleted user %s.", request.user.id, target_user.id)
        messages.success(request, "User deleted successfully.")
        return redirect("all_users")
    
    return render(request, "users/confirm_delete.html", {"target_user": target_user})


@login_required
def all_admins_view(request: HttpRequest) -> HttpResponse:
    """
    Display global admin list.
    Restricted to root users only.
    """
    if request.user.role != UserRole.ROOT:
        logger.warning("Non-root user %s attempted to access admin list.", request.user.id)
        return redirect("home")
    
    admins = User.objects.filter(role=UserRole.ADMIN).order_by("-date_joined")
    
    context = {
        "users": admins,
        "total_users": admins.count(),
        "page_title": "All System Admins",
    }
    return render(request, "users/all_users.html", context)


@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    """Render role-appropriate dashboard."""
    template = DASHBOARD_TEMPLATES.get(request.user.role, "index.html")
    return render(request, template)


@login_required
def edit_company_profile(request: HttpRequest) -> HttpResponse:
    """
    Edit company profile information.
    Restricted to users with company role.
    """
    if request.user.role != UserRole.COMPANY:
        messages.error(request, "Access Denied.")
        return redirect("home")
    
    profile = CompanyProfile.objects.get_or_create(user=request.user)[0]
    
    if request.method == "POST":
        form = CompanyProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Company profile updated successfully!")
            logger.info("Company profile updated - user %s.", request.user.id)
            return redirect("edit_company_profile")
        messages.error(request, "Error updating profile. Please check the form.")
    else:
        form = CompanyProfileForm(instance=profile)
    
    return render(request, "accounts/edit_company_profile.html", {"form": form})


@login_required
def add_device(request: HttpRequest) -> HttpResponse:
    """
    Add new device.
    Restricted to users with company role.
    """
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
    """Display list of devices owned by current user."""
    devices = DeviceService.get_devices_for_owner(request.user)
    return render(request, "devices/device_list.html", {"devices": devices})


@login_required
def edit_device(request: HttpRequest, device_id: int) -> HttpResponse:
    """
    Edit device information.
    Ownership verified via get_object_or_404 filter.
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


@login_required
def send_otp_view(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Initiate OTP login flow for device.
    Opens browser and navigates to operator login page.
    
    Args:
        device_id: ID of the device to connect
        
    Returns:
        JsonResponse with status and message
    """
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    operator_url = OPERATOR_LOGIN_URLS.get(device.operator)
    if not operator_url:
        return JsonResponse({
            'status': 'error',
            'message': f'Operator URL not found for "{device.operator}".'
        }, status=404)

    success, message = PlaywrightSessionManager.start_login_flow(
        device_id=device.id,
        operator_url=operator_url,
        sim_number=device.sim_number
    )

    if success:
        return JsonResponse({'status': 'success', 'message': message})
    else:
        return JsonResponse({'status': 'error', 'message': message}, status=500)


@login_required
def verify_otp_view(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Complete OTP login flow by verifying the OTP code.
    Updates device session data and balance if successful.
    
    Query Parameters:
        otp: One-time password received by user
    
    Args:
        device_id: ID of the device being connected
        
    Returns:
        JsonResponse with status, message, and updated device data
    """
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    otp = request.GET.get('otp')
    if not otp:
        return JsonResponse({
            'status': 'error',
            'message': 'OTP is required.'
        }, status=400)

    success, result = PlaywrightSessionManager.complete_login_flow(
        device_id=device.id,
        otp=otp
    )

    if success:
        try:
            data = json.loads(result)
            
            if 'session' in data:
                device.session_data = json.dumps(data['session'])
            
            if 'balance' in data:
                try:
                    device.balance = float(data['balance'])
                except (ValueError, TypeError):
                    logger.warning("Failed to parse balance for device %s.", device.id)
            
            device.status = 'Active'
            device.save()
            
            logger.info("Device %s connected successfully with balance update.", device.id)
            return JsonResponse({
                'status': 'success',
                'message': 'Device connected successfully and balance updated!'
            })
        
        except json.JSONDecodeError:
            device.session_data = result
            device.status = 'Active'
            device.save()
            
            logger.info("Device %s connected successfully.", device.id)
            return JsonResponse({
                'status': 'success',
                'message': 'Device connected successfully!'
            })
    else:
        return JsonResponse({
            'status': 'error',
            'message': f'Failed to connect: {result}'
        }, status=500)


@login_required
def connect_device_view(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Legacy single-step device connection endpoint.
    Uses the original get_operator_session service.
    
    Query Parameters:
        otp: One-time password for authentication
    
    Args:
        device_id: ID of the device to connect
        
    Returns:
        JsonResponse with status, message, and appropriate HTTP status code
    """
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    otp = request.GET.get('otp')
    if not otp:
        return JsonResponse({
            'status': 'error',
            'message': 'OTP is required.'
        }, status=400)

    result = DeviceService.connect_device_session(device=device, otp=otp)
    
    return JsonResponse(
        {'status': result['status'], 'message': result['message']},
        status=result['status_code']
    )