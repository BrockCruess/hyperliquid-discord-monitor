from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal, Callable

TradeType = Literal["FILL", "ORDER_PLACED", "ORDER_CANCELLED"]

@dataclass
class Trade:
    timestamp: datetime
    address: str
    coin: str
    side: Literal["BUY", "SELL"]
    size: float
    price: float
    trade_type: TradeType
    direction: Optional[str] = None
    tx_hash: Optional[str] = None
    fee: Optional[float] = None
    fee_token: Optional[str] = None
    start_position: Optional[float] = None
    closed_pnl: Optional[float] = None
    order_id: Optional[int] = None

TradeCallback = Callable[[Trade], None]