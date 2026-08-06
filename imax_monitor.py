
import asyncio
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()  # Load environment variables from .env file

URL = "https://www.imax.com/theatre/regal-edwards-boise-imax"

# Check every 10 minutes for new showtimes. This is a balance between
# being responsive to new showtimes and not overloading the IMAX server.

CHECK_INTERVAL_MINUTES = 10

STATE_FILE = "imax_state.json"
 
BOISE_TZ = ZoneInfo("America/Boise")

# Discord webhook URL
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


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


def send_discord_notification(new_showtimes):
    """
    Send a Discord webhook notification for newly released showtimes.

    This runs in a background thread so it doesn't block
    the asyncio event loop.
    """

    if not DISCORD_WEBHOOK_URL:
        print("Warning: DISCORD_WEBHOOK_URL is not set.")
        return

    if not new_showtimes:
        return

    # Build the Discord message.
    lines = [
        "🚨 **NEW IMAX SHOWTIMES RELEASED!** 🚨",
        "",
    ]

    for showtime in new_showtimes:
        lines.append(
            f"🎬 **{showtime['day']}, {showtime['date']}**"
        )

    lines.extend([
        "",
        f"🔗 {URL}",
    ])

    message = "\n".join(lines)

    payload = {
        "content": message,
        "username": "IMAX Showtime Monitor",
    }

    data = json.dumps(payload).encode("utf-8")

    request = Request(
        DISCORD_WEBHOOK_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "IMAX Showtime Monitor",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            if 200 <= response.status < 300:
                log("✅ Discord notification sent!")
            else:
                print(
                    f"⚠️ Discord webhook returned "
                    f"HTTP {response.status}"
                )

    except HTTPError as e:
        print(
            f"❌ Discord webhook HTTP error: "
            f"{e.code} {e.reason}"
        )

    except URLError as e:
        print(
            f"❌ Discord webhook connection error: "
            f"{e.reason}"
        )

    except Exception as e:
        print(
            f"❌ Discord webhook error: {e}"
        )


async def notify_discord(new_showtimes):
    """
    Send Discord notification without blocking
    the asyncio event loop.
    """

    await asyncio.to_thread(
        send_discord_notification,
        new_showtimes
    )


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

    calendar = page.locator(
        '[role="grid"]'
    ).first

    await calendar.wait_for(
        state="visible",
        timeout=30_000
    )

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

        if not text.isdigit():
            continue

        timestamp = await button.get_attribute(
            "data-timestamp"
        )

        if not timestamp:
            continue

        timestamp_ms = int(timestamp)

        utc_date = datetime.fromtimestamp(
            timestamp_ms / 1000,
            BOISE_TZ
        ).date()

        date = utc_date + timedelta(days=1)

        is_disabled = await button.is_disabled()
        aria_disabled = await button.get_attribute(
            "aria-disabled"
        )
        aria_selected = await button.get_attribute(
            "aria-selected"
        )
        class_name = await button.get_attribute(
            "class"
        )

        results[str(date)] = {
            "available": (
                "Mui-disabled" not in class_name
            ),
            "day": date.strftime("%A"),
        }

    return results


def detect_new_showtimes(previous, current):
    """
    Compare the previous state to the current state.

    Returns dates that changed from:

        unavailable -> available
    """

    new_showtimes = []

    for date, info in current.items():

        currently_available = info["available"]

        previously_available = previous.get(
            date,
            {}
        ).get(
            "available",
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
        print(
            "WARNING: No Friday/Saturday/Sunday "
            "dates found."
        )
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
    """Print newly released showtimes."""

    for showtime in new_showtimes:
        log(
            f"🚨 NEW SHOWTIME: "
            f"{showtime['day']}, {showtime['date']}"
        )


async def check_site():
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-position=-2000,-2000",
                "--window-size=1920,1080",
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
                timeout=30_000,
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
                log("❌ Calendar not found. Saving diagnostics.")

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


            weekend = await get_weekend_dates(page)

            return weekend

        finally:
            await browser.close()

def log(message):
    """Print a timestamped log message."""
    now = datetime.now(BOISE_TZ)
    print(
        f"[{now.strftime('%Y-%m-%d %I:%M:%S %p')}] "
        f"{message}"
    )

async def monitor():


    while True:

   
        log("Checking IMAX for new showtimes...")
       

        # Reload the previous state from disk every check
        previous = load_state()
        
        try:

            weekend = await check_site()

            if weekend is None:
                 log("❌ IMAX check failed. Previous state preserved.")

            else:

                # print_status(weekend)

                new_showtimes = detect_new_showtimes(
                    previous,
                    weekend
                )

                if new_showtimes:


                    # Send Discord notification
                    await notify_discord(
                        new_showtimes
                    )

                save_state(weekend)

                previous = weekend

                log("✅ IMAX check successful.")

        except Exception as e:

            
            log(f"❌ Error occurred: {e}")


        await asyncio.sleep(
            CHECK_INTERVAL_MINUTES * 60
        )


if __name__ == "__main__":
    asyncio.run(monitor())

