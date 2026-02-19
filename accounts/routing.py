from django.urls import path
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    path('ws/otp/<str:device_id>/', consumers.OTPConsumer.as_asgi()),
    re_path(r'ws/android/$', consumers.AndroidBridgeConsumer.as_asgi()),

]