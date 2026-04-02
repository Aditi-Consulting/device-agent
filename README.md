# Device Agent

A LangGraph-based Python agent that automates the device unlock workflow:

```
User supplies IMEI
      │
      ▼
┌─────────────────────┐
│  check_eligibility  │  POST /device/check-eligibility
└──────────┬──────────┘
           │
     eligible?
     /          \
   No            Yes
   │              │
   ▼              ▼
 [END]   ┌──────────────┐
         │ unlock_device│  POST /device/unlock-device
         └──────┬───────┘
                │
              [END]
```

---

## Project Structure

```
device-agent/
├── src/
│   └── device_agent/
│       ├── __init__.py      # Package entry
│       ├── config.py        # Settings (env-driven)
│       ├── state.py         # LangGraph AgentState
│       ├── api_client.py    # HTTP client for Device API
│       ├── nodes.py         # Graph node implementations
│       └── agent.py         # Graph construction & routing
├── main.py                  # CLI entry point
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quick Start

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

Edit `.env` as required (defaults point to `http://127.0.0.1:8000`).

### 4. Run the agent

**Interactive prompt:**
```bash
python main.py
```

**Pass IMEI as argument:**
```bash
python main.py 1234567890123456
```

---

## Environment Variables

| Variable               | Default                   | Description                        |
|------------------------|---------------------------|------------------------------------|
| `DEVICE_API_BASE_URL`  | `http://127.0.0.1:8000`   | Base URL of the Device API         |
| `DEVICE_API_TIMEOUT`   | `10`                      | Request timeout in seconds         |
| `LOG_LEVEL`            | `INFO`                    | Python logging level               |

---

## API Endpoints Expected

| Method | Path                          | Body              | Response                   |
|--------|-------------------------------|-------------------|----------------------------|
| POST   | `/device/check-eligibility`   | `{"imei": "..."}` | `{"eligible": true/false}` |
| POST   | `/device/unlock-device`       | `{"imei": "..."}` | `{"status": "..."}`        |

---

## Exit Codes

| Code | Meaning                               |
|------|---------------------------------------|
| `0`  | Success                               |
| `1`  | Invalid IMEI format supplied          |
| `2`  | API error occurred during workflow    |
