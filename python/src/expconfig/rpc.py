"""JSON-RPC 2.0 over ZMQ REQ/REP, the Instrument Framework protocol.

Same wire format as FLEX `flex.inst.base.Instrument`: one request string,
one reply string, `result` or `error: {code, message, data}`.
"""

from __future__ import annotations

import itertools
import json
import threading
from typing import Any, Callable

import zmq


class RpcError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, data: Any = None):
        super().__init__(f"[{code}] {message}" if code is not None else message)
        self.message = message
        self.code = code
        self.data = data


class Client:
    def __init__(self, address: str, timeout: float = 3.0, context: zmq.Context | None = None):
        self.address = address
        self.timeout = timeout
        self._ctx = context or zmq.Context.instance()
        self._ids = itertools.count(1)
        self._sock: zmq.Socket | None = None
        self._lock = threading.Lock()

    def _socket(self) -> zmq.Socket:
        if self._sock is None:
            s = self._ctx.socket(zmq.REQ)
            s.setsockopt(zmq.LINGER, 0)
            s.setsockopt(zmq.RCVTIMEO, int(self.timeout * 1000))
            s.setsockopt(zmq.SNDTIMEO, int(self.timeout * 1000))
            s.connect(self.address)
            self._sock = s
        return self._sock

    def _reset(self) -> None:
        if self._sock is not None:
            self._sock.close(linger=0)
            self._sock = None

    def call(self, method: str, params: Any = None) -> Any:
        request = {"jsonrpc": "2.0", "method": method, "params": {} if params is None else params,
                   "id": str(next(self._ids))}
        with self._lock:
            sock = self._socket()
            try:
                sock.send_string(json.dumps(request))
                reply = json.loads(sock.recv_string())
            except zmq.Again as err:
                self._reset()  # a REQ socket is stuck after a missed reply
                raise TimeoutError(f"{self.address}: no reply to {method} within {self.timeout} s") from err
            except Exception:
                self._reset()
                raise
        if isinstance(reply, dict) and "error" in reply:
            err = reply["error"]
            if isinstance(err, dict):
                raise RpcError(err.get("message", "instrument error"), err.get("code"), err.get("data"))
            raise RpcError(str(err))
        return reply.get("result") if isinstance(reply, dict) else reply

    def close(self) -> None:
        with self._lock:
            self._reset()


Handler = Callable[[str, Any], Any]


class Server:
    """Minimal REP server for simulated instruments. handler(method, params) -> result;
    raise RpcError to reply with an error."""

    def __init__(self, address: str, handler: Handler, context: zmq.Context | None = None):
        self.address = address
        self.handler = handler
        self._ctx = context or zmq.Context.instance()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None

    def start(self) -> "Server":
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"sim {self.address}")
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise self._error
        return self

    def _run(self) -> None:
        sock = self._ctx.socket(zmq.REP)
        sock.setsockopt(zmq.LINGER, 0)
        try:
            sock.bind(self.address)
        except zmq.ZMQError as err:
            self._error = err
            self._ready.set()
            return
        self._ready.set()
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        while not self._stop.is_set():
            if not poller.poll(100):
                continue
            raw = sock.recv_string()
            req_id = None
            try:
                req = json.loads(raw)
                req_id = req.get("id")
                reply = {"jsonrpc": "2.0", "result": self.handler(req["method"], req.get("params")), "id": req_id}
            except RpcError as err:
                error = {"code": err.code, "message": err.message}
                if err.data is not None:
                    error["data"] = err.data
                reply = {"jsonrpc": "2.0", "error": error, "id": req_id}
            except Exception as err:  # unknown method, bad params
                reply = {"jsonrpc": "2.0", "error": {"code": -32603, "message": repr(err)}, "id": req_id}
            sock.send_string(json.dumps(reply))
        sock.close(linger=0)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)
