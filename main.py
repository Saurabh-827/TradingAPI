from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from SmartApi import SmartConnect
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