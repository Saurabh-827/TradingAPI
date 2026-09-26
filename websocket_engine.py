import time
import threading
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

import state
from core_logic import process_full_exit

def get_exchange_type(exchange: str) -> int:
    """Angel one convert exchange's strings to numeric id"""
    mapping = {
        "NSE": 1,
        "NFO": 2,
        "BSE": 3,
        "MCX": 5,
        "NCDEX": 7,
        "CDS": 13
    }
    return mapping.get(exchange.upper(), 1)  # Default 1(NSE)

def start_websocket_stream(API_KEY, CLIENT_ID, jwt_token, feed_token):

    # Initializing websocket instance
    state.sws = SmartWebSocketV2(jwt_token, API_KEY, CLIENT_ID, feed_token)

    # Define callbacks INSIDE so they can use 'sws' automatically
    def on_data(wsapp, message):
        # Tick Data Parsing: On getting a new tick, read it and save it in state
        raw_token = message.get("token")
        if not raw_token:
            return

        token = raw_token
        
        current_price = message.get("last_traded_price", 0) / 100  # Divided by 100 to convert paise to rupees
        state.liv_market_data[token] = current_price
        # print(f"Live Price [{token}] : {current_price}")  # Commented this for a cleaner terminal

        # --- FAKE SPIKE FILTER LOGIC ---
        if token in state.active_positions and state.active_positions[token]['status'] == 'ACTIVE':
            order = state.active_positions[token]

            # Condition 1: Check if target price or stop loss is hit 
            if current_price >= order["target"] or current_price <= order['sl']:
                
                # If hit for the first time, record the breach time 
                if order['breach_time'] is None:
                    order['breach_time'] = time.time()
                    print(f"[{token}] ALERT: Price reached {current_price}. Verification started...")

                # If already breached, check elapsed time
                else:
                    time_elapsed = time.time() - order["breach_time"]
                    
                    if time_elapsed >= 2.5: # 2.5 seconds sustained
                        print(f"[{token}] CONFIRMED: Price sustained at {current_price} for 2.5s. Executing REAL EXIT!")
                        with state.state_lock:
                            state.active_positions[token]["status"] = "EXITED"
                        # Here we will send the order to the broker
                        # --- DECOUPLED EXECUTION (Fire & Forget) ---
                        threading.Thread(
                            target=process_full_exit,
                            args=(token, order),
                            daemon=True
                        ).start()
            else:
                # Condition 2: If price returns to normal range (Fake Spike)
                if order["breach_time"] is not None:
                    print(f"[{token}] FAKE SPIKE DETECTED & IGNORED! Price returned to {current_price}.")
                    order["breach_time"] = None # Time reset

    def on_open(wsapp):
        state.reconnect_attempts = 0  # Reset reconnect counter on successful connect

        print("Websocket connected successfully. Waiting for dynamic subscriptions...")
        # --- AUTO-RESUBSCRIBE ---

        if state.active_positions:
            print("Restoring active subscriptions after connection...")
            for token, pos_data in state.active_positions.items():
                if pos_data["status"] == "ACTIVE":
                    exch_type = get_exchange_type(pos_data["exchange"])
                    subscription_list = [{"exchangeType": exch_type, "tokens": [token]}]

                    try:
                        state.sws.subscribe("dynamic_sub", 1, subscription_list)
                        print(f"   -> Resubscribed Token: {token}")
                    except Exception as e:
                        print(f"   -> Failed to resubscribe {token}: {e}")

    def on_error(wsapp, error):
        print(f"Websocket Error: {error}")

    def trigger_reconnect():
        state.reconnect_attempts += 1

        wait_time = min(state.reconnect_attempts * 5, 30) 
        print(f"Connection lost! Attempting reconnect {state.reconnect_attempts} in {wait_time} seconds...")
        time.sleep(wait_time)

        if state.current_jwt_token and state.current_feed_token:
            threading.Thread(
                target=start_websocket_stream,
                args=(API_KEY, CLIENT_ID, state.current_jwt_token, state.current_feed_token),
                daemon=True
            ).start()

    def on_close(wsapp):
        print("Websocket connection closed")

        threading.Thread(target=trigger_reconnect, daemon=True).start()

    state.sws.on_open = on_open
    state.sws.on_data = on_data
    state.sws.on_error = on_error
    state.sws.on_close = on_close

    # Connect function is blocking, that's why we call it in a thread 
    try:
        state.sws.connect()
    except Exception as e:
        print(f"Critical Error: WebSocket failed to connect or crashed - {str(e)}")
