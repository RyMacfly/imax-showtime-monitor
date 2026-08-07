
import asyncio
import ctypes
import json
import os
import platform
import subprocess
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

CHECK_INTERVAL_MINUTES = 15

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
    """Get the window that currently has focus."""

    system = platform.system()

    if system == "Windows":
        return ctypes.windll.user32.GetForegroundWindow()

    elif system == "Linux":
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
                check=True
            )
            return int(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    return None


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
        }
    }

    Movie state is intentionally kept even if a movie
    temporarily disappears from the IMAX page.
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

    Runs in a background thread so it doesn't block
    the asyncio event loop.
    """

    if not DISCORD_WEBHOOK_URL:

        log(
            "⚠️  DISCORD_WEBHOOK_URL is not set."
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
# MOVIES
# ============================================================

async def get_movies(page):
    """
    Find all movies currently displayed in the IMAX
    movie carousel.

    Returns a list of movie titles.
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
    Let the user choose between:

        1. Monitoring one movie
        A. Dynamically monitoring all movies

    Returns:

        {
            "mode": "all",
            "movies": [...]
        }

    or:

        {
            "mode": "single",
            "movies": [...]
        }
    """

    log(
        "Finding available IMAX movies..."
    )

    await page.wait_for_timeout(
        2_000
    )

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
    print(
        "A. Check all movies "
        "(automatically detect additions/removals)"
    )
    print()

    while True:

        choice = input(
            "Select a movie number or A for all: "
        ).strip().lower()

        if choice == "a":

            log(
                f"🎬 Dynamic all-movie monitoring enabled "
                f"({len(movies)} movies currently listed)."
            )

            return {
                "mode": "all",
                "movies": movies,
            }

        try:

            index = int(choice) - 1

            if 0 <= index < len(movies):

                selected = movies[index]

                log(
                    f"🎬 Monitoring only: {selected}"
                )

                return {
                    "mode": "single",
                    "movies": [selected],
                }

        except ValueError:
            pass

        print(
            "⚠️ Invalid selection. "
            "Please enter a movie number or A."
        )


async def select_movie(page, movie):
    """
    Select a specific movie from the movie carousel.

    The click is performed through JavaScript because
    the site's carousel/sticky header can intercept
    normal Playwright pointer clicks.
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

    await page.wait_for_timeout(
        2_000
    )

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
    Detect dates that changed from:

        unavailable -> available
    """

    new_showtimes = []

    previous_movie = previous.get(
        movie,
        {}
    )

    for date, info in current.items():

        currently_available = (
            info["available"]
        )

        previously_available = (
            previous_movie
            .get(date, {})
            .get(
                "available",
                False
            )
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
# MOVIE LIST CHANGES
# ============================================================

def detect_movie_changes(
    previous_movies,
    current_movies
):
    """
    Compare the movie list from the previous cycle
    to the current cycle.

    Returns:

        added_movies
        removed_movies
    """

    previous_set = set(
        previous_movies
    )

    current_set = set(
        current_movies
    )

    added_movies = [
        movie
        for movie in current_movies
        if movie not in previous_set
    ]

    removed_movies = [
        movie
        for movie in previous_movies
        if movie not in current_set
    ]

    return added_movies, removed_movies


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

    await page.wait_for_timeout(
        500
    )

    restore_focus(
        previous_window
    )

    return (
        p,
        browser,
        context,
        page
    )


async def refresh_movie_list(page):
    """
    Re-read the movie carousel from the live page.

    This is used in 'all' mode every monitoring cycle.
    """

    movies = await get_movies(page)

    if not movies:

        raise RuntimeError(
            "No movies currently found in carousel."
        )

    return movies


# ============================================================
# INITIAL SITE SETUP
# ============================================================

async def check_site():
    """
    Open the IMAX site and allow the user to select
    a movie or dynamic all-movie monitoring.

    Returns:

        p
        browser
        context
        page
        monitoring_config
    """

    (
        p,
        browser,
        context,
        page
    ) = await open_browser()

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

        await page.wait_for_timeout(
            5_000
        )

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

            return (
                None,
                None,
                None,
                None,
                None
            )

        monitoring_config = (
            await choose_movies(page)
        )

        return (
            p,
            browser,
            context,
            page,
            monitoring_config
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
            context,
            page,
            monitoring_config
        ) = await check_site()

    except Exception as e:

        log(
            f"❌ Could not start monitor: {e}"
        )

        return

    if not monitoring_config:

        log(
            "❌ No monitoring configuration."
        )

        await browser.close()
        await p.stop()

        return

    mode = monitoring_config["mode"]

    selected_movies = (
        monitoring_config["movies"]
    )

    # This is used only in all mode.
    previous_movie_list = (
        selected_movies.copy()
    )

    try:

        while True:

            cycle_start = datetime.now(
                BOISE_TZ
            )

            all_new_showtimes = []
            errors = 0

            # ------------------------------------------------
            # REFRESH MOVIE LIST IN ALL MODE
            # ------------------------------------------------

            if mode == "all":

                try:

                    current_movies = (
                        await refresh_movie_list(
                            page
                        )
                    )

                    (
                        added_movies,
                        removed_movies
                    ) = detect_movie_changes(
                        previous_movie_list,
                        current_movies
                    )

                    if added_movies:

                        for movie in added_movies:

                            log(
                                f"🆕 New movie detected: "
                                f"{movie}"
                            )

                    if removed_movies:

                        for movie in removed_movies:

                            log(
                                f"🗑️ Movie removed: "
                                f"{movie}"
                            )

                    selected_movies = (
                        current_movies
                    )

                    previous_movie_list = (
                        current_movies.copy()
                    )

                except Exception as e:

                    errors += 1

                    log(
                        f"❌ Could not refresh movie list: "
                        f"{e}"
                    )

                    # If the movie list cannot be refreshed,
                    # continue using the previous list.
                    selected_movies = (
                        previous_movie_list
                    )

            # ------------------------------------------------
            # CHECK MOVIES
            # ------------------------------------------------

            log(
                f"🔍 Checking "
                f"{len(selected_movies)} movie(s)..."
            )

            checked = 0

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

                    # Only update state after a
                    # successful calendar read.
                    state[movie] = weekend

                    save_state(
                        state
                    )

                    checked += 1

                except Exception as e:

                    errors += 1

                    log(
                        f"❌ {movie}: {e}"
                    )

            # ------------------------------------------------
            # DISCORD NOTIFICATIONS
            # ------------------------------------------------

            if all_new_showtimes:

                await notify_discord(
                    all_new_showtimes
                )

            # ------------------------------------------------
            # CYCLE SUMMARY
            # ------------------------------------------------

            elapsed = (
                datetime.now(
                    BOISE_TZ
                )
                - cycle_start
            ).total_seconds()

            if errors == 0:

                if all_new_showtimes:

                    log(
                        f"🚨 Checked "
                        f"{checked} movies in "
                        f"{elapsed:.1f}s — "
                        f"{len(all_new_showtimes)} "
                        f"new showtime(s) found!"
                    )

                else:

                    log(
                        f"✅ Checked "
                        f"{checked} movies in "
                        f"{elapsed:.1f}s — "
                        f"no new showtimes."
                    )

            else:

                log(
                    f"⚠️ Checked "
                    f"{checked} movies in "
                    f"{elapsed:.1f}s — "
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

        log(
            "Closing browser..."
        )

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

