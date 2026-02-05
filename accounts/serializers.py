from rest_framework import serializers
from .models import User, CompanyProfile, Device

class CompanyProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyProfile
        fields = ['company_name', 'license_number', 'company_email', 'location', 'website', 'phone_number']

class UserSerializer(serializers.ModelSerializer):
    companyprofile = CompanyProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'role', 'date_joined', 'companyprofile']
        read_only_fields = ['role', 'date_joined']

class DeviceSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.username', read_only=True)
    operator_display = serializers.CharField(source='get_operator_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Device
        fields = [
            'id', 'company', 'company_name', 'operator', 'operator_display',
            'sim_number', 'sim_pin', 'balance', 'status', 'status_display',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'company']
        extra_kwargs = {
            'password': {'write_only': True}
        }

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        device = super().create(validated_data)
        if password:
            device.set_password(password)
            device.save()
        return device

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        device = super().update(instance, validated_data)
        if password:
            device.set_password(password)
            device.save()
        return device
