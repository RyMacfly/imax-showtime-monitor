
import asyncio
import ctypes
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv
from playwright.async_api import async_playwright


load_dotenv()


# ============================================================
# CONFIGURATION
# ============================================================

URL = "https://www.imax.com/theatre/regal-edwards-boise-imax"

# Movie to monitor.
#
# This must match the movie's alt text on the IMAX website.
#
# Examples:
#   "The Odyssey"
#   "Spider-Man: Brand New Day"
#   "Ghost: 2 Big to Rig"
#
MOVIE_TITLE = "Spider-Man: Brand New Day"

# Check every 10 minutes for new showtimes.
CHECK_INTERVAL_MINUTES = 1

STATE_FILE = f"{MOVIE_TITLE.replace(' ', '_').replace(':', '')}_imax_state.json"

BOISE_TZ = ZoneInfo("America/Boise")

# Discord webhook URL
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL"
)


# ============================================================
# LOGGING
# ============================================================

def log(message):
    """Print a timestamped log message."""

    now = datetime.now(BOISE_TZ)

    print(
        f"[{now.strftime('%Y-%m-%d %I:%M:%S %p')}] "
        f"{message}"
    )


# ============================================================
# WINDOWS FOCUS MANAGEMENT
# ============================================================

def get_foreground_window():
    """
    Get the Windows window that currently has focus.

    This allows Chromium to run without stealing focus
    from whatever the user is currently doing.
    """

    return ctypes.windll.user32.GetForegroundWindow()


def restore_focus(hwnd):
    """
    Restore focus to the window that was active before
    Chromium was launched.
    """

    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(
            hwnd
        )


# ============================================================
# STATE
# ============================================================

def load_state():
    """Load the previously detected showtime state."""

    if not os.path.exists(STATE_FILE):
        return {}

    try:

        with open(
            STATE_FILE,
            "r"
        ) as f:

            return json.load(f)

    except (
        json.JSONDecodeError,
        OSError
    ):

        log(
            "⚠️ Could not read state file."
        )

        return {}


def save_state(state):
    """Save the current showtime state."""

    with open(
        STATE_FILE,
        "w"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )


# ============================================================
# DISCORD
# ============================================================

def send_discord_notification(
    new_showtimes
):
    """
    Send a Discord webhook notification for newly
    released showtimes.

    Runs in a background thread so it doesn't block
    the asyncio event loop.
    """

    if not DISCORD_WEBHOOK_URL:

        log(
            "⚠️ DISCORD_WEBHOOK_URL is not set."
        )

        return

    if not new_showtimes:
        return

    lines = [
        "🚨 **NEW IMAX SHOWTIMES RELEASED!** 🚨",
        "",
        f"🎬 **{MOVIE_TITLE}**",
        "",
    ]

    for showtime in new_showtimes:

        lines.append(
            f"📅 **{showtime['day']}, "
            f"{showtime['date']}**"
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

    data = json.dumps(
        payload
    ).encode("utf-8")

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

        with urlopen(
            request,
            timeout=10
        ) as response:

            if 200 <= response.status < 300:

                log(
                    "✅ Discord notification sent!"
                )

            else:

                log(
                    f"⚠️ Discord webhook returned "
                    f"HTTP {response.status}"
                )

    except HTTPError as e:

        log(
            f"❌ Discord webhook HTTP error: "
            f"{e.code} {e.reason}"
        )

    except URLError as e:

        log(
            f"❌ Discord webhook connection error: "
            f"{e.reason}"
        )

    except Exception as e:

        log(
            f"❌ Discord webhook error: {e}"
        )


async def notify_discord(
    new_showtimes
):
    """
    Send Discord notification without blocking
    the asyncio event loop.
    """

    await asyncio.to_thread(
        send_discord_notification,
        new_showtimes
    )


# ============================================================
# MOVIE SELECTION
# ============================================================

async def select_movie(page):
    """
    Find and select the configured movie.

    The IMAX page displays movies in a carousel and normally
    selects the first movie automatically. This function
    explicitly selects the requested movie before checking
    the calendar.
    """

    log(
        f"🎬 Selecting movie: {MOVIE_TITLE}"
    )

    # Find the movie image by its alt text.
    movie_image = page.locator(
        f'img[alt="{MOVIE_TITLE}"]'
    ).first

    try:

        await movie_image.wait_for(
            state="visible",
            timeout=30_000
        )

    except Exception:

        log(
            f"❌ Movie not found: {MOVIE_TITLE}"
        )

        # Show the movies currently available.
        movies = page.locator(
            '[data-testid="movie-card"] img[alt]'
        )

        count = await movies.count()

        if count:

            log("Movies currently available:")

            for i in range(count):

                alt = await movies.nth(i).get_attribute(
                    "alt"
                )

                log(
                    f"   • {alt}"
                )

        return False

    # The structure is:
    #
    # swiper-slide
    #   └── slideContentContainer
    #       └── imageContainer
    #           └── img
    #
    # Find the slide containing our movie.
    movie_slide = movie_image.locator(
        "xpath=ancestor::div[contains(@class, "
        "'swiper-slide')]"
    ).first

    await movie_slide.wait_for(
        state="visible",
        timeout=10_000
    )

    # Get the slide's current class so we can determine
    # whether it is already selected.
    slide_content = movie_slide.locator(
        'div[data-testid="movie-card"]'
    ).locator(
        "xpath=.."
    ).first

    # Click the slide content rather than the image.
    #
    # force=True is intentional here. The IMAX carousel
    # has overlay elements that Playwright's normal hit
    # testing considers to be intercepting the click.
    await slide_content.click(
        force=True
    )

    log(
        f"🖱️ Clicked '{MOVIE_TITLE}'"
    )

    # Give React/Next.js time to update the selected movie
    # and reload the corresponding calendar.
    await page.wait_for_timeout(
        2_000
    )

    # Verify that the requested movie is now selected.
    selected = movie_slide.locator(
        "div.movies-carousel-module-scss-module__"
        "EtTL9G__slideContentContainer."
        "movies-carousel-module-scss-module__"
        "EtTL9G__selected"
    )

    try:

        await selected.wait_for(
            state="attached",
            timeout=5_000
        )

        log(
            f"✅ Selected movie: {MOVIE_TITLE}"
        )

    except Exception:

        # The generated CSS class can change, so don't
        # consider this a failure if the calendar itself
        # updates correctly.
        log(
            f"✅ Clicked movie: {MOVIE_TITLE}"
        )

    return True



# ============================================================
# CALENDAR
# ============================================================

async def get_weekend_dates(page):
    """
    Find Friday, Saturday, and Sunday currently shown
    in the IMAX calendar.

    The movie must already have been selected before
    this function is called.

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

        # Ignore anything that isn't an actual date.
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

        # The IMAX timestamp appears to represent the
        # previous local date, so preserve the existing
        # +1 day behavior.
        date = utc_date + timedelta(
            days=1
        )

        class_name = await button.get_attribute(
            "class"
        )

        if not class_name:
            class_name = ""

        results[str(date)] = {
            "available": (
                "Mui-disabled" not in class_name
            ),
            "day": date.strftime("%A"),
        }

    return results


# ============================================================
# SHOWTIME DETECTION
# ============================================================

def detect_new_showtimes(
    previous,
    current
):
    """
    Compare the previous state to the current state.

    Returns dates that changed from:

        unavailable -> available
    """

    new_showtimes = []

    for date, info in current.items():

        currently_available = (
            info["available"]
        )

        previously_available = (
            previous
            .get(date, {})
            .get("available", False)
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

        log(
            "⚠️ No Friday/Saturday/Sunday "
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


def print_new_showtimes(
    new_showtimes
):
    """Print newly released showtimes."""

    for showtime in new_showtimes:

        log(
            f"🚨 NEW SHOWTIME: "
            f"{showtime['day']}, "
            f"{showtime['date']}"
        )


# ============================================================
# WEBSITE CHECK
# ============================================================

async def check_site():
    """
    Open the IMAX website using a real Chromium browser.

    Chromium remains non-headless because the IMAX site
    requires the real browser environment for verification.

    The window is positioned off-screen and focus is restored
    to whatever window the user was using beforehand.

    The requested movie is selected before the calendar
    is inspected.
    """

    # Remember whatever window the user is currently using.
    previous_window = (
        get_foreground_window()
    )

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

        # Give Windows time to create the Chromium window.
        await page.wait_for_timeout(
            500
        )

        # Return focus to whatever the user was doing.
        restore_focus(
            previous_window
        )

        try:

            log(
                "Opening IMAX..."
            )

            response = await page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            if response:

                log(
                    f"HTTP status: "
                    f"{response.status}"
                )

            # Give IMAX's JavaScript / verification
            # time to run.
            await page.wait_for_timeout(
                5_000
            )

            # ------------------------------------------------
            # SELECT MOVIE
            # ------------------------------------------------

            movie_selected = (
                await select_movie(page)
            )

            if not movie_selected:

                log(
                    "❌ Could not select movie."
                )

                return None

            # ------------------------------------------------
            # CHECK CALENDAR
            # ------------------------------------------------

            log(
                "Checking calendar..."
            )

            calendar = page.locator(
                '[role="grid"]'
            ).first

            try:

                await calendar.wait_for(
                    state="visible",
                    timeout=30_000,
                )

            except Exception:

                log(
                    "❌ Calendar not found. "
                    "Saving diagnostics."
                )

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

            weekend = (
                await get_weekend_dates(
                    page
                )
            )

            return weekend

        finally:

            await browser.close()


# ============================================================
# MAIN MONITOR
# ============================================================

async def monitor():

    while True:

        log(
            f"Checking IMAX for "
            f"'{MOVIE_TITLE}'..."
        )

        # Reload the previous state from disk
        # every check.
        previous = load_state()

        try:

            weekend = await check_site()

            if weekend is None:

                log(
                    "❌ IMAX check failed. "
                    "Previous state preserved."
                )

            else:

                print_status(
                    weekend
                )

                new_showtimes = (
                    detect_new_showtimes(
                        previous,
                        weekend
                    )
                )

                if new_showtimes:

                    print_new_showtimes(
                        new_showtimes
                    )

                    await notify_discord(
                        new_showtimes
                    )

                else:

                    log(
                        "No new showtimes."
                    )

                # Only save a successful check.
                save_state(
                    weekend
                )

                log(
                    "✅ IMAX check successful."
                )

        except Exception as e:

            log(
                f"❌ Error occurred: {e}"
            )

        log(
            f"Next check in "
            f"{CHECK_INTERVAL_MINUTES} minutes."
        )

        await asyncio.sleep(
            CHECK_INTERVAL_MINUTES * 60
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        monitor()
    )

