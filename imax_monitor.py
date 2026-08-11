
import argparse
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

DEFAULT_IMAX_URL = "https://www.imax.com/theatre/regal-edwards-boise-imax"

CHECK_INTERVAL_MINUTES = 15

STATE_FILE = "imax_state.json"
CONFIG_FILE = "imax_monitor_config.json"
STATUS_FILE = "imax_monitor_status.json"

BOISE_TZ = ZoneInfo("America/Boise")

discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", ""
).strip()

def load_monitor_config():

    try:
        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except (
        OSError,
        json.JSONDecodeError
    ):
        return {}

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
# JSON FILE UTILITIES
# ============================================================
        
def load_json_file(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except (json.JSONDecodeError, OSError):
        return default


def save_json_file(path, data):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    os.replace(temp, path)


def load_web_config():
    """
    Read configuration written by the web UI.

    Returns:
        {
            "mode": "all" | "selected",
            "movies": [...]
        }

    or None if no valid web configuration exists.
    """

    config = load_json_file(
        CONFIG_FILE,
        None
    )

    if not config:
        return None

    mode = config.get("mode")
    movies = config.get("movies", [])

    if mode not in {"all", "selected"}:
        return None

    if not isinstance(movies, list):
        movies = []

    return {
        "mode": mode,
        "movies": list(
            dict.fromkeys(
                str(movie)
                for movie in movies
            )
        )
    }


def write_web_status(
    *,
    running=True,
    mode=None,
    selected_movies=None,
    available_movies=None,
    showtimes=None,
    last_check=None,
    next_check=None,
    error_message=""
):
    """
    Publish monitor state for the web UI.
    """

    status = load_json_file(
        STATUS_FILE,
        {}
    )

    status.update({
        "running": running,
        "mode": mode,
        "selected_movies": selected_movies or [],
        "available_movies": available_movies or [],
        "showtimes": showtimes or {},
        "last_check": last_check,
        "next_check": next_check,
        "error_message": error_message,
        "last_update": datetime.now(
            BOISE_TZ
        ).isoformat(),
    })

    save_json_file(
        STATUS_FILE,
        status
    )


def get_check_now_token():
    """
    Used by the web UI to request an immediate check.
    """

    status = load_json_file(
        STATUS_FILE,
        {}
    )

    return status.get("check_now")


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

    if not discord_webhook_url:

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
        f"🔗 {DEFAULT_IMAX_URL}"
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
        discord_webhook_url,
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


async def choose_movies(page, args):
    """
    Determine which movies should be monitored.

    Supported modes:

        --all
            Dynamically monitor every movie currently listed.
            Newly added movies are automatically detected and monitored.

        --movie "Movie Title"
            Monitor one specific movie.

        --movies "Movie 1" "Movie 2"
            Monitor multiple specific movies.

        No arguments
            Show an interactive menu.

    Returns:

        {
            "mode": "all",
            "movies": [...]
        }

    or:

        {
            "mode": "selected",
            "movies": [...]
        }
    """

    log("Finding available IMAX movies...")

    await page.wait_for_timeout(2_000)

    movies = await get_movies(page)

    if not movies:
        raise RuntimeError(
            "No movies were found in the IMAX carousel."
        )

    # ------------------------------------------------------------
    # --all
    # ------------------------------------------------------------

    if args.all:
        log(
            f"🎬 Dynamic all-movie monitoring enabled "
            f"({len(movies)} movies currently listed)."
        )

        return {
            "mode": "all",
            "movies": movies,
        }

    # ------------------------------------------------------------
    # --movie
    # ------------------------------------------------------------

    if args.movie:
        if args.movie not in movies:
            raise ValueError(
                f"Movie not found: {args.movie}\n"
                f"Available movies: {', '.join(movies)}"
            )

        log(f"🎬 Monitoring only: {args.movie}")

        return {
            "mode": "selected",
            "movies": [args.movie],
        }

    # ------------------------------------------------------------
    # --movies
    # ------------------------------------------------------------

    if args.movies:
        invalid = [
            movie
            for movie in args.movies
            if movie not in movies
        ]

        if invalid:
            raise ValueError(
                "The following movies were not found:\n"
                + "\n".join(f"  - {movie}" for movie in invalid)
                + "\n\nAvailable movies:\n"
                + "\n".join(f"  - {movie}" for movie in movies)
            )

        # Remove duplicates while preserving order.
        selected = list(dict.fromkeys(args.movies))

        log(
            f"🎬 Monitoring {len(selected)} selected movie(s):"
        )

        for movie in selected:
            log(f"   • {movie}")

        return {
            "mode": "selected",
            "movies": selected,
        }

    # ------------------------------------------------------------
    # No arguments → interactive mode
    # ------------------------------------------------------------

    print()
    print("=" * 60)
    print("AVAILABLE IMAX MOVIES")
    print("=" * 60)

    for i, movie in enumerate(movies, start=1):
        print(f"{i}. {movie}")

    print()
    print("A. Check all movies")
    print("You can select multiple movies, e.g. 1 3 5")
    print()

    while True:
        choice = input(
            "Select movie(s), or A for all: "
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
            indexes = [
                int(value) - 1
                for value in choice.split()
            ]

            if not indexes:
                raise ValueError

            if not all(
                0 <= index < len(movies)
                for index in indexes
            ):
                raise ValueError

            # Remove duplicate selections while preserving order.
            indexes = list(dict.fromkeys(indexes))

            selected = [
                movies[index]
                for index in indexes
            ]

            log(
                f"🎬 Monitoring {len(selected)} selected movie(s):"
            )

            for movie in selected:
                log(f"   • {movie}")

            return {
                "mode": "selected",
                "movies": selected,
            }

        except ValueError:
            print(
                "⚠️ Invalid selection. "
                "Enter movie numbers separated by spaces or A."
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
# COMMAND-LINE ARGUMENTS
# ============================================================

def parse_args():
    """Parse command-line monitoring options."""

    parser = argparse.ArgumentParser(
        description="IMAX Showtime Monitor"
    )

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "--all",
        action="store_true",
        help="Monitor all movies dynamically"
    )

    group.add_argument(
        "--movie",
        type=str,
        help="Monitor one specific movie"
    )

    group.add_argument(
        "--movies",
        nargs="+",
        help="Monitor multiple specific movies"
    )

    return parser.parse_args()


# ============================================================
# INITIAL SITE SETUP
# ============================================================

async def check_site(args, imax_url):
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
            imax_url,
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
            await choose_movies(page, args)
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

async def monitor(args):

    state = load_state()

    monitor_config = load_monitor_config()
    
    imax_url = monitor_config.get(
        "imax_theatre_url",
        DEFAULT_IMAX_URL
    )

    discord_webhook_url = monitor_config.get(
        "discord_webhook_url",
        ""
    )

    # If the web UI already has a configuration,
    # use it when no CLI movie-selection argument was supplied.
    web_config = load_web_config()

    if web_config and not (
        args.all
        or args.movie
        or args.movies
    ):
        args.all = (
            web_config["mode"] == "all"
        )

        args.movie = None

        args.movies = (
            web_config["movies"]
            if web_config["mode"] == "selected"
            else None
        )

    try:

        (
            p,
            browser,
            context,
            page,
            monitoring_config
        ) = await check_site(args, imax_url)

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
    # All movies currently known to exist on IMAX.
    available_movies = (
        await get_movies(page)
    )

    # Movies currently being monitored.
    selected_movies = (
        monitoring_config["movies"]
    )

    # Used to detect movies being added/removed.
    previous_movie_list = (
        available_movies.copy()
    )

    write_web_status(
        running=True,
        mode=mode,
        selected_movies=selected_movies,
        available_movies=available_movies,
        showtimes={},
        last_check=None,
        next_check=None,
    )

    try:

        while True:

            # ========================================================
            # CHECK FOR SETTINGS / WEB UI CONFIGURATION CHANGES
            # ========================================================

            # Reload the monitor settings every cycle so a theatre URL
            # saved from the web UI is picked up without restarting.
            latest_monitor_config = load_monitor_config()
            requested_imax_url = latest_monitor_config.get(
                "imax_theatre_url",
                DEFAULT_IMAX_URL
            ).strip() or DEFAULT_IMAX_URL

            if requested_imax_url != imax_url:

                old_imax_url = imax_url
                imax_url = requested_imax_url

                log(
                    "🌐 IMAX theatre URL changed."
                )
                log(
                    f"   Old: {old_imax_url}"
                )
                log(
                    f"   New: {imax_url}"
                )

                # ----------------------------------------------------
                # RESET ALL THEATRE-SPECIFIC DATA
                # ----------------------------------------------------
                #
                # Movie names, showtime state, and web UI showtimes
                # belong to the previous theatre. Do not carry any of
                # that data over to the new theatre.
                #
                # ----------------------------------------------------
                # RESET ALL THEATRE-SPECIFIC DATA
                # ----------------------------------------------------

                # Clear showtime state.
                state = {}
                save_state(state)

                # Clear all in-memory movie data.
                available_movies = []
                previous_movie_list = []
                selected_movies = []

                # Clear all web UI showtime data.
                web_showtimes = {}

                # ----------------------------------------------------
                # CLEAR SAVED MOVIE SELECTIONS
                # ----------------------------------------------------

                current_web_config = load_json_file(
                    CONFIG_FILE,
                    {}
                )

                if current_web_config:

                    current_web_config["movies"] = []
                    current_web_config["updated_at"] = (
                        datetime.now().isoformat()
                    )

                    save_json_file(
                        CONFIG_FILE,
                        current_web_config
                    )

                # ----------------------------------------------------
                # CLEAR STATUS FILE
                # ----------------------------------------------------

                # IMPORTANT:
                # The old status file must also be cleared.
                # Otherwise the code below will load the old
                # theatre's movies/showtimes back into memory.

                empty_status = {
                    "running": True,
                    "mode": mode,
                    "selected_movies": [],
                    "available_movies": [],
                    "showtimes": {},
                    "last_check": None,
                    "next_check": None,
                    "error_message": "",
                }

                save_json_file(
                    STATUS_FILE,
                    empty_status
                )

                try:
                    log(
                        "🔄 Opening new IMAX theatre..."
                    )

                    response = await page.goto(
                        imax_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )

                    if response:
                        log(
                            f"HTTP status: {response.status}"
                        )

                    await page.wait_for_timeout(5_000)

                    # Rebuild the movie list entirely from the new
                    # theatre. Nothing from the old theatre is reused.
                    new_movies = await get_movies(page)

                    available_movies = new_movies.copy()
                    previous_movie_list = new_movies.copy()

                    if mode == "all":
                        # ALL mode automatically monitors every movie
                        # currently listed at the new theatre.
                        selected_movies = new_movies.copy()

                    else:
                        # SELECTED mode starts empty because the old
                        # theatre's selections are no longer valid.
                        selected_movies = []

                    log(
                        f"✅ Switched to new theatre. "
                        f"Found {len(new_movies)} movie(s)."
                    )

                    if mode == "selected":
                        log(
                            "ℹ️ Old movie selections were cleared. "
                            "Select movies from the new theatre in "
                            "the web UI."
                        )

                except Exception as e:

                    log(
                        f"❌ Could not open new IMAX theatre: {e}"
                    )

                    # Do not restore the old theatre's movies/state.
                    # The old data has deliberately been discarded.
                    # The next cycle will retry the new URL.
                    errors += 1

            web_config = load_web_config()

            if web_config:

                requested_mode = web_config["mode"]
                requested_movies = web_config["movies"]

                config_changed = (
                    requested_mode != mode
                )

                if requested_mode == "selected":
                    config_changed = (
                        config_changed
                        or requested_movies != selected_movies
                    )

                if config_changed:

                    mode = requested_mode

                    if mode == "selected":
                        selected_movies = (
                            requested_movies.copy()
                        )

                    log(
                        f"🌐 Web UI changed monitoring "
                        f"mode to {mode} "
                        f"({len(selected_movies)} movie(s))."
                    )

                    if mode == "all":
                        previous_movie_list = (
                            selected_movies.copy()
                        )

            cycle_start = datetime.now(
                BOISE_TZ
            )

            all_new_showtimes = []
            errors = 0

            # Current web UI showtime data. This is reset when the
            # theatre changes so old-theatre showtimes are never reused.
            old_status = load_json_file(
                STATUS_FILE,
                {}
            )

            web_showtimes = old_status.get(
                "showtimes",
                {}
            )

            # ------------------------------------------------
            # REFRESH MOVIE LIST IN ALL MODE
            # ------------------------------------------------

            if mode == "all":
                
                write_web_status(
                    running=True,
                    mode=mode,
                    selected_movies=selected_movies,
                    available_movies=available_movies,
                    showtimes=load_json_file(
                        STATUS_FILE,
                        {}
                    ).get(
                        "showtimes",
                        {}
                    ),
                    last_check=load_json_file(
                        STATUS_FILE,
                        {}
                    ).get(
                        "last_check"
                    ),
                    next_check=None,
                )

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

                    available_movies = previous_movie_list

                    previous_movie_list = current_movies.copy()

                    # Only automatically select everything when
                    # we are genuinely operating in ALL mode.
                    if mode == "all":
                        selected_movies = current_movies.copy()

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

                    # Publish calendar information to the web UI.
                    web_showtimes[movie] = [
                        {
                            "date": date,
                            "day": info["day"],
                            "available": info["available"],
                        }
                        for date, info in weekend.items()
                    ]

                    checked += 1

                except Exception as e:

                    errors += 1

                    log(
                        f"❌ {movie}: {e}"
                    )
            # ========================================================
            # UPDATE WEB UI STATUS
            # ========================================================

            last_check = datetime.now(
                BOISE_TZ
            )

            next_check = (
                last_check
                + timedelta(
                    minutes=CHECK_INTERVAL_MINUTES
                )
            )

            write_web_status(
                running=True,
                mode=mode,
                selected_movies=selected_movies,
                available_movies=(
                    selected_movies
                    if mode == "selected"
                    else previous_movie_list
                ),
                showtimes=web_showtimes,
                last_check=last_check.isoformat(),
                next_check=next_check.isoformat(),
                error_message=(
                    ""
                    if errors == 0
                    else f"{errors} error(s)"
                ),
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

            expected_check_now = (
                get_check_now_token()
            )

            wait_until = (
                datetime.now(BOISE_TZ)
                + timedelta(
                    minutes=CHECK_INTERVAL_MINUTES
                )
            )

            while datetime.now(BOISE_TZ) < wait_until:

                await asyncio.sleep(1)

                # ------------------------------------------------
                # CHECK NOW
                # ------------------------------------------------

                if (
                    get_check_now_token()
                    != expected_check_now
                ):

                    log(
                        "🌐 Web UI requested an immediate check."
                    )

                    break

                # ------------------------------------------------
                # CONFIGURATION CHANGE
                # ------------------------------------------------

                latest_config = (
                    load_web_config()
                )

                latest_config = load_web_config()

                if latest_config:

                    config_changed = (
                        latest_config["mode"] != mode
                    )

                    # In selected mode, movie changes matter.
                    if latest_config["mode"] == "selected":
                        config_changed = (
                            config_changed
                            or latest_config["movies"]
                            != selected_movies
                        )

                    if config_changed:

                        log(
                            "🌐 Web UI configuration changed."
                        )

                        break

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

    args = parse_args()

    try:

        asyncio.run(
            monitor(args)
        )

    except KeyboardInterrupt:

        print()

        log(
            "Monitor stopped."
        )
