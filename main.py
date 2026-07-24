from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from SmartApi import SmartConnect

from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import threading

import pyotp
import os
from dotenv import load_dotenv

# Loading env credentials
load_dotenv()

app = FastAPI(title="TradingAPI")

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

# WebSocket Live Data State

liv_market_data = {}



def start_websocket_stream(jwt_token, feed_token):
    #initializing websocket instance
    sws = SmartWebSocketV2(jwt_token, API_KEY, CLIENT_ID, feed_token)

    # Define callbacks INSIDE so they can use 'sws' automatically (crashing websocket)
    def on_data(wsapp, message):
        # Tick Data Parsin: On getting new tick, read it and save in state
        token = message.get("token")
        if token:
            liv_market_data[token] = message.get("last_traded_price", 0)/100  # diveded by 100 to convert paisa in rupees
            print(f"Live Price [{token}] : {liv_market_data[token]}")

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