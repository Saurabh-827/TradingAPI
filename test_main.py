import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from main import app, smartApi
import state

# TestClient initialize
client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    """This fixture cleans and mocks the state before every test"""
    state.is_broker_connected = False
    state.active_positions = {}
    state.sws = MagicMock() # Mocking websocket instance
    state.api_instance = MagicMock()

    # mocking data instead of downloading json
    state.instrument_list = [
        {"symbol": "CRUDEOIL24MAY6500CE", "token": "12345", "exch_seg": "MCX", "expiry": "24MAY2026"},
        {"symbol": "RELIANCE-EQ", "token": "67890", "exch_seg": "NSE", "expiry": "NA"}
    ]

    yield

# --- 1. Test Home Endpoint ---
def test_home():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message":"Welcome to the Trading API"}

# --- 2. Test /search-token Endpoint ---
def test_search_token_success():
    response = client.get("/search-token?symbol=CRUDE&exchange=MCX")
    assert response.status_code == 200

    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["token"] == "12345"

def test_search_token_not_found():
    response = client.get("/search-token?symbol=HDFCC&exchange=NSE")
    assert response.status_code == 404
    assert response.json()["detail"] == "No token found for this symbol"

def test_search_token_unloaded():
    state.instrument_list = []
    response = client.get("/search-token?symbol=CRUDE&exchnage=MCX")

    assert response.status_code == 500
    assert "Instrument list not loaded yet" in response.json()["detail"]

# --- 3. Test /login Endpoint (Mocking External APIs) ---
@patch("main.smartApi.generateSession")
@patch("main.smartApi.getfeedToken")
@patch("main.threading.Thread") #blocking background websocket thread
def test_login_success(mock_thread, mock_feedToken, mock_generateSession):

    mock_generateSession.return_value = {
        "status" : True,
        "message" : "SUCCESS",
        "data" : {"jwtToken": "fake_jwt_token"}
    }
    mock_feedToken.return_value = "fake_feed_token"

    response = client.post("/login")

    assert response.status_code == 200
    assert response.json()["tokens"]["jwtToken"] == "fake_jwt_token"
    assert state.is_broker_connected == True

@patch("main.smartApi.generateSession")
def test_login_failure_broker_rejection(mock_generateSession):
    mock_generateSession.return_value = {
        "status": False,
        "message": "Invalid Credentials"
    }

    response = client.post("/login")

    assert response.status_code == 400
    assert "Invalid Credentials" in response.json()["detail"]

# --- 4. Test /set-position Endpoint ---
def test_set_position_unauthorized():
    # without login trying to set position (state.is_broker_connected is False)
    payload = {
        "token": "12345",
        "target": 6500,
        "sl": 6450,
        "tradingsymbol": "CRUDECE",
        "exchange": "MCX",
        "quantity": 100
    }
    response = client.post("/set-position", json=payload)

    assert response.status_code == 401
    assert "Broker not connected" in response.json()["detail"]

def test_set_position_success():

    # mocking login to bypass
    state.is_broker_connected = True

    payload = {
        "token": "12345",
        "target": 6550,
        "sl": 6480,
        "tradingsymbol": "CRUDEOIL24MAY6500CE",
        "exchange": "MCX",
        "quantity": 100,
        "linked_token": "54321"
    }
    response = client.post("/set-position", json=payload)

    assert response.status_code == 200
    assert state.active_positions["12345"]["target"] == 6550
    assert state.active_positions["12345"]["linked_token"] == "54321"

def test_set_position_websocket_crash():
    state.is_broker_connected = True

    # Force the mocked WebSocket's subscribe method to raise an error
    state.sws.subscribe.side_effect = Exception("Mocked connection timeout")

    payload = {
        "token": "99999",
        "target": 6550,
        "sl": 6480,
        "tradingsymbol": "CRUDEOIL24MAY6500CE",
        "exchange": "MCX",
        "quantity": 100
    }
    response = client.post("/set-position", json=payload)

    assert response.status_code == 500
    assert "WebSocket subscription failed" in response.json()["detail"]
    assert "99999" not in state.active_positions

# --- 5. Test /get-positions Endpoint ---
def test_get_positions_unauthorized():
    # without login trying to get positions (state.is_broker_connected is False)
    response = client.get("/get-positions")
    assert response.status_code == 401 
    assert "Broker not connected" in response.json()["detail"]

@patch("main.smartApi.position")
def test_get_positions_success(mock_position):
    # bypassing login state
    state.is_broker_connected = True

    # Mocking Angel One's position response
    mock_position.return_value = {
        "status": True,
        "message": "SUCCESS",
        "data": [
            {
                "tradingsymbol": "CRUDEOIL24MAY6500CE",
                "symboltoken": "12345",
                "exchange": "MCX",
                "netqty": "100", # Active
                "buyavgprice": "50.5",
                "pnl": "1500.00",
                "producttype": "INTRADAY"
            },
            {
                "tradingsymbol": "RELIANCE-EQ",
                "symboltoken": "67890",
                "exchange": "NSE",
                "netqty": "0",  # Closed
                "buyavgprice": "2900.0",
                "pnl": "500.00",
                "producttype": "INTRADAY"
            }
        ]
    }

    response = client.get("/get-positions")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "Success"
    assert data["total_open_positions"] == 1
    assert data["data"][0]["symbol"] == "CRUDEOIL24MAY6500CE"
    assert data["data"][0]["net_qty"] == 100

@patch("main.smartApi.position")
def test_get_positions_broker_rejection(mock_position):
    state.is_broker_connected = True
    
    # Mock Angel One API returning a failure status
    mock_position.return_value = {
        "status": False,
        "message": "Session Expired or Invalid Token"
    }
    
    response = client.get("/get-positions")
    
    assert response.status_code == 400
    assert "Session Expired" in response.json()["detail"]