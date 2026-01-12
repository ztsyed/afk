#!/usr/bin/env python3
"""Test script to simulate a Claude Code hook connection"""

import json
import subprocess
import sys

try:
    import websockets.sync.client as ws_client
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
    import websockets.sync.client as ws_client

SERVER_URL = "ws://localhost:8000/ws/hook"

payload = {
    "instance_id": "test-machine-myproject-12345",
    "machine_name": "test-machine",
    "project_name": "myproject",
    "working_dir": "/Users/test/code/myproject",
    "notification": "Claude is asking: Should I proceed with refactoring the authentication module?",
    "context_tail": """I've analyzed the codebase and found several areas that could be improved:

1. The auth module uses outdated JWT validation
2. Password hashing should use bcrypt instead of sha256
3. Session management could be simplified

I can refactor these now. Do you want me to proceed?"""
}

print(f"Connecting to {SERVER_URL}...")

try:
    with ws_client.connect(SERVER_URL) as websocket:
        print("Connected! Sending session data...")
        websocket.send(json.dumps(payload))

        print("Waiting for response (check the web UI at http://localhost:5173)...")
        print("Press Ctrl+C to cancel\n")

        while True:
            message = websocket.recv()
            data = json.loads(message)
            print(f"Received: {data}")

            if data.get("type") == "registered":
                print(f"✓ Session registered with ID: {data.get('session_id')}")
            elif data.get("type") == "ping":
                websocket.send(json.dumps({"type": "pong"}))
            elif data.get("type") == "response":
                print(f"\n✓ Got response: {data.get('response')}")
                break

except KeyboardInterrupt:
    print("\nCancelled")
except Exception as e:
    print(f"Error: {e}")
