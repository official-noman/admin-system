"""
URL Configuration for Accounts App
===================================
Handles routing for both web views and API endpoints.

Structure:
- Standard Django views (HTML pages)
- DRF API endpoints (JSON responses)
- WebSocket routes (handled separately in routing.py)
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Import views with clear aliases
from . import views as standard_views
from . import api_views


# ============================================================================
# DJANGO REST FRAMEWORK ROUTER
# ============================================================================
# Automatically generates CRUD endpoints for ViewSets
# Example generated URLs:
#   GET    /api/users/           -> List all users
#   POST   /api/users/           -> Create user
#   GET    /api/users/{id}/      -> Get specific user
#   PUT    /api/users/{id}/      -> Update user
#   DELETE /api/users/{id}/      -> Delete user
router = DefaultRouter()
router.register(r'users', api_views.UserViewSet, basename='api-user')
router.register(r'devices', api_views.DeviceViewSet, basename='api-device')


# ============================================================================
# URL PATTERNS
# ============================================================================
urlpatterns = [
    # ========================================================================
    # SECTION 1: DASHBOARD
    # ========================================================================
    path('', standard_views.home_view, name='home'),

    # ========================================================================
    # SECTION 2: USER MANAGEMENT (Web Pages)
    # ========================================================================
    path('users/', standard_views.all_users_view, name='all_users'),
    path('users/create/', standard_views.create_user_view, name='create_user'),
    path('users/profile/<int:user_id>/', standard_views.user_detail_view, name='user_detail'),
    path('users/delete/<int:user_id>/', standard_views.delete_user_view, name='delete_user'),
    
    # Admin Management (Root user only)
    path('admins/', standard_views.all_admins_view, name='all_admins'),

    # ========================================================================
    # SECTION 3: COMPANY PROFILE
    # ========================================================================
    path('company/profile/', standard_views.edit_company_profile, name='edit_company_profile'),

    # ========================================================================
    # SECTION 4: DEVICE MANAGEMENT (Web Pages)
    # ========================================================================
    path('devices/', standard_views.device_list, name='device_list'),
    path('devices/add/', standard_views.add_device, name='add_device'),
    path('devices/edit/<int:device_id>/', standard_views.edit_device, name='edit_device'),
    path('devices/delete/<int:device_id>/', standard_views.delete_device, name='delete_device'),  # MISSING!

    # ========================================================================
    # SECTION 5: DEVICE ACTIONS (AJAX/WebSocket Endpoints)
    # ========================================================================
    # OTP Flow
    path('devices/<int:device_id>/send-otp/', standard_views.send_otp_view, name='send_otp'),
    
    # Additional Device Actions (Based on your screenshot requirements)
    path('devices/<int:device_id>/token/', standard_views.view_device_token, name='view_device_token'),
    path('devices/<int:device_id>/logout/', standard_views.logout_device, name='logout_device'),
    path('devices/<int:device_id>/balance/', standard_views.check_balance, name='check_balance'),
    path('devices/<int:device_id>/recharge/', standard_views.recharge_device, name='recharge_device'),

    # ========================================================================
    # SECTION 6: REST API ENDPOINTS
    # ========================================================================
    # DRF Router URLs (users, devices CRUD via API)
    path('api/', include(router.urls)),
    
    # DRF Authentication (if using token/session auth)
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('devices/disconnect/<int:device_id>/', standard_views.disconnect_device, name='disconnect_device'),
]