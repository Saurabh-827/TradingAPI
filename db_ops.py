from sqlalchemy.orm import Session
from db_models import Position, TradeHistory

def upsert_position(db: Session, token: str, data: dict):
    pos = db.get(Position, token)
    if pos:
        for k, v in data.items():
            setattr(pos, k, v)
    else:
        db.add(Position(token=token, **data))
    db.commit()

def update_position_status(db: Session, token: str, status: str):
    pos = db.get(Position, token)
    if pos:
        pos.status = status
        db.commit()

def save_trade(db: Session, token: str, tradingsymbol: str, exit_reason: str, order_id: str = None, exit_price: float = None):
    db.add(TradeHistory(
        token=token,
        tradingsymbol=tradingsymbol,
        exit_reason=exit_reason,
        order_id=order_id,
        exit_price=exit_price
    ))
    db.commit()

def load_active_positions(db: Session):
    rows = db.query(Position).filter(Position.status == "ACTIVE").all()
    return {
        row.token: {
            "target": row.target, "sl": row.sl,
            "tradingsymbol": row.tradingsymbol, "exchange": row.exchange,
            "quantity": row.quantity, "exit_type": row.exit_type,
            "product_type": row.product_type, "linked_token": row.linked_token,
            "breach_time": None, "status": "ACTIVE"
        }
        for row in rows
    }

def get_trade_history(db: Session, token: str = None) -> list:
    query = db.query(TradeHistory)
    if token:
        query = query.filter(TradeHistory.token == token)
    return query.order_by(TradeHistory.exited_at.desc()).all()