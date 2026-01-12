#!/usr/bin/env python3
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

# Debug log file
DEBUG_LOG = "/tmp/afk-hook-debug.log"

def debug(msg):
    """Write debug message to log file"""
    with open(DEBUG_LOG, "a") as f:
        f.write(f"{msg}\n")

# Auto-install dependencies if not present
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
    """Get SSL context with proper CA certificates."""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    return ssl_context


def get_env(name, default=None):
    return os.environ.get(name, default)


def get_machine_name():
    return socket.gethostname().split('.')[0]


def get_project_name():
    cwd = os.getcwd()
    return os.path.basename(cwd)


def parse_menu_options(context):
    """
    Parse menu options from the context to build a mapping of intents to option numbers.

    Returns a dict like: {"yes": "1", "no": "2", "always": "2"}
    """
    import re

    if not context:
        return {}

    options = {}

    # Pattern to match menu options like "❯ 1. Yes" or "  2. No, cancel" or "3. Type something"
    # The ❯ indicates the currently selected option
    pattern = r'[❯\s]*(\d)\.\s*(.+?)(?:\n|$)'

    matches = re.findall(pattern, context)
    debug(f"Found menu options: {matches}")

    for num, text in matches:
        text_lower = text.lower().strip()

        # Detect "yes" options
        if text_lower.startswith('yes') or 'allow' in text_lower or 'create' in text_lower or 'proceed' in text_lower:
            if 'always' in text_lower or "don't ask" in text_lower or 'never ask' in text_lower:
                options["always"] = num
            else:
                options["yes"] = num

        # Detect "no" options
        elif text_lower.startswith('no') or 'cancel' in text_lower or 'deny' in text_lower or 'reject' in text_lower:
            options["no"] = num

        # Detect "type something" / custom input option
        elif 'type' in text_lower or 'custom' in text_lower or 'other' in text_lower:
            options["type"] = num

    debug(f"Parsed options mapping: {options}")
    return options


def parse_response_to_keys(response, context=None):
    """
    Smart detection: convert response to appropriate tmux key sequence.
    Uses context to determine correct menu option numbers when available.

    Returns a list of keys/strings to send to tmux send-keys.
    """
    response = response.strip()

    # Empty or explicit "Enter" -> just send Enter
    if not response or response.lower() == "enter":
        return ["Enter"]

    # Single digit 1-9: menu selection (no Enter needed, Claude Code responds immediately)
    if response in "123456789":
        return [response]

    # Try to parse menu options from context for smart mapping
    menu_options = parse_menu_options(context) if context else {}

    # Map yes/no/always to actual menu option numbers
    if response.lower() in ("y", "yes"):
        if "yes" in menu_options:
            debug(f"Mapped 'yes' to option {menu_options['yes']} from context")
            return [menu_options["yes"]]
        # Fallback to standard Claude Code permission prompt (1 = Yes)
        return ["1"]

    if response.lower() in ("n", "no"):
        if "no" in menu_options:
            debug(f"Mapped 'no' to option {menu_options['no']} from context")
            return [menu_options["no"]]
        # Fallback to standard Claude Code permission prompt (3 = No)
        return ["3"]

    if response.lower() in ("always", "yes always", "yes, always"):
        if "always" in menu_options:
            debug(f"Mapped 'always' to option {menu_options['always']} from context")
            return [menu_options["always"]]
        # Fallback to standard Claude Code permission prompt (2 = Yes, always)
        return ["2"]

    # Special key names (case-insensitive) -> send as tmux key
    special_keys = {
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "escape": "Escape",
        "esc": "Escape",
        "tab": "Tab",
        "space": "Space",
        "backspace": "BSpace",
    }
    if response.lower() in special_keys:
        return [special_keys[response.lower()]]

    # Arrow key sequences like "down down enter" or "down,down,enter"
    parts = response.replace(",", " ").lower().split()
    if all(p in special_keys or p == "enter" for p in parts):
        keys = []
        for p in parts:
            if p == "enter":
                keys.append("Enter")
            else:
                keys.append(special_keys[p])
        return keys

    # Otherwise: text input -> send text followed by Enter
    return [response, "Enter"]


def find_claude_tmux_pane():
    """Find a tmux pane running claude that has a permission prompt waiting."""
    if not shutil.which("tmux"):
        return None

    import re

    try:
        # List all panes with their commands
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}:#{pane_current_command}"],
            capture_output=True,
            text=True
        )

        claude_panes = []
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if ':' in line:
                    pane_id, cmd = line.split(':', 1)
                    # Look for panes running claude (command includes 'claude' or is a version like '2.1.4')
                    if 'claude' in cmd.lower() or re.match(r'^\d+\.\d+\.\d+$', cmd):
                        debug(f"Found claude pane: {pane_id} running {cmd}")
                        claude_panes.append(pane_id)

        # If we found claude panes, check which one has the permission prompt
        if claude_panes:
            for pane_id in claude_panes:
                content_result = subprocess.run(
                    ["tmux", "capture-pane", "-t", pane_id, "-p"],
                    capture_output=True,
                    text=True
                )
                if content_result.returncode == 0:
                    content = content_result.stdout
                    # Look for permission prompt markers
                    if "❯ 1." in content or "☐ Permission" in content or "Allow" in content:
                        debug(f"Found claude pane with prompt: {pane_id}")
                        return pane_id

            # If no pane has a prompt, return the last one (most recently created)
            debug(f"No pane with prompt found, using last claude pane: {claude_panes[-1]}")
            return claude_panes[-1]

        # Fallback: find a pane with Claude Code UI content
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            for pane_id in result.stdout.strip().split('\n'):
                if pane_id:
                    content_result = subprocess.run(
                        ["tmux", "capture-pane", "-t", pane_id, "-p"],
                        capture_output=True,
                        text=True
                    )
                    if content_result.returncode == 0:
                        content = content_result.stdout
                        if "Claude Code" in content or "❯" in content:
                            debug(f"Found claude pane by content: {pane_id}")
                            return pane_id

    except Exception as e:
        debug(f"Failed to find claude pane: {e}")

    return None


def get_tmux_pane():
    """Get the current tmux pane identifier."""
    tmux_pane = os.environ.get("TMUX_PANE")
    debug(f"TMUX_PANE env: {tmux_pane}")
    debug(f"TMUX env: {os.environ.get('TMUX')}")

    if not tmux_pane:
        tmux_env = os.environ.get("TMUX")
        if tmux_env:
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-p", "#{pane_id}"],
                    capture_output=True,
                    text=True
                )
                tmux_pane = result.stdout.strip()
                debug(f"Got pane from tmux display-message: {tmux_pane}")
            except Exception as e:
                debug(f"Failed to get pane: {e}")

    # If still no pane, try to find a pane running claude
    if not tmux_pane:
        tmux_pane = find_claude_tmux_pane()
        if tmux_pane:
            debug(f"Found claude pane via search: {tmux_pane}")

    return tmux_pane


def is_tmux_available():
    """Check if tmux is available and we can find a claude pane."""
    if os.environ.get("TMUX"):
        return True
    # Even if not in tmux, check if we can find a claude pane to inject into
    if shutil.which("tmux") and find_claude_tmux_pane():
        return True
    return False


def capture_tmux_pane(tmux_pane=None, lines=30):
    """Capture the current tmux pane content."""
    if not shutil.which("tmux"):
        return None

    try:
        cmd = ["tmux", "capture-pane", "-p"]
        if tmux_pane:
            cmd.extend(["-t", tmux_pane])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Get last N lines
            content = result.stdout.strip()
            content_lines = content.split('\n')
            return '\n'.join(content_lines[-lines:])
    except Exception as e:
        debug(f"Failed to capture pane: {e}")

    return None


def send_to_tmux(response, notification_type="permission_prompt", context=None):
    """Send response to the current tmux pane with smart key detection."""
    debug(f"send_to_tmux called with: {response}, notification_type: {notification_type}")

    if not shutil.which("tmux"):
        debug("tmux not found in PATH")
        return False

    tmux_pane = get_tmux_pane()
    pane_args = ["-t", tmux_pane] if tmux_pane else []

    # For permission prompts, use smart key parsing (yes→1, no→2, etc.)
    # For idle prompts (text input), just send the text as-is + Enter
    if notification_type == "permission_prompt":
        keys = parse_response_to_keys(response, context)
        debug(f"Parsed keys: {keys}")
        # Send all keys in one command
        cmd = ["tmux", "send-keys"] + pane_args + keys
        try:
            debug(f"Running: {cmd}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            debug(f"send-keys succeeded: stdout={result.stdout}, stderr={result.stderr}")
            return True
        except subprocess.CalledProcessError as e:
            debug(f"send-keys failed: {e}, stderr={e.stderr}")
            return False
    else:
        # Text input - send literal text, then Enter key separately
        # Using -l flag for literal text (no key interpretation)
        text = response.strip() if response else ""
        try:
            if text:
                # Send the text literally
                cmd = ["tmux", "send-keys"] + pane_args + ["-l", text]
                debug(f"Running (text): {cmd}")
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            # Send Enter key
            cmd = ["tmux", "send-keys"] + pane_args + ["Enter"]
            debug(f"Running (enter): {cmd}")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            debug("send-keys succeeded")
            return True
        except subprocess.CalledProcessError as e:
            debug(f"send-keys failed: {e}, stderr={e.stderr}")
            return False


def timeout_handler(signum, frame):
    debug("Timeout!")
    sys.exit(1)


def main():
    debug("=" * 50)
    debug("AFK hook started")
    debug(f"Environment: TMUX={os.environ.get('TMUX')}, TMUX_PANE={os.environ.get('TMUX_PANE')}")

    # Check if AFK is enabled
    if get_env("AFK_ENABLED", "true").lower() == "false":
        debug("AFK disabled, exiting")
        sys.exit(0)

    # Check if we can use tmux (either in tmux or can find a claude pane)
    in_tmux = is_tmux_available()
    debug(f"in_tmux (can inject): {in_tmux}")

    # Exit early if tmux injection isn't available - no point sending to AFK
    if not in_tmux:
        debug("No tmux available for injection, skipping AFK notification")
        sys.exit(0)

    # Read hook input from stdin
    try:
        stdin_data = sys.stdin.read()
        debug(f"stdin: {stdin_data[:500]}")
        hook_input = json.loads(stdin_data)
    except json.JSONDecodeError as e:
        debug(f"JSON decode error: {e}")
        sys.exit(1)

    # Get notification type (permission_prompt vs idle_prompt)
    notification_type = hook_input.get("notification_type", "")
    debug(f"notification_type: {notification_type}")

    # Get notification text
    notification = hook_input.get("message", "Claude Code is waiting for your input")
    debug(f"notification: {notification}")

    # Get session info
    machine_name = get_machine_name()
    project_name = get_project_name()
    working_dir = os.getcwd()
    instance_id = f"{machine_name}-{project_name}-{os.getpid()}"

    # Try to get context from hook input, or capture from tmux pane
    context_tail = hook_input.get("context", None)
    debug(f"Initial context_tail: {context_tail}, in_tmux: {in_tmux}")
    if not context_tail and in_tmux:
        import time
        tmux_pane = get_tmux_pane()
        debug(f"Got tmux_pane: {tmux_pane}")

        if notification_type == "permission_prompt":
            # Wait for the permission prompt to appear (max 3 seconds)
            for attempt in range(6):
                time.sleep(0.5)
                context_tail = capture_tmux_pane(tmux_pane, lines=40)
                if context_tail and ("❯ 1." in context_tail or "☐ Permission" in context_tail):
                    debug(f"Found permission prompt after {(attempt+1)*0.5}s")
                    break
                debug(f"Attempt {attempt+1}: No permission prompt yet")
        else:
            # For idle prompts, capture immediately
            time.sleep(0.3)
            context_tail = capture_tmux_pane(tmux_pane, lines=40)

        if context_tail:
            debug(f"Captured pane context ({len(context_tail)} chars): {context_tail[:200]}...")
        else:
            debug("Failed to capture pane context")

    payload = {
        "instance_id": instance_id,
        "machine_name": machine_name,
        "project_name": project_name,
        "working_dir": working_dir,
        "notification": notification,
        "notification_type": notification_type,
        "context_tail": context_tail,
        "can_inject": in_tmux
    }

    server_url = get_env("AFK_SERVER", "wss://afk.ziasyed.com/ws/hook")
    timeout = int(get_env("AFK_TIMEOUT", "3600"))

    debug(f"Connecting to {server_url}")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)

    try:
        # Use SSL context with certifi CA certificates for proper verification
        ssl_context = get_ssl_context() if server_url.startswith("wss://") else None
        with ws_client.connect(server_url, ssl=ssl_context) as websocket:
            debug("Connected to server")
            websocket.send(json.dumps(payload))
            debug("Sent payload, waiting for response...")

            while True:
                try:
                    message = websocket.recv()
                    data = json.loads(message)
                    debug(f"Received: {data}")

                    if data.get("type") == "registered":
                        debug(f"Registered with session_id: {data.get('session_id')}")
                        continue
                    elif data.get("type") == "ping":
                        websocket.send(json.dumps({"type": "pong"}))
                        debug("Sent pong")
                    elif data.get("type") == "response":
                        response = data.get("response", "")
                        debug(f"Got response: {response}")
                        signal.alarm(0)

                        if in_tmux:
                            success = send_to_tmux(response, notification_type, context_tail)
                            debug(f"send_to_tmux result: {success}")
                            if success:
                                sys.exit(0)

                        print(response)
                        debug("Printed response to stdout")
                        sys.exit(0)

                except Exception as e:
                    debug(f"Loop exception: {e}")
                    break

    except KeyboardInterrupt:
        debug("Interrupted")
        sys.exit(130)
    except Exception as e:
        debug(f"Connection error: {e}")
        print(f"AFK connection error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
