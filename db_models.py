from sqlalchemy import Column, String, Float, Integer, DateTime, UniqueConstraint
from datetime import datetime, timezone
from database import Base

class Position(Base):
    __tablename__ = "positions"

    token         = Column(String, primary_key=True)
    tradingsymbol = Column(String, nullable=False)
    exchange      = Column(String, nullable=False)
    target        = Column(Float, nullable=True)
    sl            = Column(Float, nullable=True)
    quantity      = Column(Integer, nullable=False)
    exit_type     = Column(String, default="SELL")
    product_type  = Column(String, default="INTRADAY")
    linked_token  = Column(String, nullable=True)
    status        = Column(String, default="ACTIVE")
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class TradeHistory(Base):
    __tablename__ = "trade_history"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    token         = Column(String, nullable=False)
    tradingsymbol = Column(String, nullable=False)
    exit_reason   = Column(String, nullable=False) # TARGET | SL | COMPANION
    exit_price    = Column(Float, nullable=True)
    order_id      = Column(String, nullable=True, unique=True)  # idempotency key: prevents duplicate order execution
    exited_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
