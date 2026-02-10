"""
Django Views Module for Accounts App
=====================================
Handles all HTTP request/response logic for user and device management.

Architecture:
    - SECTION 1: Constants and Configurations
    - SECTION 2: Service Classes (Business Logic)
    - SECTION 3: View Functions (HTTP Handlers)

Author: Urbix Team
Version: 2.0
Last Updated: February 2026
"""

import json
import logging
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CompanyProfileForm, DeviceForm, UserCreationFormCustom
from .models import CompanyProfile, Device, UserRole

# Get custom logger for this module
logger = logging.getLogger(__name__)

# Get user model (supports custom user models)
User = get_user_model()


# =============================================================================
# SECTION 1: CONSTANTS AND CONFIGURATIONS
# =============================================================================

# User role hierarchy mapping
# Format: {parent_role: (child_role, display_label)}
ROLE_HIERARCHY: dict[str, tuple[str, str]] = {
    UserRole.ROOT: (UserRole.COMPANY, "Company"),
    UserRole.COMPANY: (UserRole.ADMIN, "Admin"),
    UserRole.ADMIN: (UserRole.STAFF, "Staff"),
}

# Operator login page URLs
# Used for Playwright automation
OPERATOR_LOGIN_URLS = {
    'grameenphone': 'https://www.grameenphone.com/personal/login',
    'robi': 'https://www.robi.com.bd/en/personal/my-robi',
    'banglalink': 'https://www.banglalink.net/en/login',
    'airtel': 'https://www.airtel.bd/en/login',
    'teletalk': 'https://www.teletalk.com.bd/login',
}

# Dashboard templates mapped by user role
DASHBOARD_TEMPLATES = {
    UserRole.ROOT: "dashboards/root_dashboard.html",
    UserRole.COMPANY: "dashboards/company_dashboard.html",
    UserRole.ADMIN: "dashboards/admin_dashboard.html",
    UserRole.STAFF: "dashboards/staff_dashboard.html",
}


# =============================================================================
# SECTION 2: SERVICE CLASSES
# =============================================================================
# Business logic separated from views for better testability and reusability

class PermissionService:
    """
    Authorization and permission checking service.
    
    Contains pure functions without side effects.
    All methods are static and stateless.
    """
    
    @staticmethod
    def can_view_user(viewer: User, target: User) -> bool:
        """
        Check if viewer has permission to view target user's profile.
        
        Permission Rules:
            1. Root users can view anyone
            2. Users can view their own profile
            3. Users can view accounts they created
            4. Company users can view admins created by their admins
        
        Args:
            viewer: User attempting to view
            target: User being viewed
            
        Returns:
            bool: True if access is allowed, False otherwise
        """
        # Root can view anyone
        if viewer.role == UserRole.ROOT:
            return True
        
        # Users can view themselves
        if viewer.id == target.id:
            return True
        
        # Users can view accounts they created
        if target.created_by_id == viewer.id:
            return True
        
        # Company can view their admins' staff
        if (
            viewer.role == UserRole.COMPANY
            and target.created_by
            and target.created_by.created_by_id == viewer.id
        ):
            return True
        
        return False

    @staticmethod
    def can_delete_user(actor: User, target: User) -> bool:
        """
        Check if actor has permission to delete target user.
        
        Deletion Rules:
            1. Root can delete companies (direct children only)
            2. Company can delete admins (direct children only)
            3. Admin can delete staff (direct children only)
            4. Cannot delete across different branches of hierarchy
        
        Args:
            actor: User attempting deletion
            target: User being deleted
            
        Returns:
            bool: True if deletion is allowed, False otherwise
        """
        # Check valid parent-child role pairs
        allowed_pairs = {
            (UserRole.ROOT, UserRole.COMPANY),
            (UserRole.COMPANY, UserRole.ADMIN),
            (UserRole.ADMIN, UserRole.STAFF),
        }
        
        # Verify role relationship
        if (actor.role, target.role) not in allowed_pairs:
            return False
        
        # Root can delete any company
        if actor.role == UserRole.ROOT:
            return True
        
        # Others can only delete their direct children
        return target.created_by_id == actor.id


class UserService:
    """
    User management service.
    
    Handles user creation, querying, and hierarchy management.
    """
    
    @staticmethod
    def create_child_user(creator: User, form: UserCreationFormCustom) -> str:
        """
        Create a new user one tier below the creator in hierarchy.
        
        Workflow:
            1. Determine child role from creator's role
            2. Create user instance (not yet saved)
            3. Set role, creator, and permissions
            4. Save to database
        
        Args:
            creator: User creating the new account
            form: Validated UserCreationFormCustom instance
            
        Returns:
            str: Human-readable role label of created user (e.g., "Company", "Admin")
        """
        # Get child role and label from hierarchy
        child_role, role_label = ROLE_HIERARCHY[creator.role]
        
        # Create user instance without saving
        new_user = form.save(commit=False)
        
        # Set role and creator
        new_user.role = child_role
        new_user.created_by = creator
        new_user.is_staff = True  # Allow admin panel access
        
        # Save to database
        new_user.save()
        
        return role_label

    @staticmethod
    def label_for_child_role(creator_role: str) -> str:
        """
        Get display label for the role that creator can create.
        
        Used for UI text like "Create New Company" or "Create New Admin".
        
        Args:
            creator_role: Role of the creating user
            
        Returns:
            str: Label like 'Company', 'Admin', or 'Staff'
        """
        return ROLE_HIERARCHY.get(creator_role, ("", "User"))[1]

    @staticmethod
    def get_child_users(current_user: User) -> tuple:
        """
        Retrieve all users in the tier directly below current user.
        
        Query Logic:
            - Root: Get all companies
            - Company: Get their admins
            - Admin: Get their staff
            - Staff: Returns empty queryset
        
        Args:
            current_user: User requesting the list
            
        Returns:
            tuple: (QuerySet of users, page title string)
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
        
        # Return ordered queryset and title
        return qs.order_by("-date_joined"), title


class DeviceService:
    """
    Device management service.
    
    Handles device CRUD operations and connection workflows.
    """
    
    @staticmethod
    def create_device(owner: User, form: DeviceForm) -> Device:
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
    def get_devices_for_owner(owner: User):
        """
        Retrieve all devices belonging to specified owner.
        
        Args:
            owner: User who owns the devices
            
        Returns:
            QuerySet: Filtered device queryset ordered by creation date
        """
        return Device.objects.filter(company=owner).order_by('-created_at')


# =============================================================================
# SECTION 3: VIEW FUNCTIONS
# =============================================================================
# HTTP request handlers - thin layer that delegates to services

# -----------------------------------------------------------------------------
# SUBSECTION 3.1: DASHBOARD VIEWS
# -----------------------------------------------------------------------------

@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    """
    Render role-appropriate dashboard for logged-in user.
    
    Template Selection:
        - Root -> root_dashboard.html
        - Company -> company_dashboard.html
        - Admin -> admin_dashboard.html
        - Staff -> staff_dashboard.html
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered dashboard template
    """
    template = DASHBOARD_TEMPLATES.get(request.user.role, "index.html")
    return render(request, template)


# -----------------------------------------------------------------------------
# SUBSECTION 3.2: USER MANAGEMENT VIEWS
# -----------------------------------------------------------------------------

@login_required
def create_user_view(request: HttpRequest) -> HttpResponse:
    """
    Create a new user one tier below current user in hierarchy.
    
    Hierarchy Flow:
        Root → Company → Admin → Staff
    
    Access Control:
        - Root, Company, Admin: Can create child users
        - Staff: Redirected to own profile (no creation permission)
    
    GET Request:
        Display empty user creation form
        
    POST Request:
        Validate and create new user
        Redirect to user list on success
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered form or redirect
    """
    current_user = request.user
    
    # Staff users cannot create accounts
    if current_user.role == UserRole.STAFF:
        logger.warning(
            f"Permission denied - staff user {current_user.id} "
            f"attempted user creation."
        )
        messages.error(request, "Permission Denied.")
        return redirect("user_detail", user_id=current_user.id)
    
    if request.method == "POST":
        # Process form submission
        form = UserCreationFormCustom(request.POST)
        
        if form.is_valid():
            # Create user via service
            role_title = UserService.create_child_user(
                creator=current_user, 
                form=form
            )
            
            messages.success(request, f"{role_title} created successfully!")
            logger.info(
                f"User {current_user.id} (role={current_user.role}) "
                f"created new {role_title}."
            )
            return redirect("all_users")
    else:
        # Display empty form
        form = UserCreationFormCustom()
    
    context = {
        "form": form,
        "creating_role": UserService.label_for_child_role(current_user.role),
    }
    return render(request, "accounts/create_user.html", context)


@login_required
def all_users_view(request: HttpRequest) -> HttpResponse:
    """
    Display list of users in tier directly below current user.
    
    View Logic:
        - Root: Shows all companies
        - Company: Shows their admins
        - Admin: Shows their staff
        - Staff: Redirects to own profile
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered user list or redirect
    """
    current_user = request.user
    
    # Staff users see their own profile instead
    if current_user.role == UserRole.STAFF:
        return redirect("user_detail", user_id=current_user.id)
    
    # Get child users via service
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
    Display detailed user profile with permission checking.
    
    Access Control:
        Enforced via PermissionService.can_view_user()
        See PermissionService docstring for rules
    
    Args:
        request: HTTP request object
        user_id: ID of user to view
        
    Returns:
        HttpResponse: Rendered profile or redirect if unauthorized
    """
    target_user = get_object_or_404(User, id=user_id)
    
    # Check view permission
    if not PermissionService.can_view_user(request.user, target_user):
        logger.warning(
            f"Access denied - user {request.user.id} "
            f"attempted to view user {target_user.id}."
        )
        messages.error(request, "Access Denied.")
        return redirect("home")
    
    return render(
        request, 
        "users/user_detail.html", 
        {"target_user": target_user}
    )


@login_required
def delete_user_view(request: HttpRequest, user_id: int) -> HttpResponse:
    """
    Delete user with confirmation step.
    
    GET Request:
        Show confirmation page
        
    POST Request:
        Execute deletion within atomic transaction
        Redirect to user list
    
    Access Control:
        Enforced via PermissionService.can_delete_user()
    
    Args:
        request: HTTP request object
        user_id: ID of user to delete
        
    Returns:
        HttpResponse: Confirmation page or redirect
    """
    target_user = get_object_or_404(User, id=user_id)
    
    # Check deletion permission
    if not PermissionService.can_delete_user(request.user, target_user):
        logger.warning(
            f"Unauthorized deletion attempt - "
            f"user {request.user.id} targeting user {target_user.id}."
        )
        messages.error(request, "Unauthorized action.")
        return redirect("all_users")
    
    if request.method == "POST":
        # Execute deletion in atomic transaction
        with transaction.atomic():
            target_user.delete()
        
        logger.info(f"User {request.user.id} deleted user {target_user.id}.")
        messages.success(request, "User deleted successfully.")
        return redirect("all_users")
    
    # Show confirmation page
    return render(
        request, 
        "users/confirm_delete.html", 
        {"target_user": target_user}
    )


@login_required
def all_admins_view(request: HttpRequest) -> HttpResponse:
    """
    Display global admin list across all companies.
    
    Access Control:
        Restricted to root users only
    
    Use Case:
        Root user oversight of all admin accounts in system
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered admin list or redirect
    """
    # Verify root permission
    if request.user.role != UserRole.ROOT:
        logger.warning(
            f"Non-root user {request.user.id} "
            f"attempted to access admin list."
        )
        return redirect("home")
    
    # Get all admins across system
    admins = User.objects.filter(role=UserRole.ADMIN).order_by("-date_joined")
    
    context = {
        "users": admins,
        "total_users": admins.count(),
        "page_title": "All System Admins",
    }
    return render(request, "users/all_users.html", context)


# -----------------------------------------------------------------------------
# SUBSECTION 3.3: COMPANY PROFILE VIEWS
# -----------------------------------------------------------------------------

@login_required
def edit_company_profile(request: HttpRequest) -> HttpResponse:
    """
    Edit company profile information.
    
    Access Control:
        Restricted to users with company role
    
    Fields:
        - Company name
        - Business details
        - Contact information
        - Other company-specific data
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered form or redirect
    """
    # Verify company role
    if request.user.role != UserRole.COMPANY:
        messages.error(request, "Access Denied.")
        return redirect("home")
    
    # Get or create profile
    profile = CompanyProfile.objects.get_or_create(user=request.user)[0]
    
    if request.method == "POST":
        # Process form submission
        form = CompanyProfileForm(request.POST, instance=profile)
        
        if form.is_valid():
            form.save()
            messages.success(request, "Company profile updated successfully!")
            logger.info(f"Company profile updated - user {request.user.id}.")
            return redirect("edit_company_profile")
        else:
            messages.error(request, "Error updating profile. Please check the form.")
    else:
        # Display form with current data
        form = CompanyProfileForm(instance=profile)
    
    return render(
        request, 
        "accounts/edit_company_profile.html", 
        {"form": form}
    )


# -----------------------------------------------------------------------------
# SUBSECTION 3.4: DEVICE MANAGEMENT VIEWS
# -----------------------------------------------------------------------------

@login_required
def add_device(request: HttpRequest) -> HttpResponse:
    """
    Add new device to user's account.
    
    Access Control:
        Restricted to users with company role
    
    Form Fields:
        - Operator (GP, Robi, Banglalink, etc.)
        - SIM number
        - Device identifier
        - Additional metadata
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered form or redirect
    """
    # Verify company role
    if request.user.role != UserRole.COMPANY:
        messages.error(request, "Only company accounts can add devices.")
        return redirect("home")
    
    if request.method == "POST":
        # Process form submission
        form = DeviceForm(request.POST)
        
        if form.is_valid():
            DeviceService.create_device(owner=request.user, form=form)
            logger.info(f"Device created by company user {request.user.id}.")
            messages.success(request, "Device added successfully!")
            return redirect("device_list")
    else:
        # Display empty form
        form = DeviceForm()
    
    return render(request, "devices/add_device.html", {"form": form})


@login_required
def device_list(request: HttpRequest) -> HttpResponse:
    """
    Display list of devices owned by current user.
    
    Shows:
        - Operator name and logo
        - SIM number
        - Connection status
        - Account balance
        - Action buttons (Connect, Edit, Delete, etc.)
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered device list
    """
    devices = DeviceService.get_devices_for_owner(request.user)
    
    return render(
        request, 
        "devices/device_list.html", 
        {"devices": devices}
    )


@login_required
def edit_device(request: HttpRequest, device_id: int) -> HttpResponse:
    """
    Edit device information.
    
    Ownership Verification:
        get_object_or_404 automatically filters by company=request.user
        Ensures users can only edit their own devices
    
    Args:
        request: HTTP request object
        device_id: ID of device to edit
        
    Returns:
        HttpResponse: Rendered form or redirect
    """
    # Get device with ownership verification
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    if request.method == "POST":
        # Process form submission
        form = DeviceForm(request.POST, instance=device)
        
        if form.is_valid():
            form.save()
            logger.info(f"Device {device.id} updated by user {request.user.id}.")
            messages.success(request, "Device updated successfully!")
            return redirect("device_list")
    else:
        # Display form with current data
        form = DeviceForm(instance=device)
    
    return render(
        request, 
        "devices/add_device.html", 
        {"form": form, "edit_mode": True}
    )


@login_required
def delete_device(request: HttpRequest, device_id: int) -> HttpResponse:
    """
    Delete device with confirmation.
    
    GET Request:
        Show confirmation page
        
    POST Request:
        Execute deletion and redirect
    
    Args:
        request: HTTP request object
        device_id: ID of device to delete
        
    Returns:
        HttpResponse: Confirmation page or redirect
    """
    # Get device with ownership verification
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    if request.method == "POST":
        # Execute deletion
        device_name = f"{device.get_operator_display()} - {device.sim_number}"
        device.delete()
        
        logger.info(f"Device {device_id} deleted by user {request.user.id}.")
        messages.success(request, f"Device '{device_name}' deleted successfully.")
        return redirect("device_list")
    
    # Show confirmation page
    return render(
        request,
        "devices/confirm_delete.html",
        {"device": device}
    )


# -----------------------------------------------------------------------------
# SUBSECTION 3.5: DEVICE CONNECTION VIEWS (AJAX/API)
# -----------------------------------------------------------------------------

@login_required
def send_otp_view(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Initiate OTP login flow for device asynchronously via Celery.
    
    Workflow:
        1. Validate device ownership
        2. Get operator login URL
        3. Queue Celery task for Playwright automation
        4. Return task ID for status tracking
    
    Response:
        Success: {'status': 'success', 'message': '...', 'task_id': '...'}
        Error: {'status': 'error', 'message': '...'}
    
    Args:
        request: HTTP request object
        device_id: ID of the device to connect
        
    Returns:
        JsonResponse with task information
    """
    # Verify device ownership
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    # Get operator URL
    operator_url = OPERATOR_LOGIN_URLS.get(device.operator)
    
    if not operator_url:
        return JsonResponse({
            'status': 'error',
            'message': f'Operator URL not found for "{device.operator}".'
        }, status=404)
    
    # Import task locally to avoid circular imports
    from .tasks import run_playwright_login_task
    
    # Queue asynchronous Celery task
    task = run_playwright_login_task.delay(
        device_id=device.id,
        operator_url=operator_url,
        sim_number=device.sim_number
    )
    
    logger.info(
        f"OTP flow initiated for device {device.id} "
        f"by user {request.user.id}. Task ID: {task.id}"
    )
    
    return JsonResponse({
        'status': 'success',
        'message': 'OTP request initiated. Browser will open shortly.',
        'task_id': task.id
    })


@login_required
def view_device_token(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Return session cookies/tokens for a device.
    
    Use Case:
        - Debugging connection issues
        - Manual session inspection
        - Advanced users viewing raw session data
    
    Response:
        Success: {
            'status': 'success',
            'device_name': '...',
            'cookies': [...],
            'full_session': {...}
        }
        Error: {'status': 'error', 'message': '...'}
    
    Args:
        request: HTTP request object
        device_id: ID of device
        
    Returns:
        JsonResponse with session data
    """
    # Verify device ownership
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    # Check if session data exists
    if not device.session_data:
        return JsonResponse({
            'status': 'error',
            'message': 'No session data available. Please login first.'
        }, status=404)
    
    try:
        # Parse session data
        session_data = json.loads(device.session_data)
        cookies = session_data.get('cookies', [])
        
        # Format cookies for display
        formatted_cookies = []
        for cookie in cookies:
            formatted_cookies.append({
                'name': cookie.get('name', 'N/A'),
                'value': cookie.get('value', 'N/A')[:50] + '...',  # Truncate
                'domain': cookie.get('domain', 'N/A'),
                'expires': cookie.get('expires', 'Session')
            })
        
        return JsonResponse({
            'status': 'success',
            'device_name': f"{device.get_operator_display()} - {device.sim_number}",
            'cookies': formatted_cookies,
            'full_session': session_data
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Session data is corrupted.'
        }, status=500)
    except Exception as e:
        logger.error(f"Error fetching token for device {device_id}: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Error parsing session data: {str(e)}'
        }, status=500)


@login_required
def logout_device(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Logout device by clearing session data.
    
    Workflow:
        1. Verify device ownership
        2. Clear session_data field
        3. Set status to "Inactive"
        4. Save changes
    
    Args:
        request: HTTP request object
        device_id: ID of device to logout
        
    Returns:
        JsonResponse with success/error status
    """
    # Verify device ownership
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    # Clear session
    device.session_data = None
    device.status = "Inactive"
    device.save(update_fields=['session_data', 'status'])
    
    logger.info(f"Device {device.id} logged out by user {request.user.id}.")
    
    return JsonResponse({
        'status': 'success',
        'message': f'Device {device.sim_number} logged out successfully.'
    })


@login_required
def check_balance(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Check current balance using saved session (queues Celery task).
    
    Workflow:
        1. Verify device has active session
        2. Queue Celery task to fetch balance
        3. Return task ID for status tracking
    
    Args:
        request: HTTP request object
        device_id: ID of device
        
    Returns:
        JsonResponse with task information
    """
    # Verify device ownership
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    # Check if device is connected
    if not device.session_data:
        return JsonResponse({
            'status': 'error',
            'message': 'Device not connected. Please login first.'
        }, status=400)
    
    # TODO: Implement check_device_balance_task in tasks.py
    # For now, return placeholder response
    
    logger.info(f"Balance check requested for device {device.id}.")
    
    return JsonResponse({
        'status': 'success',
        'message': 'Balance check feature coming soon!',
        'current_balance': float(device.balance)
    })


@login_required
def recharge_device(request: HttpRequest, device_id: int) -> JsonResponse:
    """
    Initiate recharge workflow for device.
    
    Note:
        This is a placeholder for future recharge functionality.
        Actual implementation depends on operator APIs.
    
    Args:
        request: HTTP request object
        device_id: ID of device
        
    Returns:
        JsonResponse with placeholder message
    """
    # Verify device ownership
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    # TODO: Implement recharge workflow
    
    logger.info(f"Recharge requested for device {device.id}.")
    
    return JsonResponse({
        'status': 'info',
        'message': 'Recharge feature coming soon!'
    })
    
@login_required
def disconnect_device(request, device_id):
    """ Clears the session data to disconnect the SIM """
    # Get device owned by current company
    device = get_object_or_404(Device, id=device_id, company=request.user)
    
    # Clear session and update status
    device.session_data = None
    device.status = "Disconnected"
    device.save()
    
    messages.warning(request, f"Device {device.sim_number} has been disconnected.")
    return redirect('device_list')