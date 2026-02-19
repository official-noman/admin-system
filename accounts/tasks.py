"""
Celery Tasks for Device Automation
===================================
Background tasks for handling device login and balance synchronization.
"""

from celery import shared_task
from .services.playwright_manager import PlaywrightSessionManager
import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import json

logger = logging.getLogger(__name__)


# ============================================================================
# TASK 1: INITIAL PLAYWRIGHT LOGIN FLOW (With OTP)
# ============================================================================
@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    name='accounts.run_playwright_login'
)
def run_playwright_login_task(self, device_id, operator_url, sim_number):
    """
    Execute complete Playwright login flow (Browser -> OTP -> Scrape -> Save).
    Notifies frontend via WebSocket on completion.
    """
    try:
        logger.info(f"[TASK START] Device {device_id}: Initiating initial login")
        
        # 1. Execute the full login flow from manager
        success, message = PlaywrightSessionManager.run_full_login_flow(
            device_id=str(device_id),
            operator_url=operator_url,
            sim_number=sim_number
        )
        
        # 2. If successful, notify the frontend WebSocket to close modal and reload
        if success:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"device_{device_id}", 
                {
                    "type": "login_result",
                    "status": "success",
                    "message": "Login successful! Refreshing dashboard..."
                }
            )
            logger.info(f"[TASK SUCCESS] Device {device_id}: Session captured.")
        else:
            logger.warning(f"[TASK FAILED] Device {device_id}: {message}")
        
        return {"success": success, "message": message, "device_id": device_id}
        
    except Exception as exc:
        logger.error(f"[TASK ERROR] Device {device_id}: {str(exc)}", exc_info=True)
        # Exponential backoff retry
        countdown = 60 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


# ============================================================================
# TASK 2: BACKGROUND BALANCE REFRESH (Using Saved Cookies)
# ============================================================================
@shared_task(
    name='accounts.run_balance_refresh'
)
def run_balance_refresh_task(device_id):
    """
    Syncs device balance using existing session data (cookies).
    No OTP required. Notifies UI when finished.
    """
    try:
        logger.info(f"[REFRESH START] Syncing balance for device {device_id}")
        
        # 1. Call the refresh method from manager
        success, message = PlaywrightSessionManager.refresh_device_balance(device_id)
        
        # 2. Always notify UI so the user sees the update or error
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"device_{device_id}",
            {
                "type": "login_result", # Reuse the same consumer handler
                "status": "success" if success else "error",
                "message": message
            }
        )
        
        if success:
            logger.info(f"[REFRESH SUCCESS] Device {device_id} balance updated.")
        else:
            logger.error(f"[REFRESH FAILED] Device {device_id}: {message}")
            
        return {"success": success, "message": message}

    except Exception as e:
        logger.error(f"[REFRESH CRITICAL ERROR] Device {device_id}: {str(e)}")
        return {"success": False, "message": str(e)}