# File: accounts/services/playwright_login.py

import json
from playwright.sync_api import sync_playwright, TimeoutError

def get_operator_session(operator_url, sim_number, otp):
    """
    Logs into Robi's website, handles cookies, and returns session data as a JSON string.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context()
        page = context.new_page()

        try:
            # 1. Navigate to the main page and handle initial cookie consent
            print(f"Navigating to {operator_url}...")
            page.goto(operator_url, timeout=60000)
            page.locator('button:has-text("Accept Cookies")').wait_for(timeout=10000).click() 
            
            # Check for and click the "Accept Cookies" button if it exists
            if page.locator('button:has-text("Accept Cookies")').is_visible():
                print("Accepting cookies...")
                page.locator('button:has-text("Accept Cookies")').click()

            # 2. Click the main "Log In" button to open the login modal
            print("Clicking the main 'Log In' button...")
            page.locator('a:has-text("Log In")').first.click()

            # 3. Wait for the login form and fill in the phone number
            print(f"Filling in phone number: {sim_number}")
            # The phone input is inside a frame, we need to locate it correctly
            phone_input_locator = page.locator('input[placeholder="Enter your number"]')
            phone_input_locator.wait_for(timeout=30000)
            phone_input_locator.fill(sim_number)

            # 4. Click the button to request OTP
            print("Requesting OTP...")
            page.locator('button:has-text("Get OTP")').click()
            
            # 5. Wait for the OTP input field and fill in the OTP
            print(f"Waiting for OTP input and filling in: {otp}")
            otp_input_locator = page.locator('input[placeholder="Enter OTP"]')
            otp_input_locator.wait_for(timeout=30000)
            otp_input_locator.fill(otp)
            
            # 6. Click the final submit/login button
            page.locator('button:has-text("Login")').click()

            # 7. Wait for a reliable element on the dashboard to confirm successful login
            print("Waiting for dashboard to load...")
            # We wait for the balance icon or similar element to confirm login
            page.locator("text=Balance").first.wait_for(timeout=45000)
            
            print("Login successful! Extracting session data.")

            # 8. Extract the entire session state (cookies + local storage)
            storage_state = context.storage_state()
            session_data_json = json.dumps(storage_state)
            
            return session_data_json

        except TimeoutError as e:
            print(f"Playwright script timed out: {e}")
            print("Possible causes: Incorrect OTP, slow network, or website structure changed.")
            return None
        except Exception as e:
            print(f"An unexpected error occurred in the Playwright script: {e}")
            return None
        finally:
            print("Closing browser.")
            browser.close()