#!/usr/bin/env python3
"""
Raw TCP/BSON rosbridge adapter.

The current UE test tool sends rosbridge BSON documents directly over a TCP
socket instead of using WebSocket frames. This server keeps the normal
rosbridge operations, but changes only the transport: one BSON document per
TCP frame, where the first 4 bytes are the BSON little-endian length field.
"""
from __future__ import annotations

import argparse
import json
import socket
import threading
import uuid

import bson
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_server.client_manager import ClientManager


DEFAULT_MAX_MESSAGE_SIZE = 4 * 1024 * 1024
UE_COMMAND_TOPIC = "/U2RTopic_Command"


def _json_string(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_ue_command_publish(message: dict) -> tuple[dict, bool]:
    if message.get("op") != "publish" or message.get("topic") != UE_COMMAND_TOPIC:
        return message, False

    msg = message.get("msg")
    if isinstance(msg, dict):
        normalized = dict(message)
        if set(msg.keys()) == {"data"}:
            data = msg.get("data")
            if isinstance(data, (dict, list)):
                normalized["msg"] = {"data": _json_string(data)}
                return normalized, True
            if isinstance(data, bytes):
                normalized["msg"] = {"data": data.decode("utf-8", errors="replace")}
                return normalized, True
            return message, False

        normalized["msg"] = {"data": _json_string(msg)}
        return normalized, True

    if isinstance(msg, bytes):
        normalized = dict(message)
        normalized["msg"] = {"data": msg.decode("utf-8", errors="replace")}
        return normalized, True

    return message, False


def normalize_bson_frame(frame: bytes) -> tuple[bytes, bool]:
    message = bson.BSON(frame).decode()
    normalized, changed = normalize_ue_command_publish(message)
    if not changed:
        return frame, False
    return bson.BSON.encode(normalized), True


class BsonTcpSession(threading.Thread):
    def __init__(
        self,
        node: Node,
        client_manager: ClientManager,
        sock: socket.socket,
        address,
        max_message_size: int,
    ):
        super().__init__(daemon=True)
        self.node = node
        self.client_manager = client_manager
        self.sock = sock
        self.address = address
        self.max_message_size = max_message_size
        self.client_id = uuid.uuid4()
        self._send_lock = threading.Lock()
        self.protocol: RosbridgeProtocol | None = None

    def run(self):
        peer = f"{self.address[0]}:{self.address[1]}"
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._read_loop()
        except OSError as exc:
            self.node.get_logger().warning(f"BSON TCP client error {peer}: {exc}")
        finally:
            try:
                if self.protocol is not None:
                    self.protocol.finish()
            finally:
                if self.protocol is not None:
                    self.client_manager.remove_client(self.client_id, self.address[0])
                try:
                    self.sock.close()
                except OSError:
                    pass
                if self.protocol is not None:
                    self.node.get_logger().info(f"BSON TCP client disconnected: {peer}")

    def _read_loop(self):
        buffer = b""
        while rclpy.ok():
            chunk = self.sock.recv(65536)
            if not chunk:
                return
            buffer += chunk

            while True:
                if len(buffer) < 4:
                    break

                size = int.from_bytes(buffer[:4], byteorder="little", signed=True)
                if size < 5 or size > self.max_message_size:
                    raise OSError(f"invalid BSON frame size: {size}")
                if len(buffer) < size:
                    break

                frame = buffer[:size]
                buffer = buffer[size:]
                self._ensure_protocol()
                try:
                    frame, normalized = normalize_bson_frame(frame)
                except Exception as exc:
                    self.node.get_logger().warning(
                        f"failed to inspect BSON frame from {self.address[0]}:{self.address[1]}: {exc}"
                    )
                    normalized = False
                if normalized:
                    self.node.get_logger().info(
                        f"normalized UE command publish on {UE_COMMAND_TOPIC} to std_msgs/String"
                    )
                self.protocol.incoming(frame)

    def _ensure_protocol(self):
        if self.protocol is not None:
            return
        peer = f"{self.address[0]}:{self.address[1]}"
        self.protocol = RosbridgeProtocol(
            self.client_id,
            self.node,
            parameters={
                "bson_only_mode": True,
                "max_message_size": self.max_message_size,
            },
        )
        self.protocol.outgoing = self._send_message
        self.client_manager.add_client(self.client_id, self.address[0])
        self.node.get_logger().info(f"BSON TCP client connected: {peer}")

    def _send_message(self, message, compression: str = "none"):  # noqa: ARG002
        if isinstance(message, str):
            data = message.encode("utf-8")
        else:
            data = bytes(message)
        with self._send_lock:
            self.sock.sendall(data)


class BsonTcpServer:
    def __init__(self, node: Node, host: str, port: int, max_message_size: int):
        self.node = node
        self.client_manager = ClientManager(node)
        self.host = host
        self.port = port
        self.max_message_size = max_message_size
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(64)
        self.sock.settimeout(0.5)
        self.sessions: list[BsonTcpSession] = []

    def serve_forever(self):
        self.node.get_logger().info(
            f"rosbridge BSON TCP server started on {self.host}:{self.port}"
        )
        try:
            while rclpy.ok():
                try:
                    client_sock, address = self.sock.accept()
                except TimeoutError:
                    continue
                session = BsonTcpSession(
                    self.node,
                    self.client_manager,
                    client_sock,
                    address,
                    self.max_message_size,
                )
                self.sessions.append(session)
                session.start()
        finally:
            self.close()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
        for session in self.sessions:
            try:
                session.sock.close()
            except OSError:
                pass


def _spin(node: Node):
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, Exception):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--max-message-size", type=int, default=DEFAULT_MAX_MESSAGE_SIZE)
    args = parser.parse_args()

    rclpy.init()
    node = Node("rosbridge_bson_tcp")
    spin_thread = threading.Thread(target=_spin, args=(node,), daemon=True)
    spin_thread.start()

    server = BsonTcpServer(node, args.address, args.port, args.max_message_size)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
