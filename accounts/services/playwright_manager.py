"""
Playwright Session Manager for Operator Login Automation
=========================================================
Handles complete browser automation workflow for telecom operator logins.
Designed for Celery workers with proper error handling and resource management.

Key Design Principles:
    - NO THREADING: All operations run synchronously in Celery worker
    - CELERY MANAGES CONCURRENCY: Each task runs in separate worker process
    - CLEAR ERROR HANDLING: All exceptions caught and logged properly
    - RESOURCE CLEANUP: Browser and connections always closed in finally block

Author: Abdullah Al Noman
Version: 2.1
Last Updated: February 2026
"""

import json
import re
import redis
import time
import os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from typing import Tuple, Optional
import logging


# ============================================================================
# LOGGER CONFIGURATION
# ============================================================================
logger = logging.getLogger(__name__)  # Get logger for this module

# ============================================================================
# GLOBAL SESSION STORAGE
# ============================================================================
# Reserved for future multi-session management features
# Currently unused - each task runs independently
active_sessions = {}

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================
REDIS_HOST = "redis"              # Redis server hostname (Docker service name)
REDIS_PORT = 6379                 # Redis default port
REDIS_DB = 0                      # Redis database number (0-15)
OTP_TIMEOUT = 300                 # Max wait time for OTP in seconds (5 minutes)
PAGE_LOAD_TIMEOUT = 60000         # Page load timeout in milliseconds (60 seconds)
ELEMENT_TIMEOUT = 15000           # Element wait timeout in milliseconds (15 seconds)
DEBUG_SCREENSHOTS = True          # Enable debug screenshots (disable in production)


# ============================================================================
# DATABASE UPDATE FUNCTION
# ============================================================================
def update_device_in_db(device_id: str, session_data_json: str, balance: float) -> None:
    """
    Updates device record in database with session data and balance.
    Uses atomic transaction with row-level locking to prevent race conditions.
    """
    from accounts.models import Device  # Import here to avoid circular imports
    from django.db import transaction   # Transaction decorator for atomicity

    try:
        with transaction.atomic():
            device = Device.objects.select_for_update().get(id=device_id)

            device.session_data = session_data_json
            device.balance = float(balance)
            device.status = "Active"

            device.save(update_fields=["session_data", "balance", "status"])
            logger.info(f"[DATABASE] ✓ Device {device_id} updated successfully.")

    except Device.DoesNotExist:
        logger.error(f"[DATABASE ERROR] Device {device_id} not found in database.")
    except Exception as e:
        logger.error(f"[DATABASE ERROR] Failed to update device {device_id}: {e}")


# ============================================================================
# MAIN PLAYWRIGHT SESSION MANAGER CLASS
# ============================================================================
class PlaywrightSessionManager:
    """
    Browser automation manager for telecom operator logins.
    """

    # ========================================================================
    # MAIN LOGIN FLOW METHOD
    # ========================================================================
    @staticmethod
    def run_full_login_flow(
        device_id: str,
        operator_url: str,
        sim_number: str,
        headless: Optional[bool] = None
    ) -> Tuple[bool, str]:
        """
        Execute complete login automation workflow synchronously.
        This is the main entry point called by Celery task.
        Runs entirely in a single worker process - NO THREADING.
        """
        playwright = None
        browser = None
        r = None
        page = None

        try:
            logger.info(f"[SESSION] Starting login for device {device_id}")

            if headless is None:
                headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

            logger.info(f"[BROWSER] Headless mode: {headless}")

            playwright = sync_playwright().start()

            browser = playwright.chromium.launch(
                headless=headless,
                slow_mo=100,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )

            page = context.new_page()

            logger.info(f"[STEP 1] Navigating to: {operator_url}")
            page.goto(operator_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step1_loaded.png")

            logger.info("[STEP 2] Handling cookie consent")
            try:
                page.wait_for_timeout(2000)
                page.locator('button:has-text("Accept Cookies")').click(timeout=5000)
                logger.info("[COOKIE] ✓ Cookies accepted")
            except:
                logger.info("[COOKIE] No cookie consent found")

            logger.info("[STEP 3] Clicking login button")
            login_btn = page.locator('button:has-text("Log In"), .mui-10pnwxb').first
            login_btn.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)
            login_btn.click()
            page.wait_for_timeout(2000)

            logger.info(f"[STEP 4] Filling phone number: {sim_number}")
            num_input = page.locator('input[name="robiNumber"]')
            num_input.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)

            num_input.click()
            num_input.fill("")
            page.wait_for_timeout(500)

            for digit in sim_number:
                page.keyboard.press(digit)
                page.wait_for_timeout(50)

            page.wait_for_timeout(1000)

            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step4_number_filled.png")

            logger.info("[STEP 5] Requesting OTP")
            send_otp_btn = page.locator('button:has-text("Send OTP"), .mui-1twuwjc')
            send_otp_btn.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)
            send_otp_btn.click()
            page.wait_for_timeout(3000)

            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step5_otp_requested.png")

            try:
                error_msg = page.locator("text=/error|invalid|wrong/i").first
                if error_msg.is_visible(timeout=2000):
                    error_text = error_msg.inner_text()
                    logger.error(f"[ERROR] OTP request failed: {error_text}")
                    return False, f"OTP request failed: {error_text}"
            except:
                pass

            logger.info("[STEP 6] Waiting for OTP input box")
            first_otp_box = page.locator("#otp-0")
            try:
                first_otp_box.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)
                logger.info(f"[OTP] ✓ OTP input box appeared for {sim_number}")
            except PlaywrightTimeout:
                if DEBUG_SCREENSHOTS:
                    page.screenshot(path=f"/app/debug_{device_id}_ERROR_no_otp_box.png")
                logger.error("[ERROR] OTP input box did not appear")
                return False, "OTP input box did not appear. Check screenshots."

            # ================================
            # REDIS OTP LISTENER (BLOCKING)
            # ================================
            logger.info(f"[OTP] Waiting on Redis channel for device {device_id}...")

            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
            )

            pubsub = r.pubsub()
            channel_name = f"otp_channel_{device_id}"
            pubsub.subscribe(channel_name)
            logger.info(f"[REDIS] Subscribed to channel: {channel_name}")

            otp = None
            start_time = time.time()

            for message in pubsub.listen():
                elapsed = time.time() - start_time
                if elapsed > OTP_TIMEOUT:
                    error_msg = f"OTP timeout: No response in {OTP_TIMEOUT} seconds"
                    logger.error(f"[TIMEOUT] {error_msg}")
                    return False, error_msg

                if message.get("type") == "message":
                    otp = message["data"]
                    logger.info(f"[REDIS] ✓ OTP received: {otp} (after {elapsed:.1f}s)")
                    break

            if not otp:
                return False, "OTP not received from Redis channel."

            # ================================
            # OTP ENTRY & CONFIRM
            # ================================
            logger.info(f"[STEP 7] Entering OTP: {otp}")

            otp_str = str(otp).strip()
            if len(otp_str) != 6:
                error_msg = f"Invalid OTP length: {len(otp_str)} (expected 6)"
                logger.error(f"[ERROR] {error_msg}")
                return False, error_msg

            try:
                page.evaluate(
                    "document.querySelectorAll('input[id^=\"otp-\"]')"
                    ".forEach(el => el.value = '')"
                )
            except:
                pass

            first_box = page.locator("#otp-0")
            first_box.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)
            first_box.click()
            page.wait_for_timeout(800)

            for i, digit in enumerate(otp_str):
                page.keyboard.press(digit)
                page.wait_for_timeout(250)
                logger.info(f"[OTP] Digit {i+1}/6 entered")

            page.wait_for_timeout(1500)

            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step7_otp_entered.png")

            logger.info("[STEP 8] Confirming OTP")

            confirm_success = False
            try:
                logger.info("[CONFIRM] Waiting for button to be enabled...")
                page.wait_for_selector(
                    'button:has-text("Confirm OTP"):not([disabled])',
                    timeout=10000,
                    state="visible",
                )
                page.locator('button:has-text("Confirm OTP")').click()
                confirm_success = True
                logger.info("[CONFIRM] ✓ Button clicked via Strategy 1")
            except PlaywrightTimeout:
                logger.warning("[CONFIRM] Strategy 1 failed, trying Strategy 2...")

            if not confirm_success:
                try:
                    page.evaluate("""
                        const btn = document.querySelector('button[class*="mui"]:not([disabled])');
                        if (btn && btn.textContent.includes('Confirm')) btn.click();
                    """)
                    confirm_success = True
                    logger.info("[CONFIRM] ✓ Button clicked via Strategy 2 (JavaScript)")
                except:
                    logger.error("[CONFIRM] Strategy 2 also failed")

            if not confirm_success:
                return False, "Could not click Confirm OTP button after multiple attempts"

            page.wait_for_timeout(3000)

            # ================================
            # BALANCE EXTRACTION
            # ================================
            logger.info("[STEP 9] Waiting for dashboard to load")

            balance_elem = page.locator(
                "p.MuiTypography-root.MuiTypography-body1.mui-v247a6"
            ).first

            try:
                balance_elem.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
                logger.info("[BALANCE] ✓ Balance element found")
            except PlaywrightTimeout:
                logger.warning("[BALANCE] Primary selector failed, trying fallback...")
                try:
                    balance_elem = page.locator(
                        'span.MuiTypography-kohinoorBangla:has-text("৳")'
                    ).locator("..").first
                    balance_elem.wait_for(state="visible", timeout=10000)
                    logger.info("[BALANCE] ✓ Balance found using fallback selector")
                except:
                    if DEBUG_SCREENSHOTS:
                        page.screenshot(path=f"/app/debug_{device_id}_ERROR_no_balance.png")
                    logger.error("[ERROR] Could not find balance element")
                    return False, "Could not find balance element on dashboard"

            raw_text = balance_elem.inner_text()
            clean_balance = PlaywrightSessionManager._extract_balance(raw_text)
            logger.info(f"[BALANCE] Extracted balance: ৳{clean_balance}")

            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_SUCCESS_dashboard.png")

            # ================================
            # SESSION CAPTURE + DB UPDATE
            # ================================
            logger.info("[STEP 10] Capturing session data")
            storage_state = context.storage_state()
            session_data_json = json.dumps(storage_state, indent=2)

            update_device_in_db(
                device_id=device_id,
                session_data_json=session_data_json,
                balance=clean_balance,
            )

            logger.info(f"[SUCCESS] ✓ Full login flow completed for device {device_id}")
            return True, f"Login successful. Balance: ৳{clean_balance}"

        except PlaywrightTimeout as e:
            error_msg = f"Playwright timeout: {str(e)}"
            logger.error(f"[ERROR] {error_msg}")
            if DEBUG_SCREENSHOTS and page:
                try:
                    page.screenshot(path=f"/app/debug_{device_id}_ERROR_timeout.png")
                except:
                    pass
            return False, error_msg

        except redis.RedisError as e:
            error_msg = f"Redis connection error: {str(e)}"
            logger.error(f"[ERROR] {error_msg}")
            return False, error_msg

        except ValueError as e:
            error_msg = f"Invalid input: {str(e)}"
            logger.error(f"[ERROR] {error_msg}")
            return False, error_msg

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"[ERROR] {error_msg}", exc_info=True)
            if DEBUG_SCREENSHOTS and page:
                try:
                    page.screenshot(path=f"/app/debug_{device_id}_ERROR_unexpected.png")
                except:
                    pass
            return False, error_msg

        finally:
            logger.info(f"[CLEANUP] Closing all resources for device {device_id}")

            if r:
                try:
                    r.close()
                    logger.info("[CLEANUP] ✓ Redis connection closed")
                except Exception as e:
                    logger.error(f"[CLEANUP ERROR] Failed to close Redis: {e}")

            if browser:
                try:
                    browser.close()
                    logger.info("[CLEANUP] ✓ Browser closed")
                except Exception as e:
                    logger.error(f"[CLEANUP ERROR] Failed to close browser: {e}")

            if playwright:
                try:
                    playwright.stop()
                    logger.info("[CLEANUP] ✓ Playwright stopped")
                except Exception as e:
                    logger.error(f"[CLEANUP ERROR] Failed to stop Playwright: {e}")

            logger.info(f"[CLEANUP] ✓ All resources cleaned up for device {device_id}")

    # ========================================================================
    # NEW FEATURE: SESSION-BASED BALANCE REFRESH (NO OTP)
    # ========================================================================
@staticmethod
def refresh_device_balance(
        device_id: str,
        dashboard_url: str = "https://www.robi.com.bd/en/personal/my-robi",
        headless: Optional[bool] = True
    ) -> Tuple[bool, str]:
        """
        Uses saved session_data to fetch latest balance without OTP.
        Notifies frontend via WebSocket on success/failure.
        """
        from accounts.models import Device
        from django.db import transaction

        playwright = None
        browser = None
        page = None

        # 1. Quick DB check
        try:
            device = Device.objects.get(id=device_id)
        except Device.DoesNotExist:
            return False, "Device not found"

        if not device.session_data:
            return False, "No session found. Please connect with OTP first."

        try:
            if headless is None:
                headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=headless,
                slow_mo=50,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            
            # 2. Load Session State
            saved_state = json.loads(device.session_data)
            # Temporary state file for the context
            state_path = f"/tmp/state_{device_id}.json"
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(saved_state, f)

            context = browser.new_context(
                storage_state=state_path,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )

            page = context.new_page()
            logger.info(f"[REFRESH] Navigating to dashboard for device {device_id}")
            
            # Use 'commit' for faster response
            page.goto(dashboard_url, wait_until="commit", timeout=PAGE_LOAD_TIMEOUT)

            # 3. Robust Session Validation
            # Check if we were redirected to login or see the login button
            page.wait_for_timeout(3000) # Wait for redirects
            login_btn = page.locator('button:has-text("Log In"), a:has-text("Log In"), #otp-0').first
            
            if login_btn.is_visible(timeout=5000):
                logger.warning(f"[REFRESH] Session expired for device {device_id}")
                with transaction.atomic():
                    d = Device.objects.select_for_update().get(id=device_id)
                    d.session_data = None
                    d.status = "Disconnected"
                    d.save(update_fields=["session_data", "status"])
                # Notify frontend about expiration
                PlaywrightSessionManager._notify_frontend(device_id, "error", "0.00", "Session expired")
                return False, "Session expired. Re-connect with OTP."

            # 4. Extract Balance
            balance_elem = page.locator("p:has-text('৳'), span:has-text('৳')").first
            balance_elem.wait_for(state="visible", timeout=30000)
            
            raw_text = balance_elem.inner_text()
            clean_balance = PlaywrightSessionManager._extract_balance(raw_text)

            # 5. Save and Notify (THE MOST IMPORTANT PART)
            new_state_json = json.dumps(context.storage_state())
            update_device_in_db(device_id, new_state_json, clean_balance)
            
            # This triggers the auto-reload in your browser
            PlaywrightSessionManager._notify_frontend(device_id, "success", clean_balance, "Balance Refreshed")

            return True, f"Balance updated: ৳{clean_balance}"

        except Exception as e:
            logger.error(f"[REFRESH ERROR] Device {device_id}: {e}")
            PlaywrightSessionManager._notify_frontend(device_id, "error", "0.00", str(e))
            return False, str(e)

        finally:
            # Cleanup resources and temp files
            if browser: browser.close()
            if playwright: playwright.stop()
            if os.path.exists(state_path): os.remove(state_path)

    # ========================================================================
    # HELPER METHODS
    # ========================================================================
@staticmethod
def _extract_balance(raw_text: str) -> float:
        """
        Extract numeric balance value from text containing currency symbols.
        """
        try:
            logger.info(f"[BALANCE] Raw text: '{raw_text}'")
            cleaned = raw_text.replace("৳", "")
            cleaned = cleaned.replace("<!--", "").replace("-->", "")
            cleaned = cleaned.strip()

            match = re.search(r"([\d,]+\.?\d*)", cleaned)
            if match:
                balance_str = match.group(1).replace(",", "")
                balance_value = float(balance_str)
                logger.info(f"[BALANCE] Extracted: {balance_value}")
                return balance_value

            logger.warning(f"[WARNING] Could not extract balance from: {raw_text}")
            return 0.0

        except Exception as e:
            logger.error(f"[ERROR] Balance extraction failed: {e}")
            return 0.0

@staticmethod
def get_active_session_count() -> int:
        return len(active_sessions)

@staticmethod
def cleanup_all_sessions() -> None:
        logger.info("[CLEANUP] Cleaning up all active sessions from memory")
        active_sessions.clear()
        logger.info("[CLEANUP] ✓ All sessions cleared")
