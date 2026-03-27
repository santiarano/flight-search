#!/usr/bin/env python3
"""Step 19-20 v3: Try force-clicking and JS-based checkbox toggling."""
import sys, os, time
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

SHOTS = os.path.expanduser("~/clawd/obsidian-vault/flights/screenshots")

def click_el(page, locator):
    el = locator.first
    box = el.bounding_box()
    if box and box["width"] > 0:
        page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
        return True
    return False

pw = sync_playwright().start()
browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled","--no-sandbox"])
ctx = browser.new_context(viewport={"width":1920,"height":1080}, locale="en-US", timezone_id="America/Los_Angeles")
ctx.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
page = ctx.new_page()

page.goto("https://www.google.com/travel/flights?q=Flights+from+SFO+to+BCN+on+2026-05-08+returning+2026-07-09+business+class", timeout=30000)
time.sleep(10)

# Open Airlines filter
btn = page.locator('button:has-text("Airlines"), button:has-text("All airlines")')
click_el(page, btn)
time.sleep(2)

# STEP 19: Toggle off "Select all"
print("STEP 19: Toggling off Select all...")
toggle = page.locator('button[role="switch"][aria-label="Select all airlines"]')
if toggle.count() > 0:
    # Use force click
    toggle.first.click(force=True)
    time.sleep(2)
    new_state = toggle.get_attribute("aria-checked")
    print(f"  After click: checked={new_state}")

page.screenshot(path=f"{SHOTS}/step19v3-toggled.png")

# STEP 20: Select airlines using force click on the checkbox div
print("\nSTEP 20: Selecting airlines...")

for airline_name in ["United", "Tap Air Portugal", "LEVEL"]:
    li = page.locator(f'li[ssk*="{airline_name}"]')
    if li.count() > 0:
        # Try multiple click strategies
        # Strategy 1: force click on the li itself
        try:
            li.first.click(force=True)
            time.sleep(1)
            print(f"  {airline_name}: force-clicked li")
        except Exception as e:
            print(f"  {airline_name}: force click failed ({str(e)[:40]})")
    else:
        print(f"  {airline_name}: not found")

page.screenshot(path=f"{SHOTS}/step20v3-selected.png")

# Check what's selected now
print("\n  Checking which airlines are now checked...")
all_li = page.locator('li[ssk]').all()
for item in all_li[:25]:
    ssk = item.get_attribute("ssk") or ""
    name = ssk.split(":")[-1] if ":" in ssk else ssk
    # Check if this item's checkbox is checked
    try:
        cb = item.locator('[class*="MPu53c"]').first
        classes = cb.get_attribute("class") or ""
        is_checked = "gk6SMd" in classes  # Material Design checked class
        if is_checked:
            print(f"    CHECKED: {name}")
    except:
        pass

# Close with X button
print("\nClosing...")
x_btn = page.locator('[aria-label="Close dialog"], button.VfPpkd-Bz112c-LgbsSe')
if x_btn.count() > 0:
    click_el(page, x_btn)
else:
    # Click the X visible in the dropdown header
    page.keyboard.press("Escape")
time.sleep(3)

page.screenshot(path=f"{SHOTS}/step20v3-closed.png")
print("DONE")
page.pause()
