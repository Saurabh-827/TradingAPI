# Global state for token list
instrument_list = []

# WebSocket Live Data State
liv_market_data = {}

# Active positions 
active_positions = {}

# Flag to check login status
is_broker_connected = False

# Global websocket instance
sws = None

# --- Session Globals for Reconnection ---
current_jwt_token  = None
current_feed_token = None
reconnect_attempts = 0
