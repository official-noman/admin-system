import json
import re
from playwright.sync_api import sync_playwright

active_sessions = {}

class PlaywrightSessionManager:
    
    @staticmethod
    def start_login_flow(device_id, operator_url, sim_number):
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=False, slow_mo=100) 
            context = browser.new_context()
            page = context.new_page()

            page.goto(operator_url, timeout=60000)

            # Handle Cookie Consent
            try:
                cookie_btn = page.locator('button:has-text("Accept Cookies")')
                if cookie_btn.is_visible(timeout=3000):
                    cookie_btn.click()
            except:
                pass

            # Open Login Modal
            login_btn = page.locator('button:has-text("Log In")').first
            login_btn.wait_for(state='visible', timeout=10000)
            login_btn.click()

            # Fill Number
            phone_input = page.locator('[name="robiNumber"]')
            phone_input.wait_for(state='visible', timeout=10000)
            phone_input.fill(sim_number)
            
            # Request OTP
            page.locator('button:has-text("Send OTP")').click()

            active_sessions[device_id] = {
                'playwright': playwright,
                'browser': browser,
                'context': context,
                'page': page
            }
            return True, "OTP sent successfully."

        except Exception as e:
            if 'browser' in locals(): browser.close()
            if 'playwright' in locals(): playwright.stop()
            return False, str(e)

    @staticmethod
    def complete_login_flow(device_id, otp):
        session = active_sessions.get(device_id)
        if not session:
            return False, "Session expired or not found."

        page = session['page']
        browser = session['browser']
        playwright = session['playwright']

        try:
            # MUI OTP fields often respond best to direct keyboard typing
            first_otp_box = page.locator("#otp-0")
            first_otp_box.wait_for(state='visible', timeout=5000)
            first_otp_box.click()
            
            # Clear and type OTP
            page.keyboard.type(str(otp), delay=100)

            # Wait for Confirm button to become enabled (MUI specific)
            confirm_btn = page.locator('button:has-text("Confirm OTP")')
            confirm_btn.wait_for(state='enabled', timeout=10000)
            confirm_btn.click()

            # Wait for Dashboard Load (Taka Symbol)
            balance_elem = page.locator("p:has-text('৳')").first
            balance_elem.wait_for(state='visible', timeout=45000)
            
            raw_text = balance_elem.inner_text()
            # Professional Regex for currency extraction
            match = re.search(r'৳\s*([\d,]+\.?\d*)', raw_text)
            clean_balance = match.group(1).replace(',', '') if match else "0.00"

            storage_state = session['context'].storage_state()
            
            result = {
                'session': storage_state,
                'balance': clean_balance
            }

            return True, json.dumps(result)

        except Exception as e:
            return False, str(e)
        finally:
            # Crucial: Always close resources
            browser.close()
            playwright.stop()
            if device_id in active_sessions:
                del active_sessions[device_id]