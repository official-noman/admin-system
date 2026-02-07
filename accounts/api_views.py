# File: accounts/api_views.py

# ==============================================================================
#  IMPORTS
# ==============================================================================
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

# Local Application Imports
from .models import User, Device, UserRole
from .serializers import UserSerializer, DeviceSerializer

# NOTE: 'connect_device_view' and 'get_operator_session' are removed from here
# because they are now handled in 'views.py'.

# ==============================================================================
#  CUSTOM PERMISSIONS
# ==============================================================================

class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object or an admin to view/edit it.
    - ROOT users can access any object.
    - A company user can access objects belonging to their company.
    - A regular user can only access their own objects.
    """
    def has_object_permission(self, request, view, obj):
        # ROOT/Superuser has access to everything.
        if request.user.role == UserRole.ROOT:
            return True

        # Check if the object (e.g., a Device) is linked to the user's company.
        if hasattr(obj, 'company'):
            return obj.company == request.user

        # Fallback for objects that are the user themselves (e.g., user profile).
        return obj == request.user

# ==============================================================================
#  API VIEWSETS (DJANGO REST FRAMEWORK)
# ==============================================================================

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows users to be viewed.
    The queryset is dynamically filtered based on the requesting user's role.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Dynamically filters the queryset based on the user's role.
        """
        user = self.request.user
        if user.role == UserRole.ROOT:
            return User.objects.all()
        if user.role == UserRole.COMPANY:
            # Returns all users that were created by this company admin.
            return User.objects.filter(created_by=user)
        
        # Default: A user can only see their own data.
        return User.objects.filter(id=user.id)

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        """
        A custom convenience endpoint to return the current logged-in user's profile.
        Accessed via `/api/users/me/`.
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class DeviceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for creating, viewing, updating, and deleting devices.
    Permissions are restricted to the device owner or an admin.
    """
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        """
        Filters devices based on the user's role.
        """
        user = self.request.user
        if user.role == UserRole.ROOT:
            return Device.objects.all()
        
        # Assumes 'company' is a ForeignKey on the Device model linking to the User.
        return Device.objects.filter(company=user)

    def perform_create(self, serializer):
        """
        Automatically associates the device with the user who is creating it.
        The 'company' field is set to the request.user.
        """
        serializer.save(company=self.request.user)

