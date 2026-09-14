from pydantic import BaseModel

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
    tradingsymbol: str
    exchange: str
    quantity: int
    exit_type: str = "SELL"
    product_type: str = "INTRADAY"
    linked_token: str = None