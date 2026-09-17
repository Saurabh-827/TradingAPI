from fastapi import FastAPI, HTTPException
from SmartApi import SmartConnect

import json
from datetime import datetime

from contextlib import asynccontextmanager
import requests

import threading

import pyotp
import os
from dotenv import load_dotenv

#local imports
import state
from models import LoginResponse, SetTargetSLRequest
from websocket_engine import start_websocket_stream, get_exchange_type

# Loading env credentials
load_dotenv()


# Startup (Auto-Download JSON with Caching)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic - on app start 
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
            state.instrument_list = response.json()

            # Save it locally for next time
            with open(file_path, "w") as f:
                json.dump(state.instrument_list, f)
            print(f"Success: Downloaded and saved {len(state.instrument_list)} instruments locally!")
        except Exception as e:
            print(f"Error while loading Scrip Master {e}")
    else:
        # Load from local file
        try:
            with open(file_path, "r") as f:
                state.instrument_list = json.load(f)
            print(f"Success: Loaded {len(state.instrument_list)} instruments from local cache in 1 second!")
        except Exception as e:
            print(f"Error while loading local Scrip Master {e}")

    yield  # Here API goes on running

    # Shutdown logic - on app close
    print("Clear instrument memory...")
    state.instrument_list.clear()

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

@app.get("/")
def home():
    return {"message": "Welcome to the Trading API"}

@app.post("/login", response_model=LoginResponse)
def login_broker():

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

        # Saving tokens globally for reconnect
        state.current_jwt_token = auth_token
        state.current_feed_token = feed_token

        # Starting WebSocket in a separate thread
        ws_thread = threading.Thread(
            target=start_websocket_stream,
            args=(auth_token, feed_token),
            daemon=True  # Daemon=True means when FastAPI closes, the thread also stops processing
        )
        ws_thread.start()
        
        state.is_broker_connected = True

        return {
            "status": "success",
            "message": "Login successfully",
            "tokens": {
                "jwtToken": auth_token,
                "feedToken": feed_token
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login Failed: {str(e)}")

@app.get("/search-token")
def search_token(symbol: str, exchange: str = "NSE"):
    if not state.instrument_list:
        raise HTTPException(status_code=500, detail="Instrument list not loaded yet")

    # List Comprehension to find matching symbols 
    # We can check partial match and exact match 
    results = []
    for item in state.instrument_list:
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
    if not state.is_broker_connected or state.sws is None:
        raise HTTPException(status_code=401, detail="Broker not connected. Please login first by hitting /login endpoint.")
    
    state.active_positions[data.token] = {
        "target": data.target,
        "sl": data.sl,
        "tradingsymbol": data.tradingsymbol,
        "exchange": data.exchange,
        "quantity": data.quantity,
        "exit_type": data.exit_type,
        "product_type": data.product_type,
        "linked_token": data.linked_token,
        "breach_time": None,
        "status": "ACTIVE"
    }

    # Dynamic Websocket subscription
    try:
        exch_type = get_exchange_type(data.exchange)
        subscription_list = [{"exchangeType": exch_type, "tokens": [data.token]}]

        state.sws.subscribe("dynamic_sub", 1, subscription_list)
        print(f"ON: Automatically subscribed Token {data.token} ({data.tradingsymbol}) to live stream!")
    except Exception as e:
        print(f"Failed to subscribe WebSocket for token {data.token}: {e}")
        del state.active_positions[data.token]
        raise HTTPException(status_code=500, detail="WebSocket subscription failed")
    
    return {
        "status": "success",
        "message": f"Monitoring started for Token {data.token}",
        "data": state.active_positions[data.token]
    }

@app.get("/get-positions")
def get_positions():

    # Check Login Status
    if not state.is_broker_connected:
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions: {e}")