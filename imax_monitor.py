
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright


URL = "https://www.imax.com/theatre/regal-edwards-boise-imax"

# Check every 60 seconds
CHECK_INTERVAL = 60

STATE_FILE = "imax_state.json"

BOISE_TZ = ZoneInfo("America/Boise")


def load_state():
    """Load the previously detected showtime state."""

    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)

    except (json.JSONDecodeError, OSError):
        print("Warning: Could not read state file.")
        return {}


def save_state(state):
    """Save the current showtime state."""

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


async def get_weekend_dates(page):
    """
    Find Friday, Saturday, and Sunday currently shown
    in the IMAX calendar.

    Returns:

    {
        "2026-08-07": {
            "available": False,
            "day": "Friday"
        },
        "2026-08-08": {
            "available": False,
            "day": "Saturday"
        },
        "2026-08-09": {
            "available": False,
            "day": "Sunday"
        }
    }
    """

    # This selector was verified by the live-site test.
    calendar = page.locator(
        '[role="grid"]'
    ).first

    await calendar.wait_for(
        state="visible",
        timeout=10_000
    )

    # Use semantic attributes rather than Material UI's
    # generated css-xxxxx classes.
    buttons = calendar.locator(
        'button[role="gridcell"][data-timestamp]'
    )

    results = {}

    count = await buttons.count()

    for i in range(count):

        button = buttons.nth(i)

        text = (
            await button.inner_text()
        ).strip()

        # Ignore anything that isn't an actual date.
        if not text.isdigit():
            continue

        timestamp = await button.get_attribute(
            "data-timestamp"
        )

        if not timestamp:
            continue

        # Convert JavaScript timestamp from milliseconds
        # to seconds.
        timestamp_ms = int(timestamp)

        utc_date = datetime.fromtimestamp(
            timestamp_ms / 1000,
            BOISE_TZ
        ).date()

        date = utc_date + timedelta(days=1)

        # Python weekday:
        #
        # Monday    = 0
        # Tuesday   = 1
        # Wednesday = 2
        # Thursday  = 3
        # Friday    = 4
        # Saturday  = 5
        # Sunday    = 6
        #
        

        is_disabled = await button.is_disabled()
        aria_disabled = await button.get_attribute("aria-disabled")
        aria_selected = await button.get_attribute("aria-selected")
        class_name = await button.get_attribute("class")

        # print(
        #     f"\nDATE: {date}"
        # )
        # print(
        #     f"  text:          {text!r}"
        # )
        # print(
        #     f"  is_disabled:   {is_disabled}"
        # )
        # print(
        #     f"  aria-disabled: {aria_disabled}"
        # )
        # print(
        #     f"  aria-selected: {aria_selected}"
        # )
        # print(
        #     f"  class:         {class_name}"
        # )

        results[str(date)] = {
            "available": "Mui-disabled" not in class_name,
            "day": date.strftime("%A"),
        }
        

    return results


def detect_new_showtimes(previous, current):
    """
    Compare the previous state to the current state.

    Returns a list of dates that changed from:

        unavailable -> available
    """

    new_showtimes = []

    for date, info in current.items():

        currently_available = info["available"]

        previously_available = previous.get(
            date,
            False
        )

        if (
            currently_available
            and not previously_available
        ):
            new_showtimes.append({
                "date": date,
                "day": info["day"],
            })

    return new_showtimes


def print_status(weekend):
    """Print the current Friday/Saturday/Sunday status."""

    print()

    if not weekend:
        print("WARNING: No Friday/Saturday/Sunday dates found.")
        return

    for date, info in weekend.items():

        if info["available"]:
            symbol = "✅"
            status = "SHOWTIMES AVAILABLE"
        else:
            symbol = "❌"
            status = "No showtimes"

        print(
            f"{symbol} "
            f"{info['day']:<9} "
            f"{date}  "
            f"{status}"
        )


def print_new_showtimes(new_showtimes):
    """Print a prominent alert for newly released dates."""

    for showtime in new_showtimes:

        print()
        print("!" * 60)
        print("🚨 NEW SHOWTIMES RELEASED 🚨")
        print("!" * 60)
        print()
        print(
            f"{showtime['day']}, "
            f"{showtime['date']}"
        )
        print()
        print(URL)
        print()



async def check_site():
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
            print("Opening IMAX...")

            response = await page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            print(
                f"HTTP status: "
                f"{response.status if response else 'unknown'}"
            )

            # Give IMAX's JavaScript / verification time to run.
            await page.wait_for_timeout(5_000)

            calendar = page.locator(
                '[role="grid"]'
            ).first

            try:
                await calendar.wait_for(
                    state="visible",
                    timeout=30_000,
                )

            except Exception:
                print("Calendar not found.")
                print("Saving diagnostic files...")

                await page.screenshot(
                    path="imax_monitor_failure.png",
                    full_page=True,
                )

                html = await page.content()

                with open(
                    "imax_monitor_failure.html",
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write(html)

                return None

            print("Calendar found!")

            # Now use your actual weekend extraction logic.
            weekend = await get_weekend_dates(page)

            return weekend

        finally:
            await browser.close()
            
async def monitor():

    previous = load_state()

    while True:

        print("=" * 60)
        print("CHECKING IMAX")
        print("=" * 60)

        try:

            weekend = await check_site()

            if weekend is None:
                print("IMAX check failed.")
                print("Previous state will be preserved.")

            else:

                print_status(weekend)

                new_showtimes = detect_new_showtimes(
                    previous,
                    weekend
                )

                if new_showtimes:
                    print_new_showtimes(
                        new_showtimes
                    )

                save_state(weekend)

                previous = weekend

                print()
                print("IMAX check successful.")

        except Exception as e:

            print("=" * 60)
            print("ERROR CHECKING IMAX")
            print("=" * 60)
            print(e)

        print(
            f"\nRetrying in "
            f"{CHECK_INTERVAL} seconds..."
        )

        await asyncio.sleep(
            CHECK_INTERVAL
        )




if __name__ == "__main__":
    asyncio.run(monitor())

