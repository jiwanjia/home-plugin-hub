"""Single-process Home Plugin Hub served over a Windows Named Pipe."""

import argparse
import signal
import threading
from multiprocessing.connection import Client as PipeClient
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Optional

from .client import DEFAULT_MANIFEST, HubClient
from .core import PluginHub
from .manifest import HubManifest, load_manifest
from .request_router import HubRequestRouter


class HubAlreadyRunningError(RuntimeError):
    """Raised when the configured pipe already belongs to a live Hub."""


class HubDaemon:
    """Own the only live PluginHub catalog and serve local requests."""

    def __init__(self, manifest_path: Path):
        self._manifest_path = Path(manifest_path)
        self._manifest: Optional[HubManifest] = None
        self._hub: Optional[PluginHub] = None
        self._router: Optional[HubRequestRouter] = None
        self._listener = None
        self._serve_error: Optional[Exception] = None
        self._stop_requested = threading.Event()

    @property
    def pipe_name(self) -> str:
        if self._manifest is None:
            raise RuntimeError("Hub daemon 尚未加载配置")
        return self._manifest.pipe_name

    def serve_forever(self) -> None:
        """Start the sole catalog and serve requests until asked to stop."""
        self._manifest = load_manifest(self._manifest_path)
        self._refuse_second_instance()

        self._hub = PluginHub(self._manifest_path)
        self._hub.start()
        self._router = HubRequestRouter(
            self._hub,
            self.pipe_name,
        )

        try:
            self._listener = Listener(
                self.pipe_name,
                family="AF_PIPE",
                authkey=None,
            )
            serve_thread = threading.Thread(
                target=self._serve_connections,
                name="home-plugin-hub-pipe",
                daemon=True,
            )
            serve_thread.start()

            self._stop_requested.wait()
            serve_thread.join(timeout=5)
            if serve_thread.is_alive():
                raise RuntimeError("Hub Named Pipe 服务线程未能停止")
            if self._serve_error is not None:
                raise self._serve_error
        finally:
            self.close()

    def request_stop(self) -> None:
        """Signal a graceful exit and unblock the current accept call."""
        self._stop_requested.set()
        self._wake_listener()

    def _wake_listener(self) -> None:
        if self._listener is None:
            return

        try:
            wakeup = PipeClient(
                self.pipe_name,
                family="AF_PIPE",
                authkey=None,
            )
        except OSError:
            return
        wakeup.close()

    def close(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

        hub = self._hub
        self._hub = None
        self._router = None
        if hub is not None:
            hub.close()

    def _refuse_second_instance(self) -> None:
        client = HubClient(self.pipe_name)
        if client.ping():
            raise HubAlreadyRunningError(
                f"Home Plugin Hub 已在运行: {self.pipe_name}"
            )

    def _serve_connections(self) -> None:
        try:
            while not self._stop_requested.is_set():
                self._serve_one_connection()
        except Exception as exc:
            if not self._stop_requested.is_set():
                self._serve_error = exc
        finally:
            self._stop_requested.set()

    def _serve_one_connection(self) -> None:
        try:
            connection = self._listener.accept()
        except (OSError, EOFError):
            if self._stop_requested.is_set():
                return
            raise

        try:
            raw_request = connection.recv_bytes()
            response = self._router.dispatch_encoded(raw_request)
            connection.send_bytes(response)
        except (EOFError, OSError):
            return
        finally:
            connection.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local Home Plugin Hub",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to the single plugins.yaml manifest",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    daemon = HubDaemon(args.manifest)

    def stop_handler(signum, frame):
        del signum
        del frame
        daemon.request_stop()

    signal.signal(signal.SIGINT, stop_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop_handler)

    try:
        daemon.serve_forever()
    except HubAlreadyRunningError as exc:
        print(str(exc))
        return 2
    except KeyboardInterrupt:
        daemon.request_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
