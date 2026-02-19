import json
import redis.asyncio as redis
from channels.generic.websocket import AsyncWebsocketConsumer

# --- Frontend OTP Consumer (Robi/Existing Logic) ---
class OTPConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device_id = self.scope['url_route']['kwargs']['device_id']
        self.room_group_name = f"device_{self.device_id}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        otp = data.get('otp')
        
        # Publish OTP to Redis for Playwright
        r = redis.Redis(host='redis', port=6379, db=0)
        await r.publish(f'otp_channel_{self.device_id}', otp)
        await r.aclose()
        
    async def login_result(self, event):
        await self.send(text_data=json.dumps({
            "status": event["status"],
            "balance": event.get("balance", "Updated"),
            "message": event["message"]
        }))

# --- Android Bridge Consumer (GP/New Logic) ---
class AndroidBridgeConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = "gp_android_bridge"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        print(f"🚀 GP Android Bridge Connected: {self.channel_name}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        print("❌ GP Android Bridge Disconnected")

    async def receive(self, text_data):
        # অ্যান্ড্রয়েড থেকে কোনো রেসপন্স আসলে এখানে প্রিন্ট হবে
        data = json.loads(text_data)
        print(f"📩 Data from Android: {data}")

    async def send_command(self, event):
        # সার্ভার থেকে অ্যান্ড্রয়েড ফোনে কমান্ড পাঠানোর মেথড
        await self.send(text_data=json.dumps(event["message"]))