import argparse
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

CONFIG_FILE = "imax_monitor_config.json"
STATUS_FILE = "imax_monitor_status.json"
STATE_FILE = "imax_state.json"

HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IMAX Monitor</title>
<style>
:root {
    color-scheme: dark;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
body {
    margin: 0;
    background: #0f1115;
    color: #f1f3f5;
}
.container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 24px;
}
header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    margin-bottom: 20px;
}
h1 { margin: 0; font-size: 28px; }
.muted { color: #9aa1ac; }
.status-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
.card {
    background: #181b21;
    border: 1px solid #292e37;
    border-radius: 12px;
    padding: 16px;
}
.value {
    font-size: 20px;
    font-weight: 700;
    margin-top: 5px;
}
.controls {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 20px;
}
button {
    border: 1px solid #343a46;
    background: #20242c;
    color: #fff;
    padding: 10px 14px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 14px;
}
button:hover { background: #2a303a; }
button.primary { background: #3b82f6; border-color: #3b82f6; }
button.danger { background: #9f3030; border-color: #9f3030; }
.movie-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
    gap: 12px;
}
.movie {
    background: #181b21;
    border: 1px solid #292e37;
    border-radius: 12px;
    padding: 16px;
}
.movie.selected {
    border-color: #3b82f6;
}
.movie-top {
    display: flex;
    align-items: flex-start;
    gap: 12px;
}
.movie-name {
    flex: 1;
    font-weight: 700;
    line-height: 1.3;
}
.toggle {
    width: 22px;
    height: 22px;
    accent-color: #3b82f6;
}
.dates {
    margin-top: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.date {
    background: #252a33;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 12px;
}
.no-showtimes {
    margin-top: 12px;
    color: #8d949f;
    font-size: 13px;
}
.error {
    color: #ff8585;
    margin-top: 8px;
}
#updated {
    font-size: 12px;
    color: #777f8c;
}
</style>
</head>
<body>
<div class="container">
<header>
    <div>
        <h1>🎬 IMAX Monitor</h1>
        <div class="muted">Regal Edwards Boise IMAX</div>
    </div>
    <div id="updated">Loading...</div>
</header>

<div class="status-grid">
    <div class="card">
        <div class="muted">Status</div>
        <div class="value" id="status">—</div>
    </div>
    <div class="card">
        <div class="muted">Mode</div>
        <div class="value" id="mode">—</div>
    </div>
    <div class="card">
        <div class="muted">Monitoring</div>
        <div class="value" id="count">—</div>
    </div>
    <div class="card">
        <div class="muted">Last Check</div>
        <div class="value" id="last-check">—</div>
    </div>
    <div class="card">
        <div class="muted">Next Check</div>
        <div class="value" id="next-check">—</div>
    </div>
</div>

<div class="controls">
    <button class="primary" onclick="setAll()">Monitor All</button>
    <button onclick="clearAll()">Deselect All</button>
    <button onclick="checkNow()">Check Now</button>
    <button onclick="refresh()">Refresh</button>
</div>

<div id="error" class="error"></div>
<div id="movies" class="movie-grid"></div>
</div>

<script>
let statusData = {};

function esc(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || "Request failed");
    }

    return data;
}

async function refresh() {
    try {
        statusData = await api("/api/status");

        document.getElementById("status").textContent =
            statusData.running ? "Running" : "Stopped";

        document.getElementById("mode").textContent =
            statusData.mode === "all" ? "All Movies" : "Selected";

        document.getElementById("count").textContent =
            `${(statusData.selected_movies || []).length} movie(s)`;

        document.getElementById("last-check").textContent =
            formatTime(statusData.last_check);

        document.getElementById("next-check").textContent =
            formatTime(statusData.next_check);

        document.getElementById("updated").textContent =
            `Updated ${formatTime(statusData.last_update)}`;

        document.getElementById("error").textContent =
            statusData.error_message || "";

        renderMovies();
    } catch (error) {
        document.getElementById("error").textContent = error.message;
    }
}

function renderMovies() {
    const movies = statusData.available_movies || [];
    const selected = new Set(statusData.selected_movies || []);
    const showtimes = statusData.showtimes || {};

    const html = movies.map(movie => {
        const isSelected = selected.has(movie);
        const dates = showtimes[movie] || [];

        return `
        <div class="movie ${isSelected ? "selected" : ""}">
            <div class="movie-top">
                <input
                    class="toggle"
                    type="checkbox"
                    ${isSelected ? "checked" : ""}
                    onchange="toggleMovie(${JSON.stringify(movie)}, this.checked)"
                >
                <div class="movie-name">${esc(movie)}</div>
            </div>

            ${
                dates.length
                ? `<div class="dates">
                    ${dates.map(item =>
                        `<span class="date">📅 ${esc(item.day)} ${esc(item.date)}</span>`
                    ).join("")}
                   </div>`
                : `<div class="no-showtimes">No showtimes detected</div>`
            }
        </div>`;
    }).join("");

    document.getElementById("movies").innerHTML =
        html || `<div class="muted">No movies found yet.</div>`;
}

async function toggleMovie(movie, checked) {
    try {
        let selected = new Set(statusData.selected_movies || []);

        if (checked) selected.add(movie);
        else selected.delete(movie);

        await api("/api/config", {
            method: "POST",
            body: JSON.stringify({
                mode: "selected",
                movies: [...selected]
            })
        });

        await refresh();
    } catch (error) {
        alert(error.message);
        await refresh();
    }
}

async function setAll() {
    try {
        await api("/api/config", {
            method: "POST",
            body: JSON.stringify({ mode: "all" })
        });
        await refresh();
    } catch (error) {
        alert(error.message);
    }
}

async function clearAll() {
    try {
        await api("/api/config", {
            method: "POST",
            body: JSON.stringify({ mode: "selected", movies: [] })
        });
        await refresh();
    } catch (error) {
        alert(error.message);
    }
}

async function checkNow() {
    try {
        await api("/api/check-now", { method: "POST" });
        await refresh();
    } catch (error) {
        alert(error.message);
    }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    os.replace(temp, path)


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[WEB] {format % args}")

    def send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        self.wfile.write(payload)

    def do_GET(self):

        path = urlparse(self.path).path

        if path == "/":
            payload = HTML.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/status":
            status = load_json(STATUS_FILE, {})

            config = load_json(
                CONFIG_FILE,
                {"mode": "selected", "movies": []}
            )

            status.setdefault("mode", config.get("mode", "selected"))
            status.setdefault("selected_movies", config.get("movies", []))
            status.setdefault("available_movies", [])
            status.setdefault("showtimes", {})

            self.send_json(status)
            return

        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):

        path = urlparse(self.path).path

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            data = json.loads(body or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json({"error": "Invalid JSON"}, 400)
            return

        if path == "/api/config":

            mode = data.get("mode")
            movies = data.get("movies", [])

            if mode not in {"all", "selected"}:
                self.send_json({"error": "Invalid mode"}, 400)
                return

            if not isinstance(movies, list):
                self.send_json({"error": "Movies must be a list"}, 400)
                return

            movies = list(dict.fromkeys(str(movie) for movie in movies))

            # In all mode the monitor will replace this list with
            # the current live movie list on its next cycle.
            save_json(
                CONFIG_FILE,
                {
                    "mode": mode,
                    "movies": movies,
                }
            )

            self.send_json({
                "ok": True,
                "mode": mode,
                "movies": movies,
            })
            return

        if path == "/api/check-now":

            status = load_json(STATUS_FILE, {})

            status["check_now"] = datetime.now().isoformat()

            save_json(STATUS_FILE, status)

            # The monitor checks this file while waiting and will
            # immediately start a new cycle when its timestamp changes.
            self.send_json({"ok": True})
            return

        self.send_json({"error": "Not found"}, 404)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Lightweight web UI for the IMAX Showtime Monitor"
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Web server bind address (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Web server port (default: 5000)"
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        Handler
    )

    print()
    print("=" * 60)
    print("IMAX MONITOR WEB UI")
    print("=" * 60)
    print(f"Open: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop the web UI.")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web UI...")
    finally:
        server.server_close()
