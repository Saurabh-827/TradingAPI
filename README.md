# Trading API (FastAPI + Angel One)

This is a robust trading backend built with **FastAPI**. It automates interactions with the **Angel One** broker platform, featuring real-time WebSocket streaming, a "Fake Spike" filter logic for Target/SL monitoring, and position tracking.

## 🚀 Key Features

- **Auto-Caching Scrip Master:** Automatically caches the Angel One Scrip Master JSON daily to ensure fast search performance.
- **WebSocket Streaming:** Provides live market price data streaming.
- **Fake Spike Filter:** Implements a 2.5-second "price sustainability" check when the Target or Stop Loss is hit, preventing premature exits from fake market spikes.
- **Position Tracking:** Fetches and tracks live open positions.
- **Authentication:** Supports automated TOTP-based login.

## 🛠 Tech Stack

- **Framework:** FastAPI
- **Broker API:** SmartApi (Angel One)
- **Data Handling:** Pydantic, JSON
- **Concurrency:** Threading (for WebSocket streams)

## 📋 Environment Variables (.env)

Create a `.env` file in the project root directory and add the following variables:

```env
ANGEL_API_KEY=your_api_key_here
ANGEL_CLIENT_ID=your_client_id_here
ANGEL_PIN=your_pin_here
ANGEL_TOTP_SECRET=your_totp_secret_here
```

## 🚀 Installation & Setup

1. **Clone the repository:**

   ```bash
   git clone <repository-url>
   cd <project-folder>
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the API:**
   ```bash
   uvicorn main:app --reload
   ```

## 🔌 API Endpoints

| Method | Endpoint         | Description                                  |
| :----- | :--------------- | :------------------------------------------- |
| `GET`  | `/`              | Home route                                   |
| `POST` | `/login`         | Authenticate with Broker and start WS stream |
| `GET`  | `/search-token`  | Search for symbol token                      |
| `POST` | `/set-position`  | Start monitoring SL/Target for a token       |
| `GET`  | `/get-positions` | Fetch all open positions                     |

## 🏗 Spike Filter Logic

- When the price hits the `Target` or `SL`, the `breach_time` is recorded.
- An EXIT signal is triggered only if the price sustains the breach for at least 2.5 seconds.
- If the price returns to the normal range before the timer expires, the filter resets.

---

_Developed with a focus on automation and reliability._
