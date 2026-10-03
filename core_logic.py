import state
from database import SessionLocal
from db_ops import save_trade, update_position_status
from logger import get_logger

logger = get_logger(__name__)

def execute_exit_order(smartApi_instance, token: str, order_info: dict):
    """
    Places a MARKET EXIT order via Angel One SmartApi when target or SL is confirmed.
    """
    try:
        logger.info("[%s] Initiating exit order", token)
        
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
            logger.info("[%s] Order executed successfully. Order ID: %s", token, order_id)
            return order_id
        else:
            logger.warning("[%s] Broker rejected order: %s", token, response.get("message"))
            return None

    except Exception as e:
        logger.error("[%s] Order failed: %s", token, e)
        return None

def process_full_exit(token: str, order: dict):
    """This function will run in a background thread to prevent blocking the WebSocket"""

    order_id = execute_exit_order(state.api_instance, token, order)

    # Saving trade to DB
    with SessionLocal() as db:
        save_trade(db, token, order["tradingsymbol"], exit_reason=order.get("exit_reason","UNKNOWN"),
        order_id=order_id, exit_price=state.liv_market_data.get(token, 0))
        update_position_status(db, token, "EXITED")

    if order_id and order.get("linked_token"):
        comp_token = order["linked_token"]
        companion_order = None

        with state.state_lock:
            if comp_token in state.active_positions and state.active_positions[comp_token]["status"] == "ACTIVE":
                logger.info("[%s] Hedge broken. Triggering auto-exit for companion token %s", token, comp_token)
                companion_order = state.active_positions[comp_token]
                state.active_positions[comp_token]["status"] = "EXITED"
        
        if companion_order:  # executing the exit order once fetched
            execute_exit_order(state.api_instance, comp_token, companion_order)
            with SessionLocal() as db:
                save_trade(db, comp_token, companion_order["tradingsymbol"],
                exit_reason="COMPANION",
                order_id=None,
                exit_price=state.liv_market_data.get(comp_token))
                update_position_status(db, comp_token, "EXITED")
              
