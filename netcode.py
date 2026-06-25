"""Tiny host/client networking over TCP for a 2-player game.

Model: the HOST runs the authoritative simulation. The CLIENT just sends its
input each frame and renders the snapshots the host sends back. That keeps the
two machines perfectly in sync with almost no code.

Messages are newline-delimited JSON:
    host -> client:  {"t": "init",  "seed": <int>, "you": 1}
    host -> client:  {"t": "state", "data": <snapshot>}
    client -> host:  {"t": "input", "data": <input dict>}
"""

import json
import random
import socket
import threading
import time

PORT = 50713


def _send(sock, obj):
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def _messages(sock):
    """Yield parsed JSON objects from a socket until it closes."""
    buf = b""
    while True:
        try:
            chunk = sock.recv(4096)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass


def local_ips():
    """Best-effort list of this machine's IPv4 addresses (for the host screen)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


class Server:
    """The host. Listens for one client, then exchanges input/state."""

    def __init__(self):
        self.seed = random.randrange(1, 1_000_000)
        self.connected = False
        self.error = None
        self._listen = None
        self._conn = None
        self._input = {"left": False, "right": False, "up": False, "down": False, "fire": False}
        self._lock = threading.Lock()
        self._craters_sent = 0   # how many craters the client already has

    def start_listening(self):
        self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen.bind(("0.0.0.0", PORT))
        self._listen.listen(1)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        try:
            conn, _addr = self._listen.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._conn = conn
            _send(conn, {"t": "init", "seed": self.seed, "you": 1})
            self.connected = True
            threading.Thread(target=self._recv_loop, daemon=True).start()
        except OSError as e:
            self.error = str(e)

    def _recv_loop(self):
        for msg in _messages(self._conn):
            if msg.get("t") == "input":
                with self._lock:
                    self._input = msg.get("data", self._input)
        self.connected = False

    def get_input(self):
        with self._lock:
            return dict(self._input)

    def send_state(self, snapshot):
        if not self.connected or self._conn is None:
            return
        # Send only craters the client doesn't have yet (it accumulates them).
        # Copy the dict so the host's own full snapshot stays intact for its FX.
        craters = snapshot.get("craters", [])
        data = dict(snapshot)
        data["craters"] = craters[self._craters_sent:]
        try:
            _send(self._conn, {"t": "state", "data": data})
            self._craters_sent = len(craters)
        except OSError:
            self.connected = False

    def close(self):
        self.connected = False
        for s in (self._conn, self._listen):
            try:
                if s:
                    s.close()
            except OSError:
                pass


class Client:
    """The joiner. Connects to a host, receives the seed, then plays."""

    def __init__(self):
        self.connected = False
        self.error = None
        self.seed = None
        self.index = 1
        self._sock = None
        self._state = None
        self._all_craters = []   # rebuilt from per-message crater deltas
        self._lock = threading.Lock()

    def connect(self, host, port=PORT, timeout=6.0):
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout)
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock.settimeout(None)
        except OSError as e:
            self.error = str(e)
            return False
        self.connected = True
        threading.Thread(target=self._recv_loop, daemon=True).start()

        waited = 0.0
        while self.seed is None and self.connected and waited < 5.0:
            time.sleep(0.05)
            waited += 0.05
        if self.seed is None:
            self.error = self.error or "Host did not send a game start."
            return False
        return True

    def _recv_loop(self):
        for msg in _messages(self._sock):
            t = msg.get("t")
            if t == "init":
                self.seed = msg.get("seed")
                self.index = msg.get("you", 1)
            elif t == "state":
                data = msg.get("data")
                if data is not None:
                    # accumulate crater deltas back into the full list (every
                    # message is seen here even if render skips some frames)
                    self._all_craters.extend(data.get("craters", []))
                    data["craters"] = list(self._all_craters)
                    with self._lock:
                        self._state = data
        self.connected = False

    def send_input(self, inp):
        if not self.connected or self._sock is None:
            return
        try:
            _send(self._sock, {"t": "input", "data": inp})
        except OSError:
            self.connected = False

    def get_state(self):
        with self._lock:
            return self._state

    def close(self):
        self.connected = False
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
