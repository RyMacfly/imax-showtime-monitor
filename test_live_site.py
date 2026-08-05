import pytest
from playwright.async_api import async_playwright


URL = "https://www.imax.com/theatre/regal-edwards-boise-imax"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_imax_live_site_calendar():

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            viewport={
                "width": 1920,
                "height": 1080,
            },
            locale="en-US",
            timezone_id="America/Boise",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        try:

            response = await page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            print(
                f"\nHTTP status: "
                f"{response.status if response else 'unknown'}"
            )

            # Don't immediately fail on HTTP 403.
            #
            # Some sites return a 403 initially but the browser
            # can still receive/render the page through JS.
            if response and response.status == 403:
                print(
                    "Initial HTTP 403 detected. "
                    "Checking whether the calendar rendered..."
                )

            # Give the site time to execute JavaScript
            await page.wait_for_timeout(5_000)

            # Check whether the calendar actually exists
            calendar = page.locator(
                '[role="grid"]'
            ).first

            try:
                await calendar.wait_for(
                    state="visible",
                    timeout=30_000,
                )
            except Exception:

                # Save the page so we can see what IMAX actually
                # returned when the test failed.
                await page.screenshot(
                    path="imax_failure.png",
                    full_page=True,
                )

                html = await page.content()

                with open(
                    "imax_failure.html",
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write(html)

                pytest.fail(
                    "IMAX calendar did not appear. "
                    "Saved imax_failure.png and "
                    "imax_failure.html for inspection."
                )

            print("Calendar found!")

            date_buttons = calendar.locator(
                'button[role="gridcell"][data-timestamp]'
            )

            count = await date_buttons.count()

            print(
                f"Found {count} calendar date buttons."
            )

            assert count > 0

            dates = []

            for i in range(count):

                button = date_buttons.nth(i)

                day = (
                    await button.inner_text()
                ).strip()

                timestamp = (
                    await button.get_attribute(
                        "data-timestamp"
                    )
                )

                disabled = (
                    await button.is_disabled()
                )

                dates.append({
                    "day": day,
                    "timestamp": timestamp,
                    "disabled": disabled,
                })

            print("\nCalendar:")

            for date in dates:

                status = (
                    "AVAILABLE"
                    if not date["disabled"]
                    else "disabled"
                )

                print(
                    f"  {date['day']:>2} "
                    f"{status}"
                )

            assert len(dates) > 0

        finally:

            await browser.close()