# 🎬 IMAX Showtime Monitor

A Python-based monitoring service that automatically tracks movie availability at the **Regal Edwards Boise IMAX**, detects newly released showtimes, and sends real-time Discord notifications.

The monitor uses **Playwright with Chromium** to interact with the live IMAX website, dynamically discovers available movies, supports monitoring a single movie or **all currently available movies**, and maintains persistent state between checks to prevent duplicate notifications.

---

## ✨ Features

* 🎬 **Dynamic movie discovery**

  * Automatically detects all movies currently listed by the IMAX theatre.
  * No movie titles need to be hard-coded.

* 🔎 **Check All mode**

  * Monitor every movie currently listed at the theatre.
  * Automatically detects when a new movie appears.
  * Automatically stops checking movies that have been removed.

* 🎯 **Individual movie monitoring**

  * Select a specific movie when starting the program.
  * Useful when monitoring only one upcoming release.

* 📅 **Showtime availability detection**

  * Monitors the IMAX calendar for newly released dates.
  * Detects transitions from unavailable → available.

* 🔔 **Discord notifications**

  * Sends a Discord webhook whenever new showtime availability is detected.
  * Notifications include the movie, date, and day of the week.

* 💾 **Persistent state**

  * Stores previously detected availability in a JSON state file.
  * Prevents duplicate notifications between monitoring cycles.
  * State is preserved when the website temporarily fails.

* 🌐 **Real Chromium browser**

  * Uses Playwright's Chromium browser instead of simple HTTP requests.
  * Allows the site’s JavaScript and browser verification systems to execute normally.

* 🖥️ **Background-friendly browser**

  * Chromium runs off-screen.
  * The program attempts to restore focus to the user's previous application.

* ⏱️ **Configurable polling interval**

  * Checks the theatre periodically without continuously hammering the website.

* 📊 **Condensed logging**

  * Each monitoring cycle produces a short summary instead of flooding the terminal with individual operations.

* 🔐 **Environment-based configuration**

  * Discord credentials are stored in a `.env` file rather than being hard-coded.

---

# 🏗️ How It Works

The monitor follows a continuous polling architecture:

```text
                  ┌─────────────────────┐
                  │     Start Program   │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │   Launch Chromium   │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │   Open IMAX Page    │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Discover Movies      │
                  └──────────┬──────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
               Single Movie       Check All
                    │                 │
                    └────────┬────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Select Movie        │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Read Calendar       │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Compare With State  │
                  └──────────┬──────────┘
                             │
                   New showtime?
                    ┌────────┴────────┐
                    │                 │
                   Yes                No
                    │                 │
                    ▼                 │
             Discord Webhook          │
                    │                 │
                    └────────┬────────┘
                             ▼
                  ┌─────────────────────┐
                  │ Save Current State  │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Wait N Minutes      │
                  └──────────┬──────────┘
                             │
                             └──────────► Repeat
```

---

# 🧠 Dynamic Movie Monitoring

One of the main design goals of the project is avoiding hard-coded movie titles.

The IMAX page exposes its movie carousel through elements containing:

```html
<div data-testid="movie-card">
```

Each movie card contains an image whose `alt` attribute identifies the movie:

```html
<img alt="The Odyssey">
```

The monitor extracts these titles dynamically.

For example:

```text
The Odyssey
Spider-Man: Brand New Day
Ghost: 2 Big to Rig
Katy Perry: The Lifetimes Tour - Live From Paris
```

This allows the monitor to adapt automatically as the theatre's movie lineup changes.

---

# 🔄 Check All Mode

When **Check All** is selected, the program does not permanently store the initial movie list.

Instead, the movie carousel is rediscovered whenever a new monitoring cycle begins.

This allows the program to respond to changes on the IMAX website.

### Example

Initial cycle:

```text
The Odyssey
Spider-Man: Brand New Day
Ghost: 2 Big to Rig
```

Later, the website adds:

```text
The Odyssey
Spider-Man: Brand New Day
Ghost: 2 Big to Rig
Avatar 4
```

The next cycle discovers:

```text
+ Avatar 4
```

and automatically begins checking it.

Similarly, if a movie disappears:

```text
Before:
The Odyssey
Spider-Man: Brand New Day
Ghost: 2 Big to Rig

After:
The Odyssey
Spider-Man: Brand New Day
```

The removed movie is no longer checked.

This makes **Check All** a dynamic monitoring mode rather than a static list of movies selected at startup.

---

# 📅 Showtime Detection

The monitor reads the theatre's calendar and determines whether each date is available.

The internal representation looks approximately like:

```json
{
  "2026-08-07": {
    "available": false,
    "day": "Friday"
  },
  "2026-08-08": {
    "available": false,
    "day": "Saturday"
  },
  "2026-08-09": {
    "available": true,
    "day": "Sunday"
  }
}
```

The monitor compares this against the previous state.

A notification is triggered when:

```text
Previous: unavailable
Current:  available
```

For example:

```text
Before
Friday    ❌
Saturday  ❌
Sunday    ❌

After
Friday    ❌
Saturday  ✅
Sunday    ❌
```

The monitor detects:

```text
Saturday → newly available
```

and sends a Discord notification.

---

# 💾 Persistent State

The monitor uses `imax_state.json` to persist the previously observed state.

A simplified state file looks like:

```json
{
  "The Odyssey": {
    "2026-08-07": {
      "available": false,
      "day": "Friday"
    },
    "2026-08-08": {
      "available": true,
      "day": "Saturday"
    }
  },
  "Spider-Man: Brand New Day": {
    "2026-08-07": {
      "available": false,
      "day": "Friday"
    }
  }
}
```

The state is organized by movie so that each movie has an independent availability history.

This is important because different movies can have completely different release schedules.

---

# 🔔 Discord Notifications

When new availability is detected, the monitor sends a Discord webhook.

Example:

```text
🚨 NEW IMAX SHOWTIMES RELEASED! 🚨

🎬 The Odyssey
📅 Saturday, 2026-08-08

🔗 https://www.imax.com/theatre/regal-edwards-boise-imax
```

If multiple movies or dates become available during the same cycle, they can be included in the same notification.

---

# 🔐 Environment Variables

The Discord webhook URL is loaded from an environment variable rather than being stored directly in the source code.

Create a `.env` file:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

The application loads it with:

```python
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL"
)
```

### Security

The `.env` file should **never be committed to Git**.

Add it to `.gitignore`:

```gitignore
.env
imax_state.json
imax_monitor_failure.png
imax_monitor_failure.html
__pycache__/
```

---

# 🛠️ Technologies

| Technology           | Purpose                         |
| -------------------- | ------------------------------- |
| **Python**           | Core application                |
| **Playwright**       | Browser automation              |
| **Chromium**         | Real browser environment        |
| **asyncio**          | Asynchronous monitoring         |
| **JSON**             | Persistent state storage        |
| **Discord Webhooks** | Notifications                   |
| **python-dotenv**    | Environment configuration       |
| **zoneinfo**         | Boise timezone handling         |
| **ctypes**           | Windows window/focus management |

---

# 📦 Installation

## 1. Clone the repository

```bash
git clone <your-repository-url>
cd imax-showtime-monitor
```

## 2. Create a virtual environment

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Install dependencies

```bash
pip install playwright python-dotenv
```

## 4. Install Chromium

```bash
playwright install chromium
```

---

# ⚙️ Configuration

The primary configuration is located near the top of the Python file:

```python
URL = "https://www.imax.com/theatre/regal-edwards-boise-imax"

CHECK_INTERVAL_MINUTES = 15

STATE_FILE = "imax_state.json"
```

### Check interval

Change:

```python
CHECK_INTERVAL_MINUTES = 15
```

to control how frequently the monitor checks the website.

For example:

```python
CHECK_INTERVAL_MINUTES = 10
```

checks every ten minutes.

---

# ▶️ Running the Monitor

Start the program with:

```bash
python imax_monitor.py
```

The program opens Chromium and discovers the currently available movies.

You'll then see something similar to:

```text
============================================================
AVAILABLE IMAX MOVIES
============================================================

1. The Odyssey
2. Spider-Man: Brand New Day
3. Ghost: 2 Big to Rig
4. Katy Perry: The Lifetimes Tour - Live From Paris

A. Check all movies

Select a movie number or A for all:
```

Selecting:

```text
A
```

enables dynamic monitoring of all movies.

---

# 📊 Logging

The monitor intentionally keeps normal operation logging concise.

Instead of logging every browser operation, a completed cycle produces something like:

```text
[2026-08-06 02:00:22 AM] 🔍 Checking 4 movie(s)...
[2026-08-06 02:00:31 AM] ✅ Checked 4 movies in 9.2s — no new showtimes.
[2026-08-06 02:00:31 AM] ⏳ Next check in 15 minutes.
```

When new availability is detected:

```text
[2026-08-06 02:15:22 AM] 🔍 Checking 4 movie(s)...
[2026-08-06 02:15:31 AM] 🚨 NEW SHOWTIME: The Odyssey | Saturday, 2026-08-08
[2026-08-06 02:15:32 AM] ✅ Discord notification sent!
[2026-08-06 02:15:32 AM] 🚨 Checked 4 movies in 10.1s — 1 new showtime(s) found!
```

This makes long-running monitoring much easier to follow.

---

# 🖥️ Browser Behavior

The monitor intentionally uses:

```python
headless=False
```

rather than headless Chromium.

This is useful because the IMAX site relies on client-side JavaScript and browser behavior that may not work reliably with a simple HTTP request.

The browser is launched with:

```text
--window-position=-2000,-2000
```

which places the Chromium window outside the visible desktop area.

The application also records the currently focused Windows window before launching Chromium and attempts to restore focus afterward.

This allows the monitor to run while the user continues working normally.

---

# 🧩 Movie Selection

The program interacts with the site's movie carousel.

Rather than clicking the image itself, the monitor identifies the surrounding movie slide and triggers the slide's click handler.

Conceptually:

```text
Movie carousel
      │
      ├── Movie Card
      │      └── Image
      │            └── alt="The Odyssey"
      │
      ├── Movie Card
      │      └── Image
      │            └── alt="Spider-Man: Brand New Day"
      │
      └── Movie Card
             └── Image
                   └── alt="Ghost: 2 Big to Rig"
```

This is necessary because the website's layered carousel UI can cause normal Playwright clicks to be intercepted by overlay elements.

---

# 🧯 Error Handling

The monitor is designed to continue running when an individual check fails.

For example:

```text
[2026-08-06 02:30:00 AM] 🔍 Checking 4 movie(s)...
[2026-08-06 02:30:08 AM] ⚠️ Checked 3 movies in 8.1s — 1 error(s).
```

A failed movie check does **not** overwrite that movie's previous state.

Likewise, if the calendar cannot be found, diagnostic files are generated:

```text
imax_monitor_failure.png
imax_monitor_failure.html
```

These can be inspected to determine what the website returned during the failed check.

---

# 🧠 Design Decisions

## Why Playwright?

A conventional HTTP scraper would only receive the initial HTML response.

The IMAX site is highly dynamic and uses JavaScript to construct parts of the page, including the movie carousel and calendar.

Playwright allows the monitor to interact with the same browser-rendered interface a user sees.

---

## Why persistent JSON state?

Without persistent state, the program would have no way to distinguish:

```text
"This date was already available"
```

from:

```text
"This date just became available"
```

The JSON state provides a lightweight persistence layer without requiring a database.

---

## Why rediscover movies?

Movie listings are inherently dynamic.

A hard-coded list would require manually updating the program whenever the theatre changes its lineup.

Dynamic discovery allows the monitor to adapt automatically.

---

## Why keep the browser open?

The browser is launched once and reused for subsequent checks rather than starting a completely new browser process every few minutes.

This reduces unnecessary startup overhead and keeps the monitoring loop simpler.

---

# 📁 Project Structure

A typical project directory looks like:

```text
imax-showtime-monitor/
│
├── imax_monitor.py
├── imax_state.json
├── .env
├── .gitignore
├── README.md
│
├── imax_monitor_failure.png
└── imax_monitor_failure.html
```

The diagnostic files are only created when a website check fails.

---

# 🔮 Potential Future Improvements

Several features could be added as the project evolves:

### Database storage

Replace JSON with SQLite for:

* historical showtime tracking
* notification history
* multiple theatres
* historical availability analysis

### Multiple theatres

Support monitoring several IMAX locations simultaneously.

```text
Boise IMAX
Meridian IMAX
Salt Lake City IMAX
...
```

### Showtime-level monitoring

Currently the monitor tracks calendar availability.

A future version could extract individual showtimes:

```text
Friday
2:15 PM
5:30 PM
8:45 PM
```

and detect newly added individual screenings.

### Web dashboard

A lightweight dashboard could display:

```text
┌────────────────────────────────────┐
│ IMAX Showtime Monitor              │
├────────────────────────────────────┤
│ The Odyssey                        │
│ Friday      ❌                     │
│ Saturday    ✅  2:15 PM, 5:30 PM  │
│ Sunday      ❌                     │
└────────────────────────────────────┘
```

### Additional notification platforms

The notification system could be extended to support:

* Email
* SMS
* Push notifications
* Telegram
* Slack

### Scheduling

The monitor could be configured to check more frequently during periods when theatres typically release new showtimes.

---

# ⚠️ Disclaimer

This project is intended for personal monitoring and automation.

The monitor should be configured with a reasonable polling interval and should avoid unnecessarily high request rates.

The project is not affiliated with or endorsed by IMAX or Regal.

---

# 👨‍💻 Project Highlights

This project demonstrates practical experience with:

* **Browser automation**
* **Asynchronous Python**
* **DOM inspection**
* **Dynamic web interfaces**
* **Persistent application state**
* **Event/change detection**
* **Webhook APIs**
* **Environment-based configuration**
* **Error handling and diagnostics**
* **Windows process/window management**
* **Long-running background services**

The project was built around a real-world problem: **detecting when IMAX showtimes become available quickly enough to act on them, without manually checking the theatre website.**

---

## 📜 License


```text
The MIT License (MIT)

Copyright (c) 2026 Ryan Macfarlane

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```
