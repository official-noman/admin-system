
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.template import TemplateDoesNotExist
from django.http import Http404
from django.contrib.auth import get_user_model

User = get_user_model()

@login_required
def home_view(request):
    """Main dashboard based on user role"""
    user = request.user
    
    # Role-based redirect
    if user.role == 'root':
        return render(request, 'dashboards/root_dashboard.html')
    elif user.role == 'admin':
        return render(request, 'dashboards/admin_dashboard.html')
    elif user.role == 'company':
        return render(request, 'dashboards/company_dashboard.html')
    elif user.role == 'staff':
        return render(request, 'dashboards/staff_dashboard.html')
    
    
    return render(request, 'index.html')


@login_required
def dynamic_view(request, page):
    """Render dynamic pages safely"""
    
    # Whitelist allowed pages for security
    allowed_pages = [
        'pages-starter', 'pages-profile', 'pages-privacy-policy',
        'pages-terms-conditions', 'pages-timeline', 
        'pages-billing-subscription'
    ]
    
    if page not in allowed_pages:
        raise Http404("Page not found")
    
    try:
        return render(request, f'{page}.html')
    except TemplateDoesNotExist:
        return render(request, 'pages-404.html')


@login_required
def all_users_view(request):
    """
    Display users based on role:
    - Root: Can see ALL users (Root + Admin + Company)
    - Admin: Can see ONLY Companies
    - Company: Access Denied
    """
    user = request.user
    
    # Check permission
    if user.role == 'company':
        raise Http404("You don't have permission to access this page")
    
    # Filter based on role
    if user.role == 'root':
        # Root can see ALL users
        all_users = User.objects.all().order_by('-date_joined')
    elif user.role == 'admin':
        # Admin can see only Company users
        all_users = User.objects.filter(role='company').order_by('-date_joined')
    else:
        all_users = []
    
    context = {
        'users': all_users,
        'total_users': all_users.count(),
        'user_role': user.role,
    }
    
    return render(request, 'users/all_users.html', context)


@login_required
def user_detail_view(request, user_id):
    """
    View user details:
    - Root: Can view ALL users
    - Admin: Can view ONLY Companies
    - Company: Can only view themselves
    """
    user = request.user
    
    try:
        target_user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise Http404("User not found")
    
    # Permission logic
    if user.role == 'root':
        # Root can view anyone
        pass
    elif user.role == 'admin':
        # Admin can ONLY view Company users
        if target_user.role != 'company':
            raise Http404("Access denied")
    elif user.role == 'company':
        # Company can only view themselves
        if user.id != user_id:
            raise Http404("Access denied")
    
    context = {
        'target_user': target_user,
    }
    
    return render(request, 'users/user_detail.html', context)