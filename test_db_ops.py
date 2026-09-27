import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from db_ops import upsert_position, update_position_status, save_trade, load_active_positions

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()

SAMPLE = {  
    "tradingsymbol": "CRUDEOIL", "exchange": "MCX",
    "target": 6500.0, "sl": 6400.0, "quantity": 100,
    "exit_type": "SELL", "product_type": "INTRADAY", "linked_token": None, "status": "ACTIVE"
}

def test_upsert_creates_new(db):
    upsert_position(db, "111", SAMPLE)
    result = load_active_positions(db)
    assert "111" in result
    assert result["111"]["target"] == 6500.0

def test_upsert_updates_existing(db):
    upsert_position(db, "111", SAMPLE)
    upsert_position(db, "111", {**SAMPLE, "target": 6600.0})
    result = load_active_positions(db)
    assert result["111"]["target"] == 6600.0

def test_update_position_status(db):
    upsert_position(db, "111", SAMPLE)
    update_position_status(db, "111", "EXITED")
    result = load_active_positions(db)
    assert "111" not in result   # EXITED positions 

def test_save_trade(db):
    save_trade(db, "111", "CRUDEOIL", "TARGET", order_id="ORD123", exit_price=6510.0)
    from db_models import TradeHistory
    trades = db.query(TradeHistory).all()
    assert len(trades) == 1
    assert trades[0].exit_reason == "TARGET"
    assert trades[0].order_id == "ORD123"

def test_load_active_positions(db):
    result = load_active_positions(db)
    assert result == {}