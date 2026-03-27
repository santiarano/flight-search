#!/usr/bin/env python3
"""Debug: inspect the airline filter dropdown DOM to find the right selectors."""
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

# Inspect every clickable item in the dropdown
print("=== AIRLINE DROPDOWN DOM INSPECTION ===\n")

# Find the dropdown container
# Look for all checkbox-like elements
checkboxes = page.locator('[role="checkbox"], [role="menuitemcheckbox"], [role="switch"]').all()
print(f"Checkboxes: {len(checkboxes)}")
for i, cb in enumerate(checkboxes[:20]):
    try:
        text = cb.inner_text(timeout=1000).strip()[:50]
        role = cb.get_attribute("role") or ""
        aria = cb.get_attribute("aria-label") or ""
        checked = cb.get_attribute("aria-checked") or ""
        tag = cb.evaluate("el => el.tagName")
        cls = (cb.get_attribute("class") or "")[:40]
        print(f"  [{i}] <{tag}> role={role} checked={checked} text={text!r} aria={aria!r} class={cls}")
    except:
        print(f"  [{i}] (error reading)")

# Also look for list items in the dropdown
print(f"\n--- List items ---")
items = page.locator('[role="listbox"] li, [role="list"] li, [class*="airline"] li').all()
print(f"List items: {len(items)}")

# Try a different approach - look for all elements containing airline names
print(f"\n--- Elements containing 'United' ---")
united_els = page.locator(':text("United")').all()
for i, el in enumerate(united_els[:10]):
    try:
        tag = el.evaluate("el => el.tagName")
        text = el.inner_text(timeout=1000).strip()[:60]
        parent_tag = el.evaluate("el => el.parentElement ? el.parentElement.tagName : 'none'")
        parent_role = el.evaluate("el => el.parentElement ? (el.parentElement.getAttribute('role') || '') : ''")
        box = el.bounding_box()
        visible = box is not None and box["width"] > 0
        print(f"  [{i}] <{tag}> text={text!r} parent=<{parent_tag}> parent_role={parent_role!r} visible={visible}")
    except:
        print(f"  [{i}] (error)")

# Look for the actual clickable airline items
print(f"\n--- All visible text items in dropdown area ---")
# The dropdown is likely a div with specific class
dialogs = page.locator('[role="dialog"], [class*="filter"], [class*="dropdown"]').all()
print(f"Dialog/filter containers: {len(dialogs)}")

# Try getting the HTML of the dropdown
print(f"\n--- Dropdown HTML structure (first airline item) ---")
try:
    # Find element with "United" and get its parent structure
    united = page.locator(':text-is("United")').first
    html = united.evaluate("el => { let p = el; for(let i=0;i<5;i++){p=p.parentElement;if(!p)break;} return p ? p.outerHTML.substring(0,500) : 'no parent'; }")
    print(html)
except Exception as e:
    print(f"Error: {e}")

page.screenshot(path=f"{SHOTS}/debug-filter.png")
print("\nDone inspecting")
page.pause()
