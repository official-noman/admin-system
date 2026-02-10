"""
Celery Tasks for Device Automation
===================================
Background tasks for handling device login workflows.
"""

from celery import shared_task
from .services.playwright_manager import PlaywrightSessionManager
import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import json


logger = logging.getLogger(__name__)


# ============================================================================
# TASK 1: PLAYWRIGHT LOGIN FLOW
# ============================================================================
@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,  # Max 10 minutes between retries
    name='accounts.run_playwright_login'  # Explicit task name for monitoring
)
def run_playwright_login_task(self, device_id, operator_url, sim_number):
    """
    Execute complete Playwright login flow in background.
    
    This task:
    1. Launches browser via Playwright
    2. Navigates to operator website
    3. Requests OTP
    4. Waits for OTP via Redis
    5. Completes login
    6. Saves session data to database
    
    Args:
        device_id (str): Unique device identifier
        operator_url (str): Operator login page URL
        sim_number (str): SIM card number (phone number)
        
    Returns:
        dict: {
            'success': bool,
            'message': str,
            'device_id': str
        }
        
    Raises:
        Retry: Automatically retries up to 3 times with exponential backoff
        
    Retry Schedule:
        - 1st retry: after 60 seconds
        - 2nd retry: after 120 seconds (2 minutes)
        - 3rd retry: after 240 seconds (4 minutes)
    """
    try:
        logger.info(f"[TASK START] Device {device_id}: Initiating login flow")
        logger.info(f"[TASK INFO] Operator: {operator_url}, Number: {sim_number}")
        
        # Execute full login flow
        success, message = PlaywrightSessionManager.run_full_login_flow(
            device_id=str(device_id),  # Ensure string type
            operator_url=operator_url,
            sim_number=sim_number
        )
        
        if success:
            # প্লে-রাইট কাজ শেষ করার পর WebSocket-কে মেসেজ পাঠানো
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"device_{device_id}", # যে গ্রুপে ব্রাউজার শুনছে
                {
                    "type": "login_result", # consumer এর ফাংশনের নাম
                    "status": "success",
                    "message": message
                }
            )
            
        # Log result based on success/failure
        if success:
            logger.info(f"[TASK SUCCESS] Device {device_id}: {message}")
        else:
            logger.warning(f"[TASK FAILED] Device {device_id}: {message}")
        
        # Console output for debugging (visible in docker logs)
        print(f"[CELERY] Task completed for device {device_id}: Success={success}")
        
        return {
            "success": success,
            "message": message,
            "device_id": device_id
        }
        
    except Exception as exc:
        # Log the exception with full traceback
        logger.error(
            f"[TASK ERROR] Device {device_id}: {str(exc)}",
            exc_info=True  # Include full traceback in logs
        )
        
        # Calculate retry countdown (exponential backoff)
        retry_count = self.request.retries
        countdown = 60 * (2 ** retry_count)  # 60s, 120s, 240s
        
        logger.warning(
            f"[TASK RETRY] Device {device_id}: "
            f"Attempt {retry_count + 1}/3, retrying in {countdown}s"
        )
        
        # Raise retry exception
        raise self.retry(exc=exc, countdown=countdown)