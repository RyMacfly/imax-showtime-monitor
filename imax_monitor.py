
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

CHECK_INTERVAL_MINUTES = 1

STATE_FILE = "imax_state.json"

BOISE_TZ = ZoneInfo("America/Boise")

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
# WINDOWS FOCUS CONTROL
# ============================================================

def get_foreground_window():
    """
    Get the Windows window that currently has focus.
    """

    return ctypes.windll.user32.GetForegroundWindow()


def restore_focus(hwnd):
    """
    Restore focus to the window that was active before
    Chromium was launched.
    """

    if hwnd:
        try:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


# ============================================================
# STATE
# ============================================================

def load_state():
    """
    Load previously detected showtime state.

    State is stored separately for every movie:

    {
        "The Odyssey": {
            "2026-08-07": {
                "available": false,
                "day": "Friday"
            }
        },
        "Spider-Man: Brand New Day": {
            ...
        }
    }
    """

    if not os.path.exists(STATE_FILE):
        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except (
        json.JSONDecodeError,
        OSError
    ):

        log(
            "⚠️ Could not read state file. "
            "Starting with empty state."
        )

        return {}


def save_state(state):
    """Save the current showtime state."""

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )


# ============================================================
# DISCORD
# ============================================================

def send_discord_notification(new_showtimes):
    """
    Send a Discord webhook notification for newly
    released showtimes.

    This runs in a background thread so it doesn't
    block the asyncio event loop.
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
    ]

    for showtime in new_showtimes:

        lines.append(
            f"🎬 **{showtime['movie']}**"
        )

        lines.append(
            f"📅 {showtime['day']}, "
            f"{showtime['date']}"
        )

        lines.append("")

    lines.append(
        f"🔗 {URL}"
    )

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


async def notify_discord(new_showtimes):
    """Send Discord notification without blocking."""

    await asyncio.to_thread(
        send_discord_notification,
        new_showtimes
    )


# ============================================================
# MOVIE SELECTION
# ============================================================

async def get_movies(page):
    """
    Find all movies currently displayed in the IMAX
    movie carousel.

    Returns a list such as:

    [
        "The Odyssey",
        "Spider-Man: Brand New Day",
        "Ghost: 2 Big to Rig",
        "Katy Perry: The Lifetimes Tour - Live From Paris"
    ]
    """

    movies = []

    cards = page.locator(
        '[data-testid="movie-card"]'
    )

    count = await cards.count()

    for i in range(count):

        card = cards.nth(i)

        image = card.locator(
            "img[alt]"
        ).first

        if await image.count() == 0:
            continue

        movie = await image.get_attribute(
            "alt"
        )

        if not movie:
            continue

        movie = movie.strip()

        if movie and movie not in movies:

            movies.append(movie)

    return movies


async def choose_movies(page):
    """
    Display the available movies and allow the user
    to select one movie or all movies.

    Returns a list of movie titles.
    """

    log("Finding available IMAX movies...")

    # Give the carousel time to render.
    await page.wait_for_timeout(2_000)

    movies = await get_movies(page)

    if not movies:

        raise RuntimeError(
            "No movies were found in the IMAX carousel."
        )

    print()
    print("=" * 60)
    print("AVAILABLE IMAX MOVIES")
    print("=" * 60)

    for i, movie in enumerate(
        movies,
        start=1
    ):

        print(
            f"{i}. {movie}"
        )

    print()
    print("A. Check all movies")
    print()

    while True:

        choice = input(
            "Select a movie number or A for all: "
        ).strip().lower()

        if choice == "a":

            log(
                f"Selected all {len(movies)} movies."
            )

            return movies

        try:

            index = int(choice) - 1

            if 0 <= index < len(movies):

                selected = movies[index]

                log(
                    f"Selected movie: {selected}"
                )

                return [selected]

        except ValueError:
            pass

        print(
            "⚠️ Invalid selection. "
            "Please enter a movie number or A."
        )


async def select_movie(page, movie):
    """
    Select a specific movie from the movie carousel.
    """

    image = page.locator(
        f'img[alt="{movie}"]'
    ).first

    await image.wait_for(
        state="visible",
        timeout=15_000
    )

    card = image.locator("..")
    slide = card.locator("..")

    await slide.scroll_into_view_if_needed()

    await slide.evaluate(
        "(element) => element.click()"
    )

    await page.wait_for_timeout(2_000)

    calendar = page.locator(
        '[role="grid"]'
    ).first

    await calendar.wait_for(
        state="visible",
        timeout=30_000
    )


# ============================================================
# CALENDAR
# ============================================================

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
        ...
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

        # IMAX timestamp appears to be one day behind
        # the displayed Boise date.
        date = utc_date + timedelta(
            days=1
        )

        class_name = (
            await button.get_attribute(
                "class"
            )
        )

        if class_name is None:
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
    movie,
    previous,
    current
):
    """
    Compare a movie's previous state to its current state.

    A notification is generated when a date changes:

        unavailable -> available
    """

    new_showtimes = []

    for date, info in current.items():

        currently_available = (
            info["available"]
        )

        previously_available = (
            previous
            .get(movie, {})
            .get(date, {})
            .get("available", False)
        )

        if (
            currently_available
            and not previously_available
        ):

            new_showtimes.append({
                "movie": movie,
                "date": date,
                "day": info["day"],
            })

    return new_showtimes


# ============================================================
# STATUS DISPLAY
# ============================================================

def print_status(
    movie,
    weekend
):
    """Print the current calendar status."""

    print()

    print(
        f"--- {movie} ---"
    )

    if not weekend:

        log(
            "⚠️ No dates found."
        )

        return



def print_new_showtimes(
    new_showtimes
):
    """Print newly released showtimes."""

    for showtime in new_showtimes:

        log(
            f"🚨 NEW SHOWTIME: "
            f"{showtime['movie']} | "
            f"{showtime['day']}, "
            f"{showtime['date']}"
        )


# ============================================================
# BROWSER
# ============================================================

async def open_browser():
    """
    Launch Chromium and navigate to the IMAX page.

    Chromium stays non-headless because the IMAX site
    requires the real browser environment.

    The window is positioned off-screen and focus is
    restored to the user's previous window.
    """

    previous_window = (
        get_foreground_window()
    )

    p = await async_playwright().start()

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
    await page.wait_for_timeout(500)

    # Restore the user's focus.
    restore_focus(
        previous_window
    )

    return p, browser, context, page


async def check_site():
    """
    Open the IMAX site and allow the user to select
    which movie(s) to monitor.

    Returns:

        page
        browser
        playwright instance
        selected movies
    """

    p, browser, context, page = (
        await open_browser()
    )

    try:

        log("Opening IMAX...")

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

        # Wait for the movie carousel.
        movie_cards = page.locator(
            '[data-testid="movie-card"]'
        )

        try:

            await movie_cards.first.wait_for(
                state="visible",
                timeout=30_000
            )

        except Exception:

            log(
                "❌ Movie carousel not found. "
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

            return None, None, None, None

        # Ask the user what movie(s) to monitor.
        selected_movies = await choose_movies(
            page
        )

        return (
            p,
            browser,
            page,
            selected_movies
        )

    except Exception:

        await browser.close()
        await p.stop()

        raise


# ============================================================
# MONITOR
# ============================================================

async def monitor():

    state = load_state()

    try:
        (
            p,
            browser,
            page,
            selected_movies
        ) = await check_site()

    except Exception as e:
        log(f"❌ Could not start monitor: {e}")
        return

    if not selected_movies:

        log("❌ No movies selected.")

        await browser.close()
        await p.stop()

        return

    log(
        f"🎬 Monitoring {len(selected_movies)} movie(s): "
        + ", ".join(selected_movies)
    )

    try:

        while True:

            cycle_start = datetime.now(
                BOISE_TZ
            )

            log(
                f"🔍 Checking {len(selected_movies)} "
                f"movie(s)..."
            )

            checked = 0
            errors = 0
            all_new_showtimes = []

            for movie in selected_movies:

                try:

                    await select_movie(
                        page,
                        movie
                    )

                    weekend = (
                        await get_weekend_dates(
                            page
                        )
                    )

                    new_showtimes = (
                        detect_new_showtimes(
                            movie,
                            state,
                            weekend
                        )
                    )

                    if new_showtimes:

                        all_new_showtimes.extend(
                            new_showtimes
                        )

                    state[movie] = weekend

                    save_state(state)

                    checked += 1

                except Exception as e:

                    errors += 1

                    log(
                        f"❌ {movie}: {e}"
                    )

            # ------------------------------------------------
            # Notifications
            # ------------------------------------------------

            if all_new_showtimes:

                print_new_showtimes(
                    all_new_showtimes
                )

                await notify_discord(
                    all_new_showtimes
                )

            # ------------------------------------------------
            # Cycle summary
            # ------------------------------------------------

            elapsed = (
                datetime.now(BOISE_TZ)
                - cycle_start
            ).total_seconds()

            if errors == 0:

                if all_new_showtimes:

                    log(
                        f"🚨 Checked {checked} movies "
                        f"in {elapsed:.1f}s — "
                        f"{len(all_new_showtimes)} "
                        f"new showtime(s) found!"
                    )

                else:

                    log(
                        f"✅ Checked {checked} movies "
                        f"in {elapsed:.1f}s — "
                        f"no new showtimes."
                    )

            else:

                log(
                    f"⚠️ Checked {checked} movies "
                    f"in {elapsed:.1f}s — "
                    f"{errors} error(s)."
                )

            log(
                f"⏳ Next check in "
                f"{CHECK_INTERVAL_MINUTES} minutes."
            )

            await asyncio.sleep(
                CHECK_INTERVAL_MINUTES * 60
            )

    finally:

        log("Closing browser...")

        await browser.close()
        await p.stop()


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            monitor()
        )

    except KeyboardInterrupt:

        print()
        log(
            "Monitor stopped."
        )

