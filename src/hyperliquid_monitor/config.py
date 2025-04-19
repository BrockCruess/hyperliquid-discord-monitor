import os
from dotenv import load_dotenv
from hyperliquid_monitor.database import init_database

# Load environment variables
load_dotenv()

# Get addresses from environment
ADDRESSES = [addr.strip() for addr in os.getenv("MONITORED_ADDRESSES", "").split(",") if addr.strip()]

# Initialize database and get path
DB_PATH = init_database(os.getenv("DB_PATH", "trades.db"))

# Discord configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
DISCORD_LOG_LEVEL = os.getenv("DISCORD_LOG_LEVEL", "INFO")
DISCORD_SEND_ALL_EVENTS = os.getenv("DISCORD_SEND_ALL_EVENTS", "false").lower() == "true"
ENABLE_LARGE_TRADE_ALERTS = os.getenv("ENABLE_LARGE_TRADE_ALERTS", "false").lower() == "true"
LARGE_TRADE_THRESHOLD = float(os.getenv("LARGE_TRADE_THRESHOLD", "10000"))