import argparse
import json
import os
import mimetypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

CONFIG_FILE = "imax_monitor_config.json"
STATUS_FILE = "imax_monitor_status.json"
STATE_FILE = "imax_state.json"

# Load the HTML template for the web UI from the same directory as this script.
HTML = open(
    os.path.join(os.path.dirname(__file__), "index.html"),
    "r",
    encoding="utf-8"
).read()


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


def load_config():
    return load_json(
        CONFIG_FILE,
        {
            "mode": "selected",
            "movies": [],
            "discord_webhook_url": "",
            "imax_theatre_url": "",
            "updated_at": None,
        }
    )


def save_config(
    mode,
    movies,
    discord_webhook_url=None,
    imax_theatre_url=None
):
    current = load_config()

    config = {
        "mode": mode,
        "movies": movies,
        "discord_webhook_url": (
            discord_webhook_url
            if discord_webhook_url is not None
            else current.get("discord_webhook_url", "")
        ),
        "imax_theatre_url": (
            imax_theatre_url
            if imax_theatre_url is not None
            else current.get("imax_theatre_url", "")
        ),
        "updated_at": datetime.now().isoformat(),
    }

    save_json(
        CONFIG_FILE,
        config
    )

    return config


class Handler(BaseHTTPRequestHandler):
    
    def serve_static_file(self, file_path):
        if not os.path.isfile(file_path):
            self.send_json(
                {"error": "File not found"},
                404
            )
            return

        content_type, _ = mimetypes.guess_type(file_path)

        if content_type is None:
            content_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                data = f.read()

            self.send_response(200)
            self.send_header(
                "Content-Type",
                content_type
            )
            self.send_header(
                "Content-Length",
                str(len(data))
            )
            self.end_headers()

            self.wfile.write(data)

        except OSError:
            self.send_json(
                {"error": "Could not read file"},
                500
            )

    def log_message(self, format, *args):
        print(f"[WEB] {format % args}")

    def send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json"
        )
        self.send_header(
            "Content-Length",
            str(len(payload))
        )
        self.send_header(
            "Cache-Control",
            "no-store"
        )
        self.end_headers()

        self.wfile.write(payload)

    def do_GET(self):
        
        path = urlparse(self.path).path
        
        # ----------------------------------------------------
        # STATIC FILES
        # ----------------------------------------------------

        if path.startswith("/images/"):

            filename = path[len("/images/"):]

            # Prevent directory traversal
            if (
                ".." in filename
                or "/" in filename
                or "\\" in filename
            ):
                self.send_json(
                    {"error": "Invalid file path"},
                    400
                )
                return

            file_path = os.path.join(
                os.path.dirname(__file__),
                "images",
                filename
            )

            self.serve_static_file(file_path)

            return

        # ----------------------------------------------------
        # MAIN PAGE
        # ----------------------------------------------------

        if path == "/":

            payload = HTML.encode("utf-8")

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )
            self.send_header(
                "Content-Length",
                str(len(payload))
            )
            self.end_headers()

            self.wfile.write(payload)

            return

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        if path == "/api/status":

            status = load_json(
                STATUS_FILE,
                {}
            )

            config = load_config()

            # The config file is the authoritative source
            # for what the user has SAVED.
            status["saved_mode"] = (
                config.get(
                    "mode",
                    "selected"
                )
            )

            status["saved_movies"] = (
                config.get(
                    "movies",
                    []
                )
            )

            status["config_updated_at"] = (
                config.get(
                    "updated_at"
                )
            )

            # Keep these for compatibility with the
            # existing UI/monitor.
            status.setdefault(
                "mode",
                config.get(
                    "mode",
                    "selected"
                )
            )

            status.setdefault(
                "selected_movies",
                config.get(
                    "movies",
                    []
                )
            )

            status.setdefault(
                "available_movies",
                []
            )

            status.setdefault(
                "showtimes",
                {}
            )
            
            status["discord_webhook_url"] = config.get(
                "discord_webhook_url",
                ""
            )

            status["imax_theatre_url"] = config.get(
                "imax_theatre_url",
                ""
            )

            self.send_json(status)

            return

        self.send_json(
            {"error": "Not found"},
            404
        )

    def do_POST(self):

        path = urlparse(
            self.path
        ).path

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            body = self.rfile.read(
                length
            )

            data = json.loads(
                body or b"{}"
            )

        except (
            ValueError,
            json.JSONDecodeError
        ):

            self.send_json(
                {"error": "Invalid JSON"},
                400
            )

            return

        # ----------------------------------------------------
        # SAVE CONFIGURATION
        # ----------------------------------------------------

        if path == "/api/config":

            mode = data.get(
                "mode"
            )

            movies = data.get(
                "movies",
                []
            )

            if mode not in {
                "all",
                "selected"
            }:

                self.send_json(
                    {"error": "Invalid mode"},
                    400
                )

                return

            if not isinstance(
                movies,
                list
            ):

                self.send_json(
                    {
                        "error":
                        "Movies must be a list"
                    },
                    400
                )

                return

            # Remove duplicates while preserving order.
            movies = list(
                dict.fromkeys(
                    str(movie)
                    for movie in movies
                )
            )

            config = save_config(
                mode,
                movies
            )

            print(
                "[WEB] Saved configuration:"
            )

            print(
                f"[WEB]   Mode: {mode}"
            )

            print(
                f"[WEB]   Movies: {movies}"
            )

            self.send_json({
                "ok": True,
                "mode": config["mode"],
                "movies": config["movies"],
                "updated_at": config["updated_at"],
            })

            return
        
        # ----------------------------------------------------
        # SAVE SETTINGS
        # ----------------------------------------------------

        if path == "/api/settings":

            discord_webhook_url = str(
                data.get(
                    "discord_webhook_url",
                    ""
                )
            ).strip()

            imax_theatre_url = str(
                data.get(
                    "imax_theatre_url",
                    ""
                )
            ).strip()

            # Basic validation
            if discord_webhook_url:
                if not (
                    discord_webhook_url.startswith(
                        "https://discord.com/api/webhooks/"
                    )
                    or
                    discord_webhook_url.startswith(
                        "https://discordapp.com/api/webhooks/"
                    )
                ):
                    self.send_json(
                        {
                            "error":
                            "Invalid Discord webhook URL"
                        },
                        400
                    )
                    return

            if not imax_theatre_url:
                self.send_json(
                    {
                        "error":
                        "IMAX theatre URL cannot be empty"
                    },
                    400
                )
                return

            if not (
                imax_theatre_url.startswith("https://")
                or
                imax_theatre_url.startswith("http://")
            ):
                self.send_json(
                    {
                        "error":
                        "Invalid IMAX theatre URL"
                    },
                    400
                )
                return

            current = load_config()

            config = save_config(
                current.get(
                    "mode",
                    "selected"
                ),
                current.get(
                    "movies",
                    []
                ),
                discord_webhook_url,
                imax_theatre_url
            )

            print("[WEB] Saved settings:")
            print(
                f"[WEB]   IMAX URL: "
                f"{imax_theatre_url}"
            )

            print(
                "[WEB]   Discord webhook: "
                f"{'configured' if discord_webhook_url else 'disabled'}"
            )

            self.send_json({
                "ok": True,
                "discord_webhook_url": (
                    config["discord_webhook_url"]
                ),
                "imax_theatre_url": (
                    config["imax_theatre_url"]
                ),
                "updated_at": (
                    config["updated_at"]
                ),
            })

            return

        # ----------------------------------------------------
        # CHECK NOW
        # ----------------------------------------------------

        if path == "/api/check-now":

            status = load_json(
                STATUS_FILE,
                {}
            )

            status["check_now"] = (
                datetime.now().isoformat()
            )

            save_json(
                STATUS_FILE,
                status
            )

            self.send_json({
                "ok": True
            })

            return

        self.send_json(
            {"error": "Not found"},
            404
        )
        



def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Lightweight web UI for "
            "the IMAX Showtime Monitor"
        )
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Web server bind address "
            "(default: 127.0.0.1)"
        )
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help=(
            "Web server port "
            "(default: 5000)"
        )
    )

    return parser.parse_args()


if __name__ == "__main__":

    args = parse_args()

    server = ThreadingHTTPServer(
        (
            args.host,
            args.port
        ),
        Handler
    )

    print()
    print("=" * 60)
    print("IMAX MONITOR WEB UI")
    print("=" * 60)
    print(
        f"Open: http://{args.host}:{args.port}"
    )
    print(
        "Press Ctrl+C to stop the web UI."
    )
    print()

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nStopping web UI..."
        )

    finally:

        server.server_close()

