from pathlib import Path
import json
from html.parser import HTMLParser
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "index.html"

class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.anchors = []
        self.scripts = 0
    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            self.ids.append(data["id"])
        if data.get("href", "").startswith("#"):
            self.anchors.append(data["href"][1:])

text = HTML.read_text(encoding="utf-8")
parser = Inspector()
parser.feed(text)
assert len(text.splitlines()) >= 2000
assert len(parser.ids) == len(set(parser.ids))
assert all(anchor in parser.ids for anchor in parser.anchors)
assert "\ufffd" not in text
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        headless=True,
        args=["--disable-gpu"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(HTML.as_uri())
    page.screenshot(path=str(ROOT / "desktop.png"))
    assert page.locator("#probability-output").inner_text()
    page.locator("#probability").evaluate("el => { el.value = '0.80'; el.dispatchEvent(new Event('input')); }")
    assert "بله" in page.locator("#probability-output").inner_text()
    page.locator("#probability").evaluate("el => { el.value = '0.25'; el.dispatchEvent(new Event('input')); }")
    assert "بازبینی" in page.locator("#probability-output").inner_text()
    for selector, value in [("#weight-0", "0"), ("#weight-1", "100"), ("#weight-2", "0")]:
        page.locator(selector).evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('input')); }", value)
    assert "۱" in page.locator("#score-output").inner_text()
    page.locator("#search").fill("کالیبراسیون")
    assert page.locator(".chapter:visible").count() < 36
    assert page.locator(".chapter:visible").count() > 0
    page.locator("#clear-search").click()
    assert page.locator(".chapter:visible").count() == 36
    page.locator("#theme").click()
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.screenshot(path=str(ROOT / "light.png"))
    page.locator("#theme").click()
    page.locator("#chapter-13").scroll_into_view_if_needed()
    page.screenshot(path=str(ROOT / "structure.png"))
    mobile = browser.new_page(viewport={"width": 390, "height": 844})
    mobile.goto(HTML.as_uri())
    mobile.screenshot(path=str(ROOT / "mobile.png"))
    overflow = mobile.evaluate(
        "document.documentElement.scrollWidth > window.innerWidth"
    )
    assert not overflow, "Unexpected horizontal overflow on mobile"
    assert page.locator("pre").first.evaluate(
        "(el) => getComputedStyle(el).direction"
    ) == "ltr"
    assert page.locator("body").evaluate(
        "(el) => getComputedStyle(el).direction"
    ) == "rtl"
    assert not errors, errors
    browser.close()
print(json.dumps({
    "html_lines": len(text.splitlines()),
    "unique_ids": len(parser.ids),
    "anchors_ok": True,
    "interactive_checks": "passed",
    "mobile_overflow": False,
    "script_errors": errors,
}, ensure_ascii=False, indent=2))
