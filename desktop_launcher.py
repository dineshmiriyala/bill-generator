import os, sys, socket, threading, time, webbrowser
from contextlib import closing
from waitress import serve

# ✅ set flags BEFORE importing app
os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("BG_DESKTOP", "1")

from app import app


def find_free_port():
    """Find a free localhost port dynamically."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server(port: int):
    serve(app, host="127.0.0.1", port=port, threads=8)


def main():
    port = find_free_port()
    t = threading.Thread(target=run_server, args=(port,), daemon=True)
    t.start()

    url = f"http://127.0.0.1:{port}/"

    try:
        import webview
        webview.create_window(
            title="SLO BILL",
            url=url,
            width=1200, height=840,
            min_size=(1024, 720),
            confirm_close=True,
        )
        webview.start()
    except ImportError:
        webbrowser.open(url)
        try:
            while t.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    sys.exit(main())