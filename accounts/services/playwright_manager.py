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
Version: 2.0
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
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

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
    
    How it works:
        1. Start atomic transaction
        2. Lock the specific device row (select_for_update)
        3. Update session_data, balance, and status fields
        4. Save only modified fields (update_fields optimization)
        5. Commit transaction automatically
    
    Why select_for_update?
        Prevents two Celery workers from updating same device simultaneously
        Locks the row until transaction completes
        Other workers wait instead of creating conflicts
    
    Args:
        device_id: Unique identifier for the device
        session_data_json: JSON string containing browser cookies/storage
        balance: Account balance extracted from dashboard (float)
        
    Returns:
        None
    """
    from accounts.models import Device  # Import here to avoid circular imports
    from django.db import transaction   # Transaction decorator for atomicity
    
    try:
        # Start atomic transaction with row-level locking
        with transaction.atomic():
            # Get device and lock row (prevents concurrent updates)
            device = Device.objects.select_for_update().get(id=device_id)
            
            # Update device fields
            device.session_data = session_data_json  # Store browser session
            device.balance = float(balance)          # Update account balance
            device.status = "Active"                 # Mark as connected
            
            # Save only specific fields (performance optimization)
            device.save(update_fields=['session_data', 'balance', 'status'])
            
            # Log successful update
            logger.info(f"[DATABASE] ✓ Device {device_id} updated successfully.")
            
    except Device.DoesNotExist:
        # Device not found in database
        logger.error(f"[DATABASE ERROR] Device {device_id} not found in database.")
        
    except Exception as e:
        # Any other database error
        logger.error(f"[DATABASE ERROR] Failed to update device {device_id}: {e}")


# ============================================================================
# MAIN PLAYWRIGHT SESSION MANAGER CLASS
# ============================================================================
class PlaywrightSessionManager:
    """
    Browser automation manager for telecom operator logins.
    
    Complete Login Workflow:
        1. Initialize browser (Playwright + Chromium)
        2. Navigate to operator login page
        3. Handle cookie consent
        4. Fill phone number and request OTP
        5. Wait for OTP via Redis pub/sub (blocking)
        6. Enter OTP and confirm
        7. Extract balance from dashboard
        8. Save session data to database
        9. Clean up all resources
    
    Design Philosophy:
        - Synchronous execution (no threading)
        - Celery handles concurrency
        - Each task runs independently
        - Resources always cleaned up
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
        
        Workflow Steps:
            PHASE 1: Browser Setup
                - Start Playwright
                - Launch Chromium
                - Create browser context
                - Open new page
            
            PHASE 2: Navigation & OTP Request
                - Navigate to operator URL
                - Handle cookie consent
                - Click login button
                - Fill phone number
                - Click "Send OTP"
                - Wait for OTP input box
            
            PHASE 3: OTP Reception (BLOCKING)
                - Connect to Redis
                - Subscribe to device channel
                - Listen for OTP message
                - Timeout after 5 minutes
            
            PHASE 4: OTP Entry & Confirmation
                - Type OTP digit by digit
                - Wait for button to enable
                - Click confirm button
            
            PHASE 5: Balance Extraction
                - Wait for dashboard to load
                - Locate balance element
                - Extract numeric value
            
            PHASE 6: Session Capture
                - Get browser cookies/storage
                - Serialize to JSON
                - Save to database
            
            PHASE 7: Cleanup
                - Close browser
                - Stop Playwright
                - Close Redis connection
        
        Args:
            device_id: Unique device identifier (used for Redis channel)
            operator_url: Login page URL (e.g., https://myrobi.com)
            sim_number: Phone number to login with
            headless: Browser visibility (None=from env, True=hidden, False=visible)
            
        Returns:
            Tuple of (success: bool, message: str)
            
        Example Success:
            (True, "Login successful. Balance: ৳123.45")
            
        Example Failure:
            (False, "OTP timeout: No response received in 300 seconds")
        """
        # ====================================================================
        # VARIABLE INITIALIZATION
        # ====================================================================
        # Initialize all variables to None for cleanup in finally block
        playwright = None  # Playwright engine instance
        browser = None     # Browser instance
        r = None           # Redis connection
        page = None        # Browser page/tab

        try:
            # ================================================================
            # PHASE 1: BROWSER INITIALIZATION
            # ================================================================
            logger.info(f"[SESSION] Starting login for device {device_id}")
            
            # Determine headless mode (visible browser for debugging)
            if headless is None:
                # Get from environment variable (default: "true")
                headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
            
            logger.info(f"[BROWSER] Headless mode: {headless}")
            
            # Start Playwright engine
            playwright = sync_playwright().start()
            
            # Launch Chromium browser with anti-detection settings
            browser = playwright.chromium.launch(
                headless=headless,                                  # Browser visibility
                slow_mo=100,                                        # Slow down actions by 100ms
                args=[
                    '--disable-blink-features=AutomationControlled',  # Hide automation
                    '--no-sandbox',                                   # Required for Docker
                    '--disable-dev-shm-usage',                        # Prevent memory issues
                    '--disable-gpu'                                   # Disable GPU acceleration
                ]
            )
            
            # Create browser context (isolated session with cookies/storage)
            context = browser.new_context(
                user_agent=(  # Realistic user agent to avoid detection
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={'width': 1920, 'height': 1080},  # Desktop resolution
                locale='en-US'                              # Language setting
            )
            
            # Create new page (tab)
            page = context.new_page()

            # ================================================================
            # PHASE 2: NAVIGATION AND OTP REQUEST
            # ================================================================
            logger.info(f"[STEP 1] Navigating to: {operator_url}")
            
            # Navigate to operator login page
            page.goto(
                operator_url,                    # Target URL
                wait_until="domcontentloaded",   # Wait for DOM to be ready
                timeout=PAGE_LOAD_TIMEOUT        # 60 second timeout
            )
            
            # Capture initial page state for debugging
            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step1_loaded.png")
            
            # Handle cookie consent popup if present
            logger.info("[STEP 2] Handling cookie consent")
            try:
                page.wait_for_timeout(2000)  # Wait for popup to appear
                # Click "Accept Cookies" button if visible
                page.locator('button:has-text("Accept Cookies")').click(timeout=5000)
                logger.info("[COOKIE] ✓ Cookies accepted")
            except:
                # Popup not found or already accepted
                logger.info("[COOKIE] No cookie consent found")
            
            # Click login button
            logger.info("[STEP 3] Clicking login button")
            login_btn = page.locator('button:has-text("Log In"), .mui-10pnwxb').first
            login_btn.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)  # Wait until visible
            login_btn.click()                                              # Click button
            page.wait_for_timeout(2000)                                    # Wait for modal
            
            # Fill phone number
            logger.info(f"[STEP 4] Filling phone number: {sim_number}")
            num_input = page.locator('input[name="robiNumber"]')  # Find input field
            num_input.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)  # Wait until visible
            
            # Clear any cached/autofilled value
            num_input.click()       # Focus on input
            num_input.fill("")      # Clear existing value
            page.wait_for_timeout(500)  # Wait for clear
            
            # Type number digit by digit to avoid autofill interference
            for digit in sim_number:
                page.keyboard.press(digit)   # Type one digit
                page.wait_for_timeout(50)    # Small delay between digits
            
            page.wait_for_timeout(1000)  # Wait for React to process
            
            # Capture number input state for debugging
            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step4_number_filled.png")
            
            # Request OTP
            logger.info("[STEP 5] Requesting OTP")
            send_otp_btn = page.locator('button:has-text("Send OTP"), .mui-1twuwjc')
            send_otp_btn.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)  # Wait until visible
            send_otp_btn.click()                                              # Click button
            page.wait_for_timeout(3000)                                       # Wait for response
            
            # Capture post-OTP request state
            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step5_otp_requested.png")
            
            # Check for error messages
            try:
                error_msg = page.locator('text=/error|invalid|wrong/i').first
                if error_msg.is_visible(timeout=2000):  # Check if error visible
                    error_text = error_msg.inner_text()  # Get error text
                    logger.error(f"[ERROR] OTP request failed: {error_text}")
                    return False, f"OTP request failed: {error_text}"
            except:
                pass  # No error found, continue
            
            # Wait for OTP input box to appear
            logger.info("[STEP 6] Waiting for OTP input box")
            first_otp_box = page.locator("#otp-0")  # First digit input box
            
            try:
                first_otp_box.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)  # Wait for box
                logger.info(f"[OTP] ✓ OTP input box appeared for {sim_number}")
            except PlaywrightTimeout:
                # OTP box didn't appear - likely an error occurred
                if DEBUG_SCREENSHOTS:
                    page.screenshot(path=f"/app/debug_{device_id}_ERROR_no_otp_box.png")
                logger.error("[ERROR] OTP input box did not appear")
                return False, "OTP input box did not appear. Check screenshots."

            # ================================================================
            # PHASE 3: REDIS OTP LISTENER (BLOCKING - NO THREADING)
            # ================================================================
            logger.info(f"[OTP] Waiting on Redis channel for device {device_id}...")
            
            # Connect to Redis server
            r = redis.Redis(
                host=REDIS_HOST,           # Redis hostname
                port=REDIS_PORT,           # Redis port
                db=REDIS_DB,               # Database number
                decode_responses=True      # Auto-decode bytes to strings
            )
            
            # Subscribe to device-specific OTP channel
            pubsub = r.pubsub()                        # Create pub/sub object
            channel_name = f"otp_channel_{device_id}"  # Channel name format
            pubsub.subscribe(channel_name)             # Subscribe to channel
            
            logger.info(f"[REDIS] Subscribed to channel: {channel_name}")
            
            # Initialize OTP variable and timer
            otp = None              # Will store received OTP
            start_time = time.time()  # Record start time for timeout
            
            # Listen for OTP messages (BLOCKING LOOP)
            for message in pubsub.listen():
                # Check if timeout exceeded
                elapsed = time.time() - start_time  # Calculate elapsed time
                if elapsed > OTP_TIMEOUT:
                    # Timeout occurred - no OTP received
                    error_msg = f"OTP timeout: No response in {OTP_TIMEOUT} seconds"
                    logger.error(f"[TIMEOUT] {error_msg}")
                    return False, error_msg
                
                # Check if message is an OTP
                if message.get("type") == "message":
                    otp = message["data"]  # Extract OTP from message
                    logger.info(f"[REDIS] ✓ OTP received: {otp} (after {elapsed:.1f}s)")
                    break  # Exit listener loop
            
            # Verify OTP was received
            if not otp:
                return False, "OTP not received from Redis channel."
            
            # ================================================================
            # PHASE 4: OTP ENTRY AND CONFIRMATION
            # ================================================================
            logger.info(f"[STEP 7] Entering OTP: {otp}")
            
            # Validate OTP format
            otp_str = str(otp).strip()  # Convert to string and remove whitespace
            
            if len(otp_str) != 6:
                # Invalid OTP length
                error_msg = f"Invalid OTP length: {len(otp_str)} (expected 6)"
                logger.error(f"[ERROR] {error_msg}")
                return False, error_msg
            
            # Clear any previous OTP state (for React-based sites)
            try:
                # JavaScript to clear all OTP input boxes
                page.evaluate(
                    "document.querySelectorAll('input[id^=\"otp-\"]')"
                    ".forEach(el => el.value = '')"
                )
            except:
                pass  # Not critical if this fails
            
            # Focus on first OTP input box
            first_box = page.locator("#otp-0")
            first_box.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)  # Wait for box
            first_box.click()                                              # Focus on box
            page.wait_for_timeout(800)  # Wait for React state initialization
            
            # Type each digit with delay (important for React state updates)
            for i, digit in enumerate(otp_str):
                page.keyboard.press(digit)   # Type digit
                page.wait_for_timeout(250)   # Wait for React to update state
                logger.info(f"[OTP] Digit {i+1}/6 entered")
            
            # CRITICAL: Wait for React to process all digits
            page.wait_for_timeout(1500)  # Extra wait for full state update
            
            # Capture OTP entry state for debugging
            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_step7_otp_entered.png")
            
            # Confirm OTP
            logger.info("[STEP 8] Confirming OTP")
            
            confirm_success = False  # Track if confirmation succeeded
            
            # Strategy 1: Wait for button to be enabled (normal flow)
            try:
                logger.info("[CONFIRM] Waiting for button to be enabled...")
                
                # Wait for confirm button to be enabled (not disabled)
                page.wait_for_selector(
                    'button:has-text("Confirm OTP"):not([disabled])',  # Selector
                    timeout=10000,                                     # 10 second timeout
                    state='visible'                                    # Must be visible
                )
                
                # Click confirm button
                page.locator('button:has-text("Confirm OTP")').click()
                confirm_success = True  # Mark as successful
                logger.info("[CONFIRM] ✓ Button clicked via Strategy 1")
                
            except PlaywrightTimeout:
                # Button didn't enable in time - try fallback
                logger.warning("[CONFIRM] Strategy 1 failed, trying Strategy 2...")
            
            # Strategy 2: Force click with JavaScript (fallback)
            if not confirm_success:
                try:
                    # JavaScript to find and click button
                    page.evaluate("""
                        const btn = document.querySelector('button[class*="mui"]:not([disabled])');
                        if (btn && btn.textContent.includes('Confirm')) {
                            btn.click();  // Force click via JavaScript
                        }
                    """)
                    confirm_success = True  # Mark as successful
                    logger.info("[CONFIRM] ✓ Button clicked via Strategy 2 (JavaScript)")
                    
                except:
                    # Both strategies failed
                    logger.error("[CONFIRM] Strategy 2 also failed")
            
            # Verify confirmation succeeded
            if not confirm_success:
                return False, "Could not click Confirm OTP button after multiple attempts"
            
            # Wait for page to process confirmation
            page.wait_for_timeout(3000)

            # ================================================================
            # PHASE 5: BALANCE EXTRACTION
            # ================================================================
            logger.info("[STEP 9] Waiting for dashboard to load")
            
            # Try to find balance element using exact class from HTML
            balance_elem = page.locator(
                'p.MuiTypography-root.MuiTypography-body1.mui-v247a6'
            ).first
            
            try:
                # Wait for balance element to appear
                balance_elem.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
                logger.info("[BALANCE] ✓ Balance element found")
                
            except PlaywrightTimeout:
                # Primary selector failed - try fallback
                logger.warning("[BALANCE] Primary selector failed, trying fallback...")
                
                try:
                    # Fallback: Find parent element of currency symbol
                    balance_elem = page.locator(
                        'span.MuiTypography-kohinoorBangla:has-text("৳")'
                    ).locator('..').first  # Get parent element
                    
                    balance_elem.wait_for(state="visible", timeout=10000)  # Wait
                    logger.info("[BALANCE] ✓ Balance found using fallback selector")
                    
                except:
                    # Could not find balance element at all
                    if DEBUG_SCREENSHOTS:
                        page.screenshot(
                            path=f"/app/debug_{device_id}_ERROR_no_balance.png"
                        )
                    logger.error("[ERROR] Could not find balance element")
                    return False, "Could not find balance element on dashboard"
            
            # Extract balance text from element
            raw_text = balance_elem.inner_text()  # Get text content
            
            # Parse numeric value from text
            clean_balance = PlaywrightSessionManager._extract_balance(raw_text)
            
            logger.info(f"[BALANCE] Extracted balance: ৳{clean_balance}")
            
            # Capture successful dashboard state
            if DEBUG_SCREENSHOTS:
                page.screenshot(path=f"/app/debug_{device_id}_SUCCESS_dashboard.png")

            # ================================================================
            # PHASE 6: SESSION DATA CAPTURE AND DATABASE UPDATE
            # ================================================================
            logger.info("[STEP 10] Capturing session data")
            
            # Get browser cookies and local storage
            storage_state = context.storage_state()  # Returns dict with cookies/storage
            
            # Serialize to JSON string for database storage
            session_data_json = json.dumps(storage_state, indent=2)
            
            # Update device in database
            update_device_in_db(
                device_id=device_id,
                session_data_json=session_data_json,
                balance=clean_balance
            )
            
            # Log successful completion
            logger.info(f"[SUCCESS] ✓ Full login flow completed for device {device_id}")
            
            # Return success result
            return True, f"Login successful. Balance: ৳{clean_balance}"
            
        # ====================================================================
        # ERROR HANDLING - CATCH ALL EXCEPTIONS
        # ====================================================================
        except PlaywrightTimeout as e:
            # Playwright operation timed out
            error_msg = f"Playwright timeout: {str(e)}"
            logger.error(f"[ERROR] {error_msg}")
            
            # Capture error screenshot if possible
            if DEBUG_SCREENSHOTS and page:
                try:
                    page.screenshot(path=f"/app/debug_{device_id}_ERROR_timeout.png")
                except:
                    pass  # Screenshot failed, continue
            
            return False, error_msg
            
        except redis.RedisError as e:
            # Redis connection error
            error_msg = f"Redis connection error: {str(e)}"
            logger.error(f"[ERROR] {error_msg}")
            return False, error_msg
            
        except ValueError as e:
            # Invalid input (e.g., bad OTP format)
            error_msg = f"Invalid input: {str(e)}"
            logger.error(f"[ERROR] {error_msg}")
            return False, error_msg
            
        except Exception as e:
            # Any other unexpected error
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"[ERROR] {error_msg}", exc_info=True)  # Include traceback
            
            # Capture error screenshot
            if DEBUG_SCREENSHOTS and page:
                try:
                    page.screenshot(
                        path=f"/app/debug_{device_id}_ERROR_unexpected.png"
                    )
                except:
                    pass  # Screenshot failed, continue
            
            return False, error_msg
            
        finally:
            # ================================================================
            # PHASE 7: RESOURCE CLEANUP (ALWAYS EXECUTED)
            # ================================================================
            logger.info(f"[CLEANUP] Closing all resources for device {device_id}")
            
            # Close Redis connection
            if r:
                try:
                    r.close()  # Close connection
                    logger.info("[CLEANUP] ✓ Redis connection closed")
                except Exception as e:
                    logger.error(f"[CLEANUP ERROR] Failed to close Redis: {e}")
            
            # Close browser
            if browser:
                try:
                    browser.close()  # Close all pages and tabs
                    logger.info("[CLEANUP] ✓ Browser closed")
                except Exception as e:
                    logger.error(f"[CLEANUP ERROR] Failed to close browser: {e}")
            
            # Stop Playwright engine
            if playwright:
                try:
                    playwright.stop()  # Stop Playwright process
                    logger.info("[CLEANUP] ✓ Playwright stopped")
                except Exception as e:
                    logger.error(f"[CLEANUP ERROR] Failed to stop Playwright: {e}")
            
            logger.info(f"[CLEANUP] ✓ All resources cleaned up for device {device_id}")
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    @staticmethod
    def _extract_balance(raw_text: str) -> float:
        """
        Extract numeric balance value from text containing currency symbols.
        
        Handles multiple formats commonly seen on operator dashboards:
            - "৳ 0.27"          → 0.27
            - "৳0.27"           → 0.27
            - "৳ 1,234.56"      → 1234.56
            - "৳ <!-- --> 0.27" → 0.27 (with HTML comments)
        
        Process:
            1. Remove currency symbols (৳)
            2. Remove HTML comments
            3. Remove whitespace
            4. Extract number using regex
            5. Convert to float
        
        Args:
            raw_text: Raw text from balance element (e.g., "৳ 123.45")
            
        Returns:
            Float balance value (0.0 if extraction fails)
            
        Example:
            >>> _extract_balance("৳ 1,234.56")
            1234.56
        """
        try:
            logger.info(f"[BALANCE] Raw text: '{raw_text}'")
            
            # Step 1: Remove currency symbol
            cleaned = raw_text.replace("৳", "")
            
            # Step 2: Remove HTML comments
            cleaned = cleaned.replace("<!--", "").replace("-->", "")
            
            # Step 3: Remove whitespace
            cleaned = cleaned.strip()
            
            # Step 4: Extract number using regex
            # Pattern matches: digits, commas, optional decimal point, more digits
            # Examples: "1234", "1,234", "1234.56", "1,234.56"
            match = re.search(r"([\d,]+\.?\d*)", cleaned)
            
            if match:
                # Step 5: Remove commas and convert to float
                balance_str = match.group(1).replace(",", "")  # Remove commas
                balance_value = float(balance_str)              # Convert to float
                
                logger.info(f"[BALANCE] Extracted: {balance_value}")
                return balance_value
            else:
                # No number found in text
                logger.warning(f"[WARNING] Could not extract balance from: {raw_text}")
                return 0.0
                
        except Exception as e:
            # Error during extraction
            logger.error(f"[ERROR] Balance extraction failed: {e}")
            return 0.0
    
    @staticmethod
    def get_active_session_count() -> int:
        """
        Get count of currently active browser sessions in memory.
        
        Note: Currently unused as each task runs independently.
        Reserved for future multi-session management.
        
        Returns:
            Number of active sessions (integer)
        """
        return len(active_sessions)
    
    @staticmethod
    def cleanup_all_sessions() -> None:
        """
        Emergency cleanup of all active sessions in memory.
        
        Use cases:
            - Graceful shutdown
            - Error recovery
            - Memory cleanup
        
        Note: Currently unused as sessions are managed per-task.
        
        Returns:
            None
        """
        logger.info("[CLEANUP] Cleaning up all active sessions from memory")
        active_sessions.clear()  # Clear dictionary
        logger.info("[CLEANUP] ✓ All sessions cleared")