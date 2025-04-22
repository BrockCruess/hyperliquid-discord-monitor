import os
import sys
import threading
import asyncio
import signal
from pathlib import Path
from dotenv import load_dotenv

# Fix the import path
current_dir = Path(__file__).resolve().parent
src_dir = current_dir.parent.parent
sys.path.insert(0, str(src_dir))

# Use try/except for more robust importing
try:
    # Try to import as a package first
    from hyperliquid_monitor.monitor import HyperliquidMonitor
    from hyperliquid_monitor.discord_bot import HyperliquidDiscordBot
    # Use relative import instead
    from .config import TESTNET_MODE
except ModuleNotFoundError:
    # Fall back to relative imports if package import fails
    try:
        from .monitor import HyperliquidMonitor
        from .discord_bot import HyperliquidDiscordBot
        from .config import TESTNET_MODE
    except ImportError:
        # Last resort: try absolute import from src
        from src.hyperliquid_monitor.monitor import HyperliquidMonitor
        from src.hyperliquid_monitor.discord_bot import HyperliquidDiscordBot
        from src.hyperliquid_monitor.config import TESTNET_MODE

# Create a shutdown event to coordinate clean shutdown
shutdown_event = threading.Event()

def signal_handler(sig, frame):
    """Handle interrupt signals by setting the shutdown event"""
    print("\nShutdown signal received. Closing connections gracefully...")
    shutdown_event.set()

def main():
    """
    Main entry point for the Hyperliquid Discord monitor.
    Starts both the Hyperliquid monitor and Discord bot.
    """
    # Load environment variables
    load_dotenv()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Get configuration directly from environment variables
    addresses = [addr.strip() for addr in os.getenv("MONITORED_ADDRESSES", "").split(",") if addr.strip()]
    db_path = os.getenv("DB_PATH", "trades.db")
    discord_token = os.getenv("DISCORD_TOKEN")
    discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
    
    # Print configuration details
    print("=== Hyperliquid Discord Monitor ===")
    network_mode = "TESTNET" if TESTNET_MODE else "MAINNET"
    print(f"Network mode: {network_mode}")
    print(f"Monitoring {len(addresses)} addresses: {', '.join(addresses)}")
    print(f"Database path: {db_path}")
    print(f"Discord channel ID: {discord_channel_id}")
    print("====================================")
    
    # Check for required configurations
    if not addresses:
        print("Error: No addresses configured to monitor. Please set MONITORED_ADDRESSES in .env file.")
        return
        
    if not discord_token:
        print("Error: Discord bot token not found. Please set DISCORD_TOKEN in .env file.")
        return
        
    if not discord_channel_id:
        print("Error: Discord channel ID not found. Please set DISCORD_CHANNEL_ID in .env file.")
        return
    
    # Initialize the Discord bot
    discord_bot = HyperliquidDiscordBot(shutdown_event)
    
    # Create a trade callback that sends notifications to Discord
    trade_callback = discord_bot.create_trade_callback()
    
    # Initialize the Hyperliquid monitor with the Discord callback
    monitor = HyperliquidMonitor(
        addresses=addresses,
        db_path=db_path,
        callback=trade_callback,
        shutdown_event=shutdown_event
    )
    
    # Start the monitor in a separate thread
    monitor_thread = threading.Thread(target=monitor.start)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    print("Hyperliquid monitor started. Waiting for trades...")
    
    # Start the Discord bot (this will block the main thread)
    try:
        print("Starting Discord bot...")
        discord_bot.start_bot()
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        # Stop the monitor when the bot exits
        print("Shutting down gracefully...")
        # Set shutdown event if not already set
        shutdown_event.set()
        # Stop the monitor
        monitor.stop()
        # Wait for threads to finish (with timeout)
        monitor_thread.join(timeout=5)
        print("Done!")

if __name__ == "__main__":
    main() 