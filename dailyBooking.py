import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from playwright.sync_api import Playwright, sync_playwright, expect

# ==============================================================================
# EXTERNALIZED CONFIGURATION (FETCHED FROM ENV / SECRETS WITH FALLBACKS)
# ==============================================================================
DAYS_IN_ADVANCE = int(os.environ.get("DAYS_IN_ADVANCE", "10"))
MAX_START_HOUR = int(os.environ.get("MAX_START_HOUR", "22"))  # 10 PM
SLOT_OFFSET_MINUTES = int(os.environ.get("SLOT_OFFSET_MINUTES", "60"))

# Fallback priority order if no day-specific override matches
DEFAULT_PRIORITY_ORDER = "19:30+20:30, 20:00+21:00, 19:00+20:00, 18:30+19:30, 20:30+SPLIT, 17:30+18:30, 17:00+18:00"
PRIORITY_ORDER_CONFIG = os.environ.get("PRIORITY_ORDER", DEFAULT_PRIORITY_ORDER)

# Parse Day-Specific Priorities from JSON Environment Variable (DAY_PRIORITIES_JSON)
DAY_PRIORITIES_ENV = os.environ.get("DAY_PRIORITIES_JSON", "{}")
try:
    DAY_SPECIFIC_PRIORITIES = json.loads(DAY_PRIORITIES_ENV)
except Exception as err:
    print(f"Warning: Failed to parse DAY_PRIORITIES_JSON ({err}). Defaulting to empty map.")
    DAY_SPECIFIC_PRIORITIES = {}

HEADLESS_MODE = os.environ.get("HEADLESS", "true").lower() == "true"

EMAIL = os.environ.get("ASPIRE_EMAIL")
PASSWORD = os.environ.get("ASPIRE_PASS")
# ==============================================================================


def parse_slot_time(slot_text: str):
    """Extracts ONLY start hour and start minute from text like '14:00 60 minutes Badminton'."""
    clean_text = " ".join(slot_text.split())
    match = re.search(r"\b(\d{2}):(\d{2})\b", clean_text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def click_continue_button(page, step_label: str):
    """Targets the Continue/Confirm button with robust multi-selector fallbacks."""
    primary_selector = '[data-test-id="universalbasket-paymentsummary-continueoptions-continue"]'
    print(f"[{step_label}] Waiting for action button...")

    btn = None
    target_selector = primary_selector

    try:
        page.wait_for_selector(primary_selector, state="visible", timeout=10000)
        btn = page.locator(primary_selector)
    except Exception:
        print(f"[{step_label}] Primary selector not found, scanning for submit/confirm fallbacks...")
        fallbacks = [
            'button:has-text("Continue")',
            'button:has-text("Pay")',
            'button:has-text("Confirm")',
            'button:has-text("Complete")',
            'input[type="submit"]',
            'a:has-text("Continue")'
        ]
        for fb in fallbacks:
            loc = page.locator(fb).first
            if loc.is_visible():
                btn = loc
                target_selector = fb
                print(f"[{step_label}] Matched fallback selector: {fb}")
                break

    if not btn:
        print(f"[{step_label}] Warning: No continue/confirm button found. Page may have already transitioned.")
        return

    current_url = page.url
    print(f"[{step_label}] Clicking button via Playwright click...")

    try:
        btn.hover()
        btn.focus()
        btn.click(force=True)
    except Exception as e:
        print(f"[{step_label}] Direct click failed ({e}). Attempting JS click...")

    time.sleep(2)

    if page.url == current_url:
        print(f"[{step_label}] URL unchanged. Dispatching safe JS click on '{target_selector}'...")
        try:
            page.eval_on_selector(target_selector, "el => el.click()")
            time.sleep(2)
        except Exception as js_err:
            print(f"[{step_label}] JS click bypassed or unnecessary: {js_err}")

    page.wait_for_load_state("networkidle")


def checkout_basket(page):
    """Executes the zero-cost checkout flow for all items in the basket."""
    print("Starting single combined basket checkout flow...")

    click_continue_button(page, "Step 1: Basket Summary")

    print("Checking for Terms & Conditions checkbox...")
    terms_selector = '[data-test-id="shared-checkbox-i-accept-the-terms-&-conditions-input"]'
    terms_checkbox = page.locator(terms_selector)

    try:
        expect(terms_checkbox).to_be_visible(timeout=8000)
        terms_checkbox.check()
        time.sleep(1)
        print("Terms & Conditions checkbox checked.")
    except Exception:
        print("Terms & Conditions checkbox not present or already checked.")

    click_continue_button(page, "Step 2: Final Confirmation")


def run(playwright: Playwright) -> None:
    if not PASSWORD:
        print("ERROR: ASPIRE_PASS environment variable is missing. Exiting.")
        sys.exit(1)

    # 1. Target Date Calculation & Day-of-Week Resolution
    target_date = datetime.now() + timedelta(days=DAYS_IN_ADVANCE)
    day_number_str = str(target_date.day)
    day_name = target_date.strftime('%A')  # e.g., 'Saturday', 'Sunday'

    # Get day-specific rule string or None
    day_rule_string = DAY_SPECIFIC_PRIORITIES.get(day_name)

    print(f"Target date: {target_date.strftime('%Y-%m-%d')} ({day_name}, Day: {day_number_str}) [+{DAYS_IN_ADVANCE} days]")
    if day_rule_string:
        print(f"Active Day Rule for {day_name}: {day_rule_string}")
        print(f"General Fallback Sequence: {PRIORITY_ORDER_CONFIG}")
    else:
        print(f"Active Priority Sequence for {day_name}: {PRIORITY_ORDER_CONFIG}")

    print(f"Launching Chromium (Headless: {HEADLESS_MODE})...")

    browser = playwright.chromium.launch(headless=HEADLESS_MODE)
    context = browser.new_context()
    page = context.new_page()

    # 2. Smart Login Check
    print("Navigating to portal...")
    page.goto("https://aspiredefence.legendonlineservices.co.uk/agsc/account/login")
    page.wait_for_load_state("networkidle")

    email_field = page.locator('[data-test-id="login-email"]')
    if email_field.is_visible():
        print(f"Session not found. Logging in as: {EMAIL}...")
        email_field.click()
        email_field.fill(EMAIL)
        email_field.press("Tab")
        page.locator('[data-test-id="login-password"]').fill(PASSWORD)
        page.locator('[data-test-id="login-password"]').press("Enter")
        page.wait_for_load_state("networkidle")
    else:
        print("Already logged in! Bypassing login step...")

    # 3. Club Selection
    print("Selecting Drop in Bookings, Club (AGSC), and Category...")
    dropins_link = page.locator('[data-test-id="account-bookings-dropins"]')
    if dropins_link.is_visible():
        dropins_link.click()
        page.wait_for_load_state("networkidle")

    club_search = page.get_by_role("searchbox", name="Please select a clubs")
    try:
        if club_search.is_visible(timeout=5000):
            club_search.click()
            club_search.fill("agsc")
            club_search.press("Enter")
        else:
            raise Exception("Searchbox role not immediately visible")
    except Exception:
        print("Fallback club selection triggered...")
        selectors = [
            'input[placeholder*="select a club"]',
            'input[aria-label*="select a club"]',
            '.select2-search__field',
            '#ClubId',
            '.form-control'
        ]
        found = False
        for sel in selectors:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click()
                loc.fill("agsc")
                loc.press("Enter")
                found = True
                break
        if not found:
            print("Notice: Proceeding with default club selection.")

    page.get_by_text("Sports Hall").click()
    page.locator('[data-test-id="bookings-category-categories-sports-hall"]').check()
    page.locator('[data-test-id="bookings-activities-activity-badminton-online"]').check()

    # 6:00 AM Gatekeeper
    now = datetime.utcnow()
    target_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    wait_seconds = (target_6am - now).total_seconds()
    if 0 < wait_seconds <= 120:
        print(f"Pre-login completed! Holding at category view for {wait_seconds:.1f}s until 06:00:00 AM...")
        time.sleep(wait_seconds)

    # 4. View Timetable & Select Date
    print("Opening timetable view...")
    page.locator('[data-test-id="bookings-viewtimetable"]').click()
    page.wait_for_load_state("networkidle")

    print(f"Opening date picker, selecting day {day_number_str}, and pressing Enter...")
    date_textbox = page.get_by_role("textbox", name="Select Date")
    if not date_textbox.is_visible():
        date_textbox = page.get_by_role("button", name=" Click to open date picker")
    date_textbox.click()

    # Fixed date selection targeting only active current-month cells
    page.locator('td:not(.dp_disabled):not(.dp_not_in_month)').filter(has_text=re.compile(rf"^{day_number_str}$")).click()
    page.keyboard.press("Enter")

    page.wait_for_load_state("networkidle")
    time.sleep(3)

    # 5. Scan & Parse Available Slots (Strictly Ignoring Publicly Full Slots)
    print("Scanning timetable for available slots...")
    page.wait_for_selector('a:has-text("BADMINTON")', timeout=10000)
    raw_links = page.locator('a:has-text("BADMINTON"), a:has-text("Badminton")').all()

    available_slots = []
    existing_booked_mins = []  # Keep empty unless scraping actual account bookings page

    for link in raw_links:
        try:
            if not link.is_visible():
                continue
            text = link.text_content().strip()

            hour, minute = parse_slot_time(text)
            if hour is None or hour > MAX_START_HOUR:
                continue

            total_minutes = hour * 60 + minute

            # Ignore public full slots so they don't block adjacent availability via gap rules
            if "Full" in text or "0 Slots" in text or "Booked" in text or "Already Booked" in text:
                print(f"Ignoring public full slot: {hour:02d}:{minute:02d}")
                continue
            else:
                available_slots.append((total_minutes, hour, minute, text, link))
                print(f"Detected available slot: {hour:02d}:{minute:02d}")
        except Exception as scan_err:
            print(f"Skipped link due to scan error: {scan_err}")
            continue

    available_slots.sort(key=lambda x: x[0])

    if not available_slots:
        print(f"No available slots found on day {day_number_str}.")
        browser.close()
        return

    # Filter available slots by the +-60 min gap rule against ACTUAL existing account bookings only
    valid_candidate_slots = []
    for slot in available_slots:
        slot_mins = slot[0]
        violates_gap = False
        for booked_mins in existing_booked_mins:
            if abs(slot_mins - booked_mins) < SLOT_OFFSET_MINUTES:
                print(f"Excluding {slot[1]:02d}:{slot[2]:02d} (violates gap rule with account booking at {booked_mins//60:02d}:{booked_mins%60:02d})")
                violates_gap = True
                break
        if not violates_gap:
            valid_candidate_slots.append(slot)

    valid_map = {s[0]: s for s in valid_candidate_slots}
    print(f"Final Valid Map Keys (in mins): {list(valid_map.keys())}")

    first_slot = None
    second_slot = None

    def check_pair(m1, m2):
        if m1 in valid_map and m2 in valid_map and abs(m1 - m2) >= SLOT_OFFSET_MINUTES:
            return valid_map[m1], valid_map[m2]
        return None, None

    def to_mins(h, m):
        return h * 60 + m

    def parse_time_str(t_str):
        parts = t_str.strip().split(":")
        return to_mins(int(parts[0]), int(parts[1]))

    # --------------------------------------------------------------------------
    # DYNAMIC DAY-AWARE PRIORITY SEQUENCE EVALUATION WITH FALLBACK
    # --------------------------------------------------------------------------
    priority_list = []
    if day_rule_string:
        priority_list.extend([p.strip().rstrip(',') for p in day_rule_string.split(",") if p.strip()])

    # Append standard PRIORITY_ORDER_CONFIG rules as fallbacks if not already present
    default_rules = [p.strip().rstrip(',') for p in PRIORITY_ORDER_CONFIG.split(",") if p.strip()]
    for def_prio in default_rules:
        if def_prio not in priority_list:
            priority_list.append(def_prio)

    print(f"Evaluating combined priority sequence for {day_name}: {priority_list}")

    for prio in priority_list:
        if "+" in prio:
            t1_str, t2_str = prio.split("+")
            t1_str, t2_str = t1_str.strip(), t2_str.strip()

            # Dynamic 20:30 Split Rule (e.g. "20:30+SPLIT")
            if t2_str.upper() == "SPLIT":
                target_mins = parse_time_str(t1_str)
                if target_mins in valid_map:
                    target_slot = valid_map[target_mins]
                    earlier_candidates = [to_mins(19, 0), to_mins(18, 30), to_mins(18, 0), to_mins(17, 30), to_mins(17, 0)]
                    for cand_mins in earlier_candidates:
                        if cand_mins in valid_map and abs(target_mins - cand_mins) >= SLOT_OFFSET_MINUTES:
                            first_slot = valid_map[cand_mins]
                            second_slot = target_slot
                            print(f"Priority matched ({prio}): {first_slot[1]:02d}:{first_slot[2]:02d} + {second_slot[1]:02d}:{second_slot[2]:02d}")
                            break
                    if not first_slot:
                        first_slot = target_slot
                        print(f"Priority matched ({prio} - Single slot): {first_slot[1]:02d}:{first_slot[2]:02d}")
                    break
            else:
                # Regular 2-slot pair (e.g. "18:00+19:00" or "14:00+15:00")
                m1, m2 = parse_time_str(t1_str), parse_time_str(t2_str)
                s1, s2 = check_pair(m1, m2)
                if s1 and s2:
                    first_slot, second_slot = s1, s2
                    print(f"Priority matched ({prio}): {t1_str} + {t2_str}")
                    break

    # --------------------------------------------------------------------------
    # SINGLE SLOT FALLBACK SEQUENCE (Strictly Gap-Filtered)
    # --------------------------------------------------------------------------
    if not first_slot:
        single_priority_order = [
            to_mins(20, 30), to_mins(20, 0), to_mins(19, 30), to_mins(19, 0),
            to_mins(18, 30), to_mins(18, 0), to_mins(17, 30), to_mins(17, 0),
            to_mins(15, 0),  to_mins(14, 0), to_mins(9, 30),  to_mins(8, 30)
        ]
        for single_mins in single_priority_order:
            if single_mins in valid_map:
                first_slot = valid_map[single_mins]
                print(f"Single Slot Fallback matched: {first_slot[1]:02d}:{first_slot[2]:02d}")
                break

    if not first_slot:
        print("No valid slot matching selection criteria.")
        browser.close()
        return

    first_total_mins, first_hour, first_minute, _, first_locator = first_slot
    print(f"Final Primary Slot Chosen: {first_hour:02d}:{first_minute:02d}")

    # 8. Add Slot 1 to Basket
    print(f"Clicking Slot 1 ({first_hour:02d}:{first_minute:02d})...")
    first_locator.click()
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    if second_slot:
        _, sec_hour, sec_min, _, _ = second_slot
        print(f"Slot 2 selected ({sec_hour:02d}:{sec_min:02d}). Clicking 'Add and Book Another' for Slot 1...")
        add_another_btn = page.locator('[data-test-id="bookings-sportshall-activitydetails-addandbookanother"]')
        add_another_btn.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        print(f"Clicking Slot 2 link for {sec_hour:02d}:{sec_min:02d}...")
        sec_slot_text = f"{sec_hour:02d}:{sec_min:02d}"
        sec_locator = page.get_by_role("link", name=re.compile(sec_slot_text)).first
        sec_locator.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        print("Clicking 'Add and Continue' for Slot 2...")
        add_continue_btn = page.locator('[data-test-id="bookings-sportshall-activitydetails-addandcontinue"]')
        add_continue_btn.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
    else:
        print("No valid Slot 2 found. Clicking 'Add and Continue' directly for Slot 1...")
        add_continue_btn = page.locator('[data-test-id="bookings-sportshall-activitydetails-addandcontinue"]')
        add_continue_btn.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)

    # 9. Single Combined Checkout for Basket
    checkout_basket(page)

    print("Booking process finished successfully!")
    time.sleep(3)

    context.close()
    browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)