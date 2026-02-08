import json
import re
import redis
from playwright.sync_api import sync_playwright

active_sessions = {}

# ==============================================================================
# DATABASE HELPER
# ==============================================================================
def update_device_in_db(device_id, session_data_json, balance):
    from accounts.models import Device
    try:
        device = Device.objects.get(id=device_id)
        device.session_data = session_data_json
        device.balance = float(balance)
        device.status = 'Connected'
        device.save()
        print(f"[DATABASE] Success: Device {device_id} updated.")
    except Exception as e:
        print(f"[DATABASE ERROR] Failed to update device {device_id}: {e}")


# ==============================================================================
# SESSION MANAGER
# ==============================================================================
class PlaywrightSessionManager:
    
    from playwright.sync_api import sync_playwright

active_sessions = {}  # assuming global
# r = redis client (already defined)

class YourClass:

    @staticmethod
    def start_login_flow(device_id, operator_url, sim_number):
        """
        Part 1: Opens browser, fills phone number, and clicks Send OTP.
        Then listens OTP from Redis pubsub and completes login.
        """
        playwright = None
        browser = None

        try:
            playwright = sync_playwright().start()

            # Use headless=True for Docker. Use headless=False only with local XLaunch.
            browser = playwright.chromium.launch(headless=True, slow_mo=100)

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # Navigate to operator URL
            page.goto(operator_url, wait_until="domcontentloaded", timeout=60000)

            # Handle possible cookie consent
            try:
                page.wait_for_timeout(2000)
                cookie_btn = page.locator('button:has-text("Accept Cookies")')
                if cookie_btn.is_visible(timeout=5000):
                    cookie_btn.click()
            except Exception:
                pass

            # Open Login modal and input SIM
            page.locator('button:has-text("Log In"), .mui-10pnwxb').first.click()

            num_input = page.locator('input[name="robiNumber"]')
            num_input.wait_for(state="visible", timeout=15000)
            num_input.fill(sim_number)

            # Click Send OTP
            page.locator('button:has-text("Send OTP"), .mui-1twuwjc').click()

            # Store objects for the next step
            active_sessions[device_id] = {
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
            }

            # Listen for OTP from Redis PubSub (blocking loop)
            r = redis.Redis(host='redis', port=6379, db=0)
            pubsub = r.pubsub()
            pubsub.subscribe(f"otp_channel_{device_id}")

            for message in pubsub.listen():
                if message.get("type") == "message":
                    otp = message["data"].decode("utf-8")
                    # staticmethod, so no self
                    return YourClass.complete_login_flow(device_id, otp)

            # If loop breaks unexpectedly
            return False, "OTP listener stopped unexpectedly."

        except Exception as e:
            try:
                if browser:
                    browser.close()
            finally:
                if playwright:
                    playwright.stop()
            return False, str(e)


    @staticmethod
    def redis_otp_listener(device_id):
        """
        Part 2: Background listener that waits for OTP from Redis.
        """
        r = redis.Redis(host='redis', port=6379, db=0)
        pubsub = r.pubsub()
        pubsub.subscribe(f'otp_channel_{device_id}')
        
        print(f"[*] Thread started: Waiting for OTP on channel otp_channel_{device_id}")

        for message in pubsub.listen():
            if message['type'] == 'message':
                otp = message['data'].decode('utf-8')
                print(f"[*] OTP received from Redis for device {device_id}: {otp}")
                PlaywrightSessionManager.complete_login_flow(device_id, otp)
                break

    @staticmethod
    def complete_login_flow(device_id, otp):
        """
        Part 3: Inputs OTP using raw keyboard events, confirms, and fetches balance.
        """
        session = active_sessions.get(device_id)
        if not session:
            print(f"[-] Session not found for device {device_id}")
            return

        page = session['page']
        try:
            # 1. Focus the first OTP box
            first_box = page.locator("#otp-0")
            first_box.wait_for(state='visible', timeout=15000)
            first_box.click()
            
            # 2. Type 6-digit OTP using Keyboard Press (Triggers MUI state updates)
            otp_str = str(otp).strip()
            print(f"[*] Typing 6-digit OTP into boxes...")
            for digit in otp_str[:6]:
                page.keyboard.press(digit)
                page.wait_for_timeout(100) # Small delay to allow auto-focus to move to next box

            # 3. Wait for the Confirm button to be enabled
            confirm_btn = page.locator('button:has-text("Confirm OTP"), .mui-1fds9z')
            confirm_btn.wait_for(state='enabled', timeout=15000)
            confirm_btn.click()
            print("[*] Confirm OTP clicked.")

            # 4. Wait for dashboard to load and find Taka symbol (৳)
            balance_elem = page.locator("p:has-text('৳'), span:has-text('৳')").first
            balance_elem.wait_for(state='visible', timeout=60000)
            
            # 5. Extract balance text
            raw_text = balance_elem.inner_text()
            # Regex extracts the numeric part (e.g., 0.27 or 1,200.50)
            match = re.search(r'([\d,]+\.?\d+)', raw_text.replace('৳', ''))
            clean_balance = match.group(1).replace(',', '') if match else "0.00"

            # 6. Capture full storage state (Cookies + LocalStorage)
            storage_state = session['context'].storage_state()
            session_data_json = json.dumps(storage_state)

            print(f"[DONE] Login successful. Balance: {clean_balance}")

            # 7. Update Database via Helper
            update_device_in_db(device_id, session_data_json, clean_balance)

        except Exception as e:
            print(f"[ERROR] complete_login_flow failed: {e}")
            try: page.screenshot(path=f"error_device_{device_id}.png")
            except Exception: pass
            
        finally:
            # Shutdown browser resources properly
            print(f"[CLEANUP] Closing browser session for device {device_id}")
            session['browser'].close()
            session['playwright'].stop()
            if device_id in active_sessions:
                del active_sessions[device_id]