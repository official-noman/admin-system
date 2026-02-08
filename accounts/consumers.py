import json, redis.asyncio as redis
from channels.generic.websocket import AsyncWebsocketConsumer

class OTPConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device_id = self.scope['url_route']['kwargs']['device_id']
        await self.accept()

    async def receive(self, text_data):
        otp = json.loads(text_data).get('otp')
        r = redis.Redis(host='redis', port=6379, db=0)
        await r.publish(f'otp_channel_{self.device_id}', otp)
        await r.aclose()