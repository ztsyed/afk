"""
AFK (ClaudeusInterruptus) - Mobile approval gateway for Claude Code
FastAPI server with WebSocket hub for real-time communication
"""

import os
import json
import uuid
import asyncio
from datetime import datetime
from enum import Enum
from typing import Optional
from contextlib import asynccontextmanager

import httpx
import aiosqlite
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./afk.db")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "zs_afk")
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
AFK_BASE_URL = os.getenv("AFK_BASE_URL", "https://afk.ziasyed.com")
DB_PATH = DATABASE_URL.replace("sqlite:///", "")


class SessionStatus(str, Enum):
    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    DISCONNECTED = "disconnected"


class SessionCreate(BaseModel):
    instance_id: str
    machine_name: str
    project_name: str
    working_dir: str
    notification: str
    notification_type: Optional[str] = "permission_prompt"
    context_tail: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    instance_id: str
    machine_name: str
    project_name: str
    working_dir: str
    notification: str
    notification_type: Optional[str]
    context_tail: Optional[str]
    status: str
    created_at: str
    responded_at: Optional[str]
    response: Optional[str]


class ResponseMessage(BaseModel):
    session_id: str
    response: str


class ConnectionManager:
    def __init__(self):
        self.hook_connections: dict[str, WebSocket] = {}
        self.ui_connections: list[WebSocket] = []

    async def connect_hook(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.hook_connections[session_id] = websocket

    def disconnect_hook(self, session_id: str):
        self.hook_connections.pop(session_id, None)

    async def connect_ui(self, websocket: WebSocket):
        await websocket.accept()
        self.ui_connections.append(websocket)

    def disconnect_ui(self, websocket: WebSocket):
        if websocket in self.ui_connections:
            self.ui_connections.remove(websocket)

    async def send_to_hook(self, session_id: str, message: str) -> bool:
        websocket = self.hook_connections.get(session_id)
        if websocket:
            try:
                await websocket.send_text(message)
                return True
            except Exception:
                return False
        return False

    async def broadcast_to_ui(self, message: dict):
        dead_connections = []
        for websocket in self.ui_connections:
            try:
                await websocket.send_json(message)
            except Exception:
                dead_connections.append(websocket)
        for ws in dead_connections:
            self.disconnect_ui(ws)


manager = ConnectionManager()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                instance_id TEXT NOT NULL,
                machine_name TEXT NOT NULL,
                project_name TEXT NOT NULL,
                working_dir TEXT NOT NULL,
                notification TEXT NOT NULL,
                notification_type TEXT DEFAULT 'permission_prompt',
                context_tail TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT,
                response TEXT
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_status ON sessions(status)")
        # Add notification_type column if it doesn't exist (migration for existing DBs)
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN notification_type TEXT DEFAULT 'permission_prompt'")
        except Exception:
            pass  # Column already exists
        await db.commit()


async def create_session(session: SessionCreate) -> str:
    session_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sessions (id, instance_id, machine_name, project_name,
                                  working_dir, notification, notification_type, context_tail, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, session.instance_id, session.machine_name, session.project_name,
             session.working_dir, session.notification, session.notification_type, session.context_tail,
             SessionStatus.PENDING.value, created_at)
        )
        await db.commit()
    return session_id


async def get_session(session_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        if row:
            return dict(row)
    return None


async def get_sessions(status: Optional[str] = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            cursor = await db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_session_status(session_id: str, status: SessionStatus, response: Optional[str] = None):
    responded_at = datetime.utcnow().isoformat() if response else None
    async with aiosqlite.connect(DB_PATH) as db:
        if response:
            await db.execute(
                "UPDATE sessions SET status = ?, response = ?, responded_at = ? WHERE id = ?",
                (status.value, response, responded_at, session_id)
            )
        else:
            await db.execute(
                "UPDATE sessions SET status = ? WHERE id = ?",
                (status.value, session_id)
            )
        await db.commit()


async def send_push_notification(session: SessionCreate, session_id: str):
    try:
        # Determine icon based on notification type
        is_permission = session.notification_type == "permission_prompt"
        tag = "lock" if is_permission else "speech_balloon"
        emoji = "🔐" if is_permission else "💬"

        # Build notification
        title = f"{emoji} {session.machine_name}/{session.project_name}"
        message = session.notification

        # Add context preview if available
        if session.context_tail:
            # Get last few lines of context
            context_lines = session.context_tail.strip().split('\n')[-3:]
            context_preview = '\n'.join(context_lines)
            if len(context_preview) > 200:
                context_preview = context_preview[:200] + "..."
            message = f"{session.notification}\n\n{context_preview}"

        # Use JSON API for proper UTF-8 support
        payload = {
            "topic": NTFY_TOPIC,
            "title": title,
            "message": message,
            "priority": 5,  # urgent
            "tags": [tag],
            "click": AFK_BASE_URL,
            "actions": [
                {
                    "action": "view",
                    "label": "Open AFK",
                    "url": AFK_BASE_URL,
                    "clear": True
                }
            ]
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{NTFY_SERVER}",
                json=payload
            )
            resp.raise_for_status()
        print(f"[NTFY] Sent notification for session {session_id}")
    except Exception as e:
        print(f"[NTFY] Failed to send push notification: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="AFK - Claude Code Mobile Gateway", lifespan=lifespan)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/logs")
async def stream_logs(lines: int = 100):
    """Return recent log entries (from stdout captured by the container)."""
    # Get connection stats
    stats = {
        "timestamp": datetime.utcnow().isoformat(),
        "hook_connections": len(manager.hook_connections),
        "ui_connections": len(manager.ui_connections),
        "hook_session_ids": list(manager.hook_connections.keys()),
    }

    # Get recent sessions for debugging
    sessions = await get_sessions()
    recent_sessions = sessions[:lines] if sessions else []

    return {
        "stats": stats,
        "recent_sessions": recent_sessions
    }


@app.get("/hook/afk.py")
async def get_hook_script():
    """Serve the AFK hook script for easy installation."""
    hook_script = '''#!/usr/bin/env python3
"""
AFK Hook for Claude Code
Sends notifications to AFK server when Claude Code needs input.
Uses tmux to inject responses back into the terminal.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys

DEBUG_LOG = "/tmp/afk-hook-debug.log"

def debug(msg):
    with open(DEBUG_LOG, "a") as f:
        f.write(f"{msg}\\n")

try:
    import websockets.sync.client as ws_client
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
    import websockets.sync.client as ws_client

try:
    import certifi
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "certifi", "-q"])
    import certifi

import ssl

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(certifi.where())
    return ctx


def get_env(name, default=None):
    return os.environ.get(name, default)


def get_machine_name():
    return socket.gethostname().split('.')[0]


def get_project_name():
    return os.path.basename(os.getcwd())


def parse_response_to_keys(response):
    response = response.strip()
    if not response or response.lower() == "enter":
        return ["Enter"]
    if response in "123456789":
        return [response]
    if response.lower() in ("y", "yes"):
        return ["1"]
    if response.lower() in ("n", "no"):
        return ["2"]
    special_keys = {
        "up": "Up", "down": "Down", "left": "Left", "right": "Right",
        "escape": "Escape", "esc": "Escape", "tab": "Tab",
        "space": "Space", "backspace": "BSpace",
    }
    if response.lower() in special_keys:
        return [special_keys[response.lower()]]
    parts = response.replace(",", " ").lower().split()
    if all(p in special_keys or p == "enter" for p in parts):
        return [special_keys.get(p, "Enter") for p in parts]
    return [response, "Enter"]


def get_tmux_pane():
    tmux_pane = os.environ.get("TMUX_PANE")
    if not tmux_pane and os.environ.get("TMUX"):
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#{pane_id}"],
                capture_output=True, text=True
            )
            tmux_pane = result.stdout.strip()
        except Exception:
            pass
    return tmux_pane


def capture_tmux_pane(tmux_pane=None, lines=30):
    if not shutil.which("tmux"):
        return None
    try:
        cmd = ["tmux", "capture-pane", "-p"]
        if tmux_pane:
            cmd.extend(["-t", tmux_pane])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            content_lines = result.stdout.strip().split('\\n')
            return '\\n'.join(content_lines[-lines:])
    except Exception:
        pass
    return None


def send_to_tmux(response):
    if not shutil.which("tmux"):
        return False
    keys = parse_response_to_keys(response)
    tmux_pane = get_tmux_pane()
    cmd = ["tmux", "send-keys"] + (["-t", tmux_pane] if tmux_pane else []) + keys
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def timeout_handler(signum, frame):
    sys.exit(1)


def main():
    if get_env("AFK_ENABLED", "true").lower() == "false":
        sys.exit(0)

    in_tmux = os.environ.get("TMUX") is not None

    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(1)

    notification = hook_input.get("message", "Claude Code is waiting for your input")
    machine_name = get_machine_name()
    project_name = get_project_name()
    instance_id = f"{machine_name}-{project_name}-{os.getpid()}"

    context_tail = hook_input.get("context", None)
    if not context_tail and in_tmux:
        import time
        tmux_pane = get_tmux_pane()
        for _ in range(6):
            time.sleep(0.5)
            context_tail = capture_tmux_pane(tmux_pane, lines=40)
            if context_tail and ("❯ 1." in context_tail or "☐ Permission" in context_tail):
                break

    payload = {
        "instance_id": instance_id,
        "machine_name": machine_name,
        "project_name": project_name,
        "working_dir": os.getcwd(),
        "notification": notification,
        "context_tail": context_tail,
        "can_inject": in_tmux
    }

    server_url = get_env("AFK_SERVER", "wss://afk.ziasyed.com/ws/hook")
    timeout = int(get_env("AFK_TIMEOUT", "3600"))

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)

    try:
        ssl_ctx = get_ssl_context() if server_url.startswith("wss://") else None
        with ws_client.connect(server_url, ssl=ssl_ctx) as websocket:
            websocket.send(json.dumps(payload))
            while True:
                try:
                    message = websocket.recv()
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        websocket.send(json.dumps({"type": "pong"}))
                    elif data.get("type") == "response":
                        response = data.get("response", "")
                        signal.alarm(0)
                        if in_tmux and send_to_tmux(response):
                            sys.exit(0)
                        print(response)
                        sys.exit(0)
                except Exception:
                    break
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"AFK connection error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
'''
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=hook_script, media_type="text/x-python")


@app.get("/api/sessions")
async def list_sessions(status: Optional[str] = None):
    sessions = await get_sessions(status)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.websocket("/ws/hook")
async def websocket_hook(websocket: WebSocket):
    session_id = None
    try:
        await websocket.accept()
        print(f"[Hook] New connection")
        data = await websocket.receive_text()
        payload = json.loads(data)
        print(f"[Hook] Received payload from {payload.get('machine_name')}/{payload.get('project_name')}")

        session_data = SessionCreate(**payload)
        session_id = await create_session(session_data)
        print(f"[Hook] Created session: {session_id}")

        manager.hook_connections[session_id] = websocket
        print(f"[Hook] Stored connection. Total hooks: {len(manager.hook_connections)}")

        await send_push_notification(session_data, session_id)

        session = await get_session(session_id)
        await manager.broadcast_to_ui({
            "type": "new_session",
            "session": session
        })

        await websocket.send_json({"type": "registered", "session_id": session_id})

        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                data = json.loads(message)
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Hook WebSocket error: {e}")
    finally:
        if session_id:
            manager.disconnect_hook(session_id)
            session = await get_session(session_id)
            if session and session["status"] == SessionStatus.PENDING.value:
                await update_session_status(session_id, SessionStatus.DISCONNECTED)
                await manager.broadcast_to_ui({
                    "type": "session_disconnected",
                    "session_id": session_id
                })


@app.websocket("/ws/ui")
async def websocket_ui(websocket: WebSocket):
    await manager.connect_ui(websocket)
    print(f"[UI] Connected. Total UI connections: {len(manager.ui_connections)}")
    try:
        sessions = await get_sessions(SessionStatus.PENDING.value)
        await websocket.send_json({
            "type": "init",
            "sessions": sessions
        })
        print(f"[UI] Sent {len(sessions)} pending sessions")

        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                data = json.loads(message)
                print(f"[UI] Received: {data.get('type')}")

                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                elif data.get("type") == "respond":
                    session_id = data.get("session_id")
                    response_text = data.get("response")
                    print(f"[UI] Respond request: session={session_id}, response={response_text}")
                    print(f"[UI] Hook connections: {list(manager.hook_connections.keys())}")

                    if session_id and response_text is not None:
                        sent = await manager.send_to_hook(session_id, json.dumps({
                            "type": "response",
                            "response": response_text
                        }))
                        print(f"[UI] send_to_hook result: {sent}")

                        if sent:
                            await update_session_status(session_id, SessionStatus.RESPONDED, response_text)
                            await manager.broadcast_to_ui({
                                "type": "session_responded",
                                "session_id": session_id,
                                "response": response_text
                            })
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Hook connection not found or closed"
                            })

                elif data.get("type") == "dismiss":
                    session_id = data.get("session_id")
                    print(f"[UI] Dismiss request: session={session_id}")

                    if session_id:
                        # Update session status to dismissed
                        await update_session_status(session_id, SessionStatus.DISCONNECTED)
                        # Disconnect the hook if still connected
                        manager.disconnect_hook(session_id)
                        # Broadcast to all UI clients
                        await manager.broadcast_to_ui({
                            "type": "session_dismissed",
                            "session_id": session_id
                        })

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"UI WebSocket error: {e}")
    finally:
        manager.disconnect_ui(websocket)


static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_path, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(static_path, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(static_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
