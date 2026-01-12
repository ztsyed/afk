# AFK - Away From Keyboard

**Zero-latency notifications for high-latency humans**

A mobile approval gateway for Claude Code.

In the age of agentic coding with Claude Code, running multiple agents simultaneously across different projects has become the norm. But there's a bottleneck: **you**. When three agents need approval at once and you're grabbing coffee, making lunch, or just stepped away from your desk, everything grinds to a halt.

AFK solves this by letting you respond to Claude Code prompts from your phone. Get push notifications when agents need input, tap to approve/deny, and keep your autonomous coding sessions running—even when you're not at your keyboard.

## How It Works

```
Claude Code (in tmux)
        ↓
   Hook triggered when Claude needs input
        ↓
   Notification sent to your phone via ntfy
        ↓
   You tap the notification → PWA opens
        ↓
   Select response (Yes/No/Custom)
        ↓
   Response injected back into tmux → Claude continues
```

The system uses WebSockets for real-time bidirectional communication between your Claude Code instances and the mobile web app. Multiple agents across different projects can all funnel through a single AFK server.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       AFK Server                            │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   FastAPI    │  │   WebSocket  │  │      SQLite      │  │
│  │   + React    │  │     Hub      │  │     Database     │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │  ntfy   │         │   Web   │         │  Hook   │
   │  Push   │         │   UI    │         │ Script  │
   └────┬────┘         └────┬────┘         └────┬────┘
        │                   │                   │
        ▼                   ▼                   ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │  Phone  │────────▶│ Browser │         │ Claude  │
   │   App   │  tap    │  (PWA)  │         │  Code   │
   └─────────┘         └─────────┘         └─────────┘
```

## Prerequisites

- A Kubernetes cluster (k3s, EKS, GKE, etc.)
- An ingress controller (Traefik or nginx-ingress)
- A domain with DNS pointing to your cluster
- The [ntfy](https://ntfy.sh) app on your phone
- Claude Code running inside tmux (for response injection)

## Deploying to Kubernetes

### 1. Clone and Configure

```bash
git clone https://github.com/YOUR_USERNAME/afk.git
cd afk
```

### 2. Choose Your ntfy Topic

Choose a **secret, random topic name** for your ntfy notifications. This acts as your authentication—anyone with the topic name can see your notifications.

```bash
# Generate a random topic
echo "afk-$(openssl rand -hex 8)"
# Example output: afk-3a7f2c9b1e4d8a6f
```

### 3. Deploy Using Raw Manifests

Edit the deployment to set your domain and ntfy topic:

```bash
# Edit k8s/deployment.yaml
# - Change afk.ziasyed.com to your domain in the Ingress
# - Update NTFY_TOPIC in the Secret
```

Apply the manifests:

```bash
kubectl apply -f k8s/deployment.yaml
```

### 4. Deploy Using Helm (Alternative)

```bash
cd k8s/helm/afk

# Create your values override
cat > my-values.yaml <<EOF
ingress:
  enabled: true
  className: traefik  # or nginx
  host: afk.yourdomain.com
  tls:
    enabled: true

config:
  ntfyTopic: "afk-YOUR-RANDOM-STRING"
  ntfyServer: "https://ntfy.sh"
EOF

# Install
helm install afk . -n afk --create-namespace -f my-values.yaml
```

### 5. Verify Deployment

```bash
# Check pods
kubectl get pods -n afk

# Check ingress
kubectl get ingress -n afk

# Test health endpoint
curl https://afk.yourdomain.com/api/health
```

## Setting Up Your Phone

1. Install the ntfy app:
   - [Android (Play Store)](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
   - [iOS (App Store)](https://apps.apple.com/app/ntfy/id1625396347)

2. Subscribe to your topic name (the same one you configured in the deployment)

3. Test it works:
   ```bash
   curl -d "AFK is working!" ntfy.sh/YOUR-TOPIC-NAME
   ```

## Installing the Hook

The hook script integrates with Claude Code's notification system. Install it on each machine where you run Claude Code.

### 1. Download the Hook

```bash
mkdir -p ~/.claude/hooks
curl -o ~/.claude/hooks/afk.py https://afk.yourdomain.com/hook/afk.py
chmod +x ~/.claude/hooks/afk.py
```

Or copy from the repo:

```bash
cp hook/afk.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/afk.py
```

### 2. Configure Claude Code

Add the hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/afk.py"
          }
        ]
      }
    ]
  }
}
```

### 3. Set Environment Variables

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
export AFK_SERVER="wss://afk.yourdomain.com/ws/hook"
export AFK_ENABLED="true"
export AFK_TIMEOUT="3600"  # 1 hour timeout
```

Reload your shell:
```bash
source ~/.zshrc  # or ~/.bashrc
```

## Usage

1. **Start Claude Code in tmux** (required for response injection):
   ```bash
   tmux new -s claude
   claude
   ```

2. **Work normally**. When Claude needs permission or input, you'll get a push notification.

3. **Respond from anywhere**:
   - Tap the notification to open the web UI
   - See the pending request with terminal context
   - Tap a quick response or type a custom one
   - Claude continues automatically

## Response Types

The hook supports smart response parsing:

| You Type | Claude Receives |
|----------|-----------------|
| `yes` or `y` | Menu option 1 (typically "Yes") |
| `no` or `n` | Menu option 2 (typically "No") |
| `1`, `2`, `3`... | Corresponding menu option |
| Custom text | Typed directly as input |

## Configuration Reference

### Server Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./afk.db` | SQLite database path |
| `NTFY_TOPIC` | `afk-claude-alerts` | Your secret ntfy topic |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy server URL |

### Hook Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AFK_SERVER` | `wss://afk.ziasyed.com/ws/hook` | Your AFK server WebSocket URL |
| `AFK_ENABLED` | `true` | Set to `false` to disable |
| `AFK_TIMEOUT` | `3600` | Response timeout in seconds |

## Local Development

```bash
# Terminal 1: Server
cd server
pip install -r requirements.txt
python main.py

# Terminal 2: Frontend (with hot reload)
cd web
npm install
npm run dev

# Terminal 3: Test the hook
python test_hook.py
```

Open http://localhost:5173 for the frontend dev server.

## Building for Production

```bash
# Build frontend
cd web && npm run build

# Build Docker image
./scripts/build.sh

# Or manually
docker build -t ghcr.io/YOUR_USERNAME/afk:latest .
docker push ghcr.io/YOUR_USERNAME/afk:latest
```

## Debugging

Check the hook debug log:
```bash
tail -f /tmp/afk-hook-debug.log
```

Check server logs:
```bash
kubectl logs -n afk -l app=afk -f
```

View API endpoints:
```bash
curl https://afk.yourdomain.com/api/health
curl https://afk.yourdomain.com/api/sessions | jq
curl https://afk.yourdomain.com/api/logs | jq
```

## Project Structure

```
afk/
├── server/
│   ├── main.py              # FastAPI server with WebSocket hub
│   └── requirements.txt     # Python dependencies
├── web/
│   ├── src/
│   │   ├── App.jsx          # Main React component
│   │   ├── main.jsx         # Entry point
│   │   └── index.css        # Tailwind styles
│   ├── public/
│   │   ├── manifest.json    # PWA manifest
│   │   └── favicon.svg
│   ├── vite.config.js
│   └── tailwind.config.js
├── hook/
│   ├── afk.py               # Claude Code hook script
│   └── settings-example.json
├── k8s/
│   ├── deployment.yaml      # Raw K8s manifests
│   └── helm/afk/            # Helm chart
├── scripts/
│   ├── build.sh             # Docker build
│   └── deploy.sh            # Helm deployment
├── Dockerfile               # Multi-stage build
└── docker-compose.yml       # Local dev
```

## Security Notes

- **ntfy topic is your auth**: Keep it secret. Anyone with the topic can see your notifications.
- **WebSocket connections are outbound-only**: Works behind corporate firewalls.
- **No credentials stored**: The hook doesn't store API keys or tokens.
- **Runs as non-root**: Container uses UID 1000.
- **TLS required**: Always use `wss://` for the WebSocket connection in production.

## Why "AFK"?

Because the whole point is that you *can* be away from your keyboard and still keep your agents productive. Go touch grass. Get coffee. Take that meeting. Your Claude Code agents will ping you when they need you.

---

*Built for developers who run more agents than they have attention spans.*
