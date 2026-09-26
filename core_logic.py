import state

def execute_exit_order(smartApi_instance, token: str, order_info: dict):
    """
    Places a MARKET EXIT order via Angel One SmartApi when target or SL is confirmed.
    """
    try:
        print(f"[{token}] INITIATING REAL EXIT ORDER...")
        
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": order_info["tradingsymbol"],
            "symboltoken": str(token),
            "transactiontype": order_info["exit_type"], 
            "exchange": order_info["exchange"],
            "ordertype": "MARKET",  
            "producttype": order_info["product_type"],
            "duration": "DAY",
            "quantity": str(order_info["quantity"])
        }

        # Sending order to broker
        response = smartApi_instance.placeOrder(orderparams)
        
        if response and response.get("status"):
            order_id = response.get("data")
            print(f"[{token}] ORDER EXECUTED SUCCESSFULLY! Order ID: {order_id}")
            return order_id
        else:
            print(f"[{token}] BROKER REJECTED ORDER: {response.get('message')}")
            return None

    except Exception as e:
        print(f"[{token}] CRITICAL ORDER FAILED: {str(e)}")
        return None

def process_full_exit(token: str, order: dict):
    """This function will run in a background thread to prevent blocking the WebSocket"""

    order_id = execute_exit_order(state.api_instance, token, order)

    if order_id and order.get("linked_token"):
        comp_token = order["linked_token"]
        companion_order = None

        with state.state_lock:
            if comp_token in state.active_positions and state.active_positions[comp_token]["status"] == "ACTIVE":
                print(f"[{token}] HEDGE BROKEN! Triggering instant auto-exit for companion token {comp_token}...")
                companion_order = state.active_positions[comp_token]
                state.active_positions[comp_token]["status"] = "EXITED"
        
        if companion_order:  # executing the exit order once fetched
            execute_exit_order(state.api_instance, comp_token, companion_order)
              
