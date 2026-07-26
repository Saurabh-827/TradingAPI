from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from SmartApi import SmartConnect

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

# Startup (Auto-Download JSON)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic - on app start 
    global instrument_list
    print("Downloading Angel One Scrip Master (this might take 10-15 seconds)....")
    try:
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url)
        instrument_list = response.json()
        print(f"Success: Loaded {len(instrument_list)} instruments into memory !")
    except Exception as e:
        print(f"Error while loading Scrip Master {e}")

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

# active positions 
active_positions = {}

def start_websocket_stream(jwt_token, feed_token):
    #initializing websocket instance
    sws = SmartWebSocketV2(jwt_token, API_KEY, CLIENT_ID, feed_token)

    # Define callbacks INSIDE so they can use 'sws' automatically (crashing websocket)
    def on_data(wsapp, message):
        # Tick Data Parsin: On getting new tick, read it and save in state
        token = message.get("token")
        if not token:
            return
        
        current_price = message.get("last_traded_price", 0)/100  # diveded by 100 to convert paisa in rupees
        liv_market_data[token] = current_price
        # print(f"Live Price [{token}] : {current_price}")  # commented this for a clear terminal

        # --- FAKE SPIKE FILTER LOGIC ---
        if token in active_positions and active_positions[token]['status'] == 'ACTIVE':
            order =  active_positions[token]

            # Condition 1: Check if target price or stop loss hitted 
            if current_price >= order["target"] or current_price <= order['sl']:
                # if hitted first time than time will be noted 
                if order['breach_time'] is None:
                    order['breach_time'] = time.time()
                    print(f"[{token}] ALERT: Price reached {current_price}. Verification started...")

                # if reached before than check time passed
                else:
                    time_elapsed = time.time() - order["breach_time"]
                    
                    if time_elapsed >= 2.5: # 2.5 seconds sustai
                        print(f"[{token}] CONFIRMED: Price sustained at {current_price} for 2.5s. Executing REAL EXIT!")
                        active_positions[token]["status"] = "EXITED"
                    # here we have to send order to broker
            else:
                # Condition 2: if price comes again where it was than ( Fake Spike )
                if order["breach_time"] is not None:
                    print(f"[{token}] FAKE SPIKE DETECTED & IGNORED! Price returned to {current_price}.")
                    order["breach_time"] = None # Time reset

    def on_open(wsapp):
        print("Websocket connected successfully")
        # Token Subscription:
        # Exchange type : 5 (for MCX), 2(NSEFO), 1(NSE)
        subscription_list = [{"exchangeType": 1, "tokens" : ["3045"]}]  # token IDs are specfic, currently taking dummy ID (sbi)
        sws.subscribe("spike_filter_stream", 1, subscription_list)

    def on_error(wsapp, error):
        print(f"Websocket Error: {error}")

    def on_close(wsapp):
        print("Websocket connection closed")

    sws.on_open = on_open
    sws.on_data = on_data
    sws.on_error = on_error
    sws.on_close = on_close

    # connect function is blocking , thats why we call it in thread 
    sws.connect()

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

        #  Starting WebSocket in a separate thread
        ws_thread = threading.Thread(
            target= start_websocket_stream,
            args= (auth_token, feed_token),
            daemon= True  # Daemon=True means when FastAPI closes thread also stop processing
        )
        ws_thread.start()

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
def search_token(symbol:str, exchange: str="NSE"):
    if not instrument_list:
        raise HTTPException(status_code=500, detail="Instrument list not loaded yet")

    # List Comprehension to find matching symbols 
    # We can check partial match and exact match 

    results = []
    for item in instrument_list:
        if symbol.upper() in item['symbol'].upper() and item['exch_seg'] == exchange.upper():
            results.append({
                "symbol": item['symbol'],
                "token" : item['token'],
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