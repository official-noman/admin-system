from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import User, Device, UserRole
from .serializers import UserSerializer, DeviceSerializer

class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object (or admins) to edit it.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        # if request.method in permissions.SAFE_METHODS:
        #     return True

        # Write permissions are only allowed to the owner of the snippet.
        if request.user.role == UserRole.ROOT:
            return True
        if hasattr(obj, 'company'):
            return obj.company == request.user
        return obj == request.user

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows users to be viewed.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == UserRole.ROOT:
            return User.objects.all()
        # Return only relevant users based on hierarchy
        if user.role == UserRole.COMPANY:
            return User.objects.filter(created_by=user)
        return User.objects.filter(id=user.id)

    @action(detail=False, methods=['get'])
    def me(self, request):
        """
        Return the current user's profile.
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

class DeviceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for devices.
    """
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == UserRole.ROOT:
            return Device.objects.all()
        return Device.objects.filter(company=user)

    def perform_create(self, serializer):
        serializer.save(company=self.request.user)
