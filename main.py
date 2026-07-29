from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from SmartApi import SmartConnect

import json
from datetime import datetime

import time
from contextlib import asynccontextmanager
import requests

from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import threading

import pyotp
import os
from dotenv import load_dotenv

# Loading env credentials
load_dotenv()

# Global state for token list
instrument_list = []

# Startup (Auto-Download JSON with Caching)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic - on app start 
    global instrument_list
    file_path = "scrip_master.json"
    download_needed = True

    # Check if file exists and is downloaded today
    if os.path.exists(file_path):
        file_date = datetime.fromtimestamp(os.path.getmtime(file_path)).date()
        today_date = datetime.now().date()

        if file_date == today_date:
            download_needed = False
            print("Local Scrip Master found for today. Loading from disk...")

    if download_needed:
        print("Downloading Angel One Scrip Master (this might take 10-15 seconds)....")
        try:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            response = requests.get(url)
            instrument_list = response.json()

            # Save it locally for next time
            with open(file_path, "w") as f:
                json.dump(instrument_list, f)
            print(f"Success: Downloaded and saved {len(instrument_list)} instruments locally!")
        except Exception as e:
            print(f"Error while loading Scrip Master {e}")
    else:
        # Load from local file
        try:
            with open(file_path, "r") as f:
                instrument_list = json.load(f)
            print(f"Success: Loaded {len(instrument_list)} instruments from local cache in 1 second!")
        except Exception as e:
            print(f"Error while loading local Scrip Master {e}")

    yield  # Here API goes on running

    # Shutdown logic - on app close
    print("Clear instrument memory...")
    instrument_list.clear()

# FastAPI instance created with lifespan
app = FastAPI(title="TradingAPI", lifespan=lifespan)

# Credentials fetching
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PIN = os.getenv("ANGEL_PIN")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

# Validating env
if not all([API_KEY, CLIENT_ID, PIN, TOTP_SECRET]):
    raise RuntimeError("Missing required environment variables. Please check your .env file.")

# Creating SmartConnect instance
smartApi = SmartConnect(api_key=API_KEY)

# Response Models
class TokenData(BaseModel):
    jwtToken: str
    feedToken: str

class LoginResponse(BaseModel):
    status: str
    message: str
    tokens: TokenData

class SetTargetSLRequest(BaseModel):
    token: str
    target: float
    sl: float

# WebSocket Live Data State
liv_market_data = {}

# Active positions 
active_positions = {}

# Flag to check login status
is_broker_connected = False

def start_websocket_stream(jwt_token, feed_token):
    # Initializing websocket instance
    sws = SmartWebSocketV2(jwt_token, API_KEY, CLIENT_ID, feed_token)

    # Define callbacks INSIDE so they can use 'sws' automatically
    def on_data(wsapp, message):
        # Tick Data Parsing: On getting a new tick, read it and save it in state
        raw_token = message.get("token")
        if not raw_token:
            return

        token = raw_token
        
        current_price = message.get("last_traded_price", 0) / 100  # Divided by 100 to convert paise to rupees
        liv_market_data[token] = current_price
        # print(f"Live Price [{token}] : {current_price}")  # Commented this for a cleaner terminal

        # --- FAKE SPIKE FILTER LOGIC ---
        if token in active_positions and active_positions[token]['status'] == 'ACTIVE':
            order = active_positions[token]

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
                        active_positions[token]["status"] = "EXITED"
                        # Here we will send the order to the broker
            else:
                # Condition 2: If price returns to normal range (Fake Spike)
                if order["breach_time"] is not None:
                    print(f"[{token}] FAKE SPIKE DETECTED & IGNORED! Price returned to {current_price}.")
                    order["breach_time"] = None # Time reset

    def on_open(wsapp):
        print("Websocket connected successfully")
        # Token Subscription:
        # Exchange type: 5 (MCX), 2 (NSEFO), 1 (NSE)
        subscription_list = [{"exchangeType": 5, "tokens" : ["573628"]}]  # Token IDs are specific, currently taking a dummy ID
        sws.subscribe("spike_filter_stream", 1, subscription_list)

    def on_error(wsapp, error):
        print(f"Websocket Error: {error}")

    def on_close(wsapp):
        print("Websocket connection closed")

    sws.on_open = on_open
    sws.on_data = on_data
    sws.on_error = on_error
    sws.on_close = on_close

    # Connect function is blocking, that's why we call it in a thread 
    sws.connect()

@app.get("/")
def home():
    return {"message": "Welcome to the Trading API"}

@app.post("/login", response_model=LoginResponse)
def login_broker():
    global is_broker_connected
    try:
        # 1: Generating TOTP
        totp = pyotp.TOTP(TOTP_SECRET).now()

        # 2: Sending login request to broker API
        login_data = smartApi.generateSession(CLIENT_ID, PIN, totp)

        if login_data.get('status') == False:
            raise HTTPException(status_code=400, detail=login_data.get('message', 'Login Failed'))
        
        # 3: Extracting token (also needed for websockets)
        auth_token = login_data['data']['jwtToken']
        feed_token = smartApi.getfeedToken()

        # Starting WebSocket in a separate thread
        ws_thread = threading.Thread(
            target=start_websocket_stream,
            args=(auth_token, feed_token),
            daemon=True  # Daemon=True means when FastAPI closes, the thread also stops processing
        )
        ws_thread.start()
        
        is_broker_connected = True

        return {
            "status": "success",
            "message": "Login successfully",
            "tokens": {
                "jwtToken": auth_token,
                "feedToken": feed_token
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login Failed: {str(e)}")

@app.get("/search-token")
def search_token(symbol: str, exchange: str = "NSE"):
    if not instrument_list:
        raise HTTPException(status_code=500, detail="Instrument list not loaded yet")

    # List Comprehension to find matching symbols 
    # We can check partial match and exact match 
    results = []
    for item in instrument_list:
        if symbol.upper() in item['symbol'].upper() and item['exch_seg'] == exchange.upper():
            results.append({
                "symbol": item['symbol'],
                "token": item['token'],
                "exchange": item['exch_seg'],
                "expiry": item.get('expiry', 'NA')
            })

        if len(results) >= 10:  # Limiting to 10 results
            break

    if not results:
        raise HTTPException(status_code=404, detail="No token found for this symbol")

    return {"status": "success", "data": results}

@app.post("/set-position")
def set_position(data: SetTargetSLRequest):
    """
    Sets active monitoring parameters (Target & SL) for a specific token.
    """
    if not is_broker_connected:
        raise HTTPException(status_code=401, detail="Broker not connected. Please login first by hitting /login endpoint.")
    
    active_positions[data.token] = {
        "target": data.target,
        "sl": data.sl,
        "breach_time": None,
        "status": "ACTIVE"
    }
    
    return {
        "status": "success",
        "message": f"Monitoring started for Token {data.token}",
        "data": active_positions[data.token]
    }

@app.get("/get-positions")
def get_positions():

    # Check Login Status
    if not is_broker_connected:
        raise HTTPException(status_code=401, detail="Broker not connected. Please login first by hitting /login endpoint.")

    try:
        # Get position books from broker
        response = smartApi.position()
        if response.get("status") == False :
            raise HTTPException(status_code=400, detail=response.get("message", "Failed to fetch positions"))

        positions_data = response.get("data", [])

        # Filter ACTIVE open positions
        open_positions = []
        for pos in positions_data:
            # converting int because angelone's netqty comes as str
            net_qty= int(pos.get("netqty", 0))

            if net_qty != 0:
                open_positions.append({
                    "symbol": pos.get("tradingsymbol"),
                    "token": pos.get("symboltoken"),
                    "exchange": pos.get("exchange"),
                    "net_qty": net_qty,
                    "buy_price": float(pos.get("buyavgprice", 0)),
                    "pnl": pos.get("pnl", "0.00"),
                    "product_type": pos.get("producttype") # INTRADAY, CARRYFORWARD, etc.
                })
                
        return {
            "status": "Success",
            "total_open_positions": len(open_positions),
            "data": open_positions,
            "raw_data": positions_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions: {e}")