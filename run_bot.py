#!/usr/bin/env python3
"""
Hyperliquid Discord Bot Runner

This script runs the Hyperliquid Discord Bot to monitor trades and send notifications
to a Discord channel.
"""
import os
import sys
import signal
import threading
import time
from pathlib import Path
from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Now we can import with absolute imports
from src.hyperliquid_monitor.types import Trade
from src.hyperliquid_monitor.monitor import HyperliquidMonitor
from src.hyperliquid_monitor.discord_bot import HyperliquidDiscordBot
from src.hyperliquid_monitor.config import TESTNET_MODE

# Create a global shutdown event
shutdown_event = threading.Event()

# Add a heartbeat flag to track if the monitor is still running
monitor_heartbeat = threading.Event()
last_heartbeat_time = time.time()

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    print("\nShutdown signal received. Closing connections gracefully...")
    shutdown_event.set()

def monitor_heartbeat_func():
    """Send heartbeats to indicate the monitor is still running"""
    while not shutdown_event.is_set():
        global last_heartbeat_time
        monitor_heartbeat.set()
        last_heartbeat_time = time.time()
        time.sleep(30)  # Heartbeat every 30 seconds

def watchdog_thread_func(monitor):
    """Watch for monitor health and restart if necessary"""
    global last_heartbeat_time # Declare as global to modify the global variable
    while not shutdown_event.is_set():
        time.sleep(60)  # Check every minute
        
        # If we haven't received a heartbeat in 3 minutes, restart the monitor
        if time.time() - last_heartbeat_time > 180:
            print("WARNING: Monitor appears to be frozen (no heartbeat). Attempting to restart...")
            try:
                # Try to stop the current monitor
                monitor.stop()
                
                # Wait a moment
                time.sleep(5)
                
                # Start the monitor again (it should auto-reconnect)
                if not shutdown_event.is_set():
                    threading.Thread(target=monitor.start).start()
                    
                # Reset heartbeat timer
                monitor_heartbeat.set()
                last_heartbeat_time = time.time()
            except Exception as e:
                print(f"Error restarting monitor: {e}")

def main():
    """
    Main entry point for the Hyperliquid Discord monitor.
    Starts both the Hyperliquid monitor and Discord bot.
    """
    # Load environment variables
    load_dotenv()
    
    # Register signal handlers for graceful shutdown
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
    
    # Initialize the Discord bot with the shutdown event
    discord_bot = HyperliquidDiscordBot(shutdown_event)
    
    # Create a trade callback that sends notifications to Discord
    trade_callback = discord_bot.create_trade_callback()
    
    # Initialize the Hyperliquid monitor with the Discord callback and shutdown event
    monitor = HyperliquidMonitor(
        addresses=addresses,
        db_path=db_path,
        callback=trade_callback,
        shutdown_event=shutdown_event
    )
    
    # Start the heartbeat thread
    heartbeat_thread = threading.Thread(target=monitor_heartbeat_func)
    heartbeat_thread.daemon = True
    heartbeat_thread.start()
    
    # Start the watchdog thread
    watchdog_thread = threading.Thread(target=watchdog_thread_func, args=(monitor,))
    watchdog_thread.daemon = True
    watchdog_thread.start()
    
    # Start the monitor in a separate thread
    monitor_thread = threading.Thread(target=monitor.start)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    print("Hyperliquid monitor started. Waiting for trades...")
    print("Press Ctrl+C to exit gracefully.")
    
    # Start the Discord bot (this will block the main thread)
    try:
        print("Starting Discord bot...")
        discord_bot.start_bot()
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        # Ensure shutdown event is set
        shutdown_event.set()
        
        # Stop the monitor when the bot exits
        print("Shutting down gracefully...")
        monitor.stop()
        
        # Wait for the monitor thread to finish with a timeout
        monitor_thread.join(timeout=5)
        if monitor_thread.is_alive():
            print("Warning: Monitor thread did not terminate cleanly. Forcing exit...")
        else:
            print("Monitor thread terminated successfully.")
            
        print("Done!")

if __name__ == "__main__":
    main() 