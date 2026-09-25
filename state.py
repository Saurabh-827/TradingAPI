import threading

# Global Variables

instrument_list = []  # state for token list
is_broker_connected = False  # Flag to check login status
# --- Session Globals for Reconnection ---
current_jwt_token  = None
current_feed_token = None
reconnect_attempts = 0


# API Instances

sws = None   # Global websocket instance
api_instance = None  # Global smartapi instance stored here (AngelOne)

# State Data
active_positions = {}
liv_market_data = {}   # WebSocket Live Data State


# Thread Safety Lock
state_lock = threading.Lock()


