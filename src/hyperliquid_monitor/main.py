import os
import threading
import asyncio
from dotenv import load_dotenv

from hyperliquid_monitor.config import (
    ADDRESSES, DB_PATH, DISCORD_TOKEN, DISCORD_CHANNEL_ID
)
from hyperliquid_monitor.monitor import HyperliquidMonitor
from hyperliquid_monitor.discord_bot import HyperliquidDiscordBot

def main():
    """
    Main entry point for the Hyperliquid Discord monitor.
    Starts both the Hyperliquid monitor and Discord bot.
    """
    # Load environment variables
    load_dotenv()
    
    # Check for required configurations
    if not ADDRESSES:
        print("Error: No addresses configured to monitor. Please set MONITORED_ADDRESSES in .env file.")
        return
        
    if not DISCORD_TOKEN:
        print("Error: Discord bot token not found. Please set DISCORD_TOKEN in .env file.")
        return
        
    if not DISCORD_CHANNEL_ID:
        print("Error: Discord channel ID not found. Please set DISCORD_CHANNEL_ID in .env file.")
        return
    
    # Initialize the Discord bot
    discord_bot = HyperliquidDiscordBot()
    
    # Create a trade callback that sends notifications to Discord
    trade_callback = discord_bot.create_trade_callback()
    
    # Initialize the Hyperliquid monitor with the Discord callback
    monitor = HyperliquidMonitor(
        addresses=ADDRESSES,
        db_path=DB_PATH,
        callback=trade_callback
    )
    
    # Start the monitor in a separate thread
    monitor_thread = threading.Thread(target=monitor.start)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Start the Discord bot (this will block the main thread)
    try:
        discord_bot.start_bot()
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        # Stop the monitor when the bot exits
        monitor.stop()

if __name__ == "__main__":
    main() 