# File: accounts/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Import both view files with clear aliases to avoid confusion
from . import views as standard_views
from . import api_views

# =============================================================
#  ROUTER FOR DJANGO REST FRAMEWORK API ENDPOINTS
# =============================================================
# This will automatically generate URLs for your ViewSets:
# /api/users/
# /api/users/{pk}/
# /api/devices/
# /api/devices/{pk}/
# etc.
router = DefaultRouter()
router.register(r'users', api_views.UserViewSet, basename='api-user')
router.register(r'devices', api_views.DeviceViewSet, basename='api-device')


# =============================================================
#  URL PATTERNS
# =============================================================
urlpatterns = [
    # --- Standard Django Views (for web pages) ---

    # Home/Dashboard
    path('', standard_views.home_view, name='home'),

    # User Management
    path('users/', standard_views.all_users_view, name='all_users'),
    path('users/create/', standard_views.create_user_view, name='create_user'),
    path('users/profile/<int:user_id>/', standard_views.user_detail_view, name='user_detail'),
    path('users/delete/<int:user_id>/', standard_views.delete_user_view, name='delete_user'),
    path('admins/', standard_views.all_admins_view, name='all_admins'), # For Root user

    # Company Profile
    path('company/profile/', standard_views.edit_company_profile, name='edit_company_profile'),

    # Device Management
    path('devices/', standard_views.device_list, name='device_list'), # List of devices
    path('devices/add/', standard_views.add_device, name='add_device'),
    path('devices/edit/<int:device_id>/', standard_views.edit_device, name='edit_device'),

    # --- Asynchronous Action URL (for connecting device via Playwright) ---
    # path('devices/connect/<int:device_id>/', standard_views.connect_device_view, name='connect_device'),

    # --- API Endpoints (for programmatic access, e.g., via JavaScript frameworks) ---
    path('api/', include(router.urls)),
     path('devices/send-otp/<int:device_id>/', standard_views.send_otp_view, name='send_otp'),
    path('devices/verify-otp/<int:device_id>/', standard_views.verify_otp_view, name='verify_otp'),
]
