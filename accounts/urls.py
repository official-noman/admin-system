from django.urls import path
from . import views

urlpatterns = [
    # User Creation
    path('create-user/', views.create_user_view, name='create_user'),
    
    # User Lists
    path('users/', views.all_users_view, name='all_users'),
    path('admins/', views.all_admins_view, name='all_admins'), # Uncommented for Root
    
    # User Profile (Variable must be 'user_id' to match views.py)
    path('profile/<int:user_id>/', views.user_detail_view, name='user_detail'),
    
    # Delete User (Optional but good to have linked)
    path('delete/<int:user_id>/', views.delete_user_view, name='delete_user'),
    path('company/profile/', views.edit_company_profile, name='edit_company_profile'),
    path('devices/add/', views.add_device, name='add_device'),
    path('devices/list/', views.device_list, name='device_list'),
    # path('device/edit/<int:id>/', views.edit_device, name='edit_device'),
    path('device/edit/<int:device_id>/', views.edit_device, name='edit_device'),
]