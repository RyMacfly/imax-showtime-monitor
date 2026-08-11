#!/bin/bash

set -e

echo "=========================================="
echo "      IMAX Showtime Monitor"
echo "=========================================="
echo

echo "Installing Python dependencies..."
python -m pip install -r requirements.txt

echo
echo "Checking Playwright browser..."
python -m playwright install chromium

echo
echo "Starting IMAX monitor..."
python imax_monitor.py --all &
MONITOR_PID=$!

echo "Starting web UI..."
python imax_monitor_web.py &
WEB_PID=$!

echo
echo "Monitor PID: $MONITOR_PID"
echo "Web UI PID:  $WEB_PID"
echo
echo "Both services are running."
echo "Press Ctrl+C to stop both."
echo

cleanup() {
    echo
    echo "Stopping services..."

    # Stop monitor
    if kill -0 "$MONITOR_PID" 2>/dev/null; then
        kill "$MONITOR_PID" 2>/dev/null || true
    fi

    # Stop web UI
    if kill -0 "$WEB_PID" 2>/dev/null; then
        kill "$WEB_PID" 2>/dev/null || true
    fi

    # Wait for both processes to actually exit.
    # Ignore their exit codes because we're intentionally stopping them.
    wait "$MONITOR_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true

    echo "Both services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for either process.
# Don't let set -e treat a terminated child as an error.
while true; do
    if ! kill -0 "$MONITOR_PID" 2>/dev/null; then
        echo
        echo "IMAX monitor exited."
        cleanup
    fi

    if ! kill -0 "$WEB_PID" 2>/dev/null; then
        echo
        echo "Web UI exited."
        cleanup
    fi

    sleep 1
done