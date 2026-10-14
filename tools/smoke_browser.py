"""Exercise form filling in local mocked pages; never contact university services."""

from playwright.sync_api import sync_playwright

from zju_ac.auth import fill_login_form

HTML = """<form onsubmit="event.preventDefault(); document.body.dataset.submitted='yes'">
<input name="username"><input type="password"><button>Login</button></form>"""


def main():
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel="msedge", headless=True)
        try:
            context = browser.new_context()
            context.route("**/*", lambda route: route.fulfill(body=HTML, content_type="text/html"))
            page = context.new_page()
            page.goto("https://identity.zju.edu.cn/mock-login")
            assert fill_login_form(page, "offline-test", "dummy-password")
            assert page.locator('[name="username"]').input_value() == "offline-test"
            assert page.locator("body").get_attribute("data-submitted") == "yes"
            page.goto("https://example.invalid/mock-login")
            assert not fill_login_form(page, "offline-test", "dummy-password")
            assert page.locator('[name="username"]').input_value() == ""
            print("Browser smoke check passed (mocked pages only).")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
