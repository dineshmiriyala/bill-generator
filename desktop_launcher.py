import os, sys, socket, threading, time, webbrowser
from contextlib import closing
from waitress import serve

# Set flags BEFORE importing app
os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("BG_DESKTOP", "1")

from app import app, APP_PORT

HOST = "0.0.0.0"
PORT = APP_PORT


def _port_available(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def run_server(port: int):
    serve(app, host=HOST, port=port, threads=8)


def main():
    port = PORT
    if not _port_available(HOST, port):
        print(f"Port {port} is already in use. Close the other SLO BILL instance and try again.")
        return 1
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
