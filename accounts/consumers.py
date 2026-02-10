import json, redis.asyncio as redis
from channels.generic.websocket import AsyncWebsocketConsumer

class OTPConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device_id = self.scope['url_route']['kwargs']['device_id']
        self.room_group_name = f"device_{self.device_id}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        
    async def disconnect(self, close_code):
        # Leave group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        otp = data.get('otp')
        
        # Publish OTP to Redis for Playwright
        r = redis.Redis(host='redis', port=6379, db=0)
        await r.publish(f'otp_channel_{self.device_id}', otp)
        await r.aclose()
        
    # This method receives messages from the PlaywrightManager via Group
    async def login_result(self, event):
        # Forward the success/fail result to the Frontend browser
        await self.send(text_data=json.dumps({
            "status": event["status"],
            "balance": event.get("balance", "Updated"),
            "message": event["message"]
        }))
        