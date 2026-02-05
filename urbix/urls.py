"""
URL configuration for Urbix project.
Production-ready URL routing with organized patterns.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from urbix.views import home_view, dynamic_view, all_users_view, user_detail_view
from rest_framework import routers
from rest_framework.authtoken import views as authtoken_views
from accounts.api_views import UserViewSet, DeviceViewSet

router = routers.DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'devices', DeviceViewSet, basename='device')

# ==============================================================================
# MAIN URL PATTERNS
# ==============================================================================

urlpatterns = [
    # Admin panel
    path(settings.ADMIN_PATH, admin.site.urls),
    
    # API
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('api-token-auth/', authtoken_views.obtain_auth_token),
    
    # Home and dynamic pages
    path('', home_view, name='home'),
    path('<str:page>', dynamic_view, name='dynamic_page'),
    
    # User management
    path('users/', all_users_view, name='all_users'),
    path('users/<int:user_id>/', user_detail_view, name='user_detail'),
    
    # Authentication (built-in Django auth views)
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Accounts app (custom user management)
    path('accounts/', include('accounts.urls')),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]

# ==============================================================================
# MEDIA FILES (Development only)
# ==============================================================================

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# ==============================================================================
# CUSTOM ERROR HANDLERS (Production)
# ==============================================================================

# handler404 = 'urbix.views.error_404'
# handler500 = 'urbix.views.error_500'
# handler403 = 'urbix.views.error_403'