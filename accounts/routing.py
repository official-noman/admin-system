from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/otp/<str:device_id>/', consumers.OTPConsumer.as_asgi()),
]