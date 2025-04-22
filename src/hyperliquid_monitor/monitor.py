import signal
import sys
import threading
import time
import importlib.metadata
from datetime import datetime
from typing import Dict, Any, List, Optional, Union

from hyperliquid.info import Info
from hyperliquid.utils import constants

from hyperliquid_monitor.database import TradeDatabase
from hyperliquid_monitor.types import Trade, TradeCallback
from .config import TESTNET_MODE

# Import the heartbeat mechanism if available
try:
    from run_bot import monitor_heartbeat
    HAS_HEARTBEAT = True
except ImportError:
    HAS_HEARTBEAT = False

# Define constants for API URLs
# The base URLs without the '/ws' path which is added by the Hyperliquid client
MAINNET_WS_URL = "https://api.hyperliquid.xyz"
TESTNET_WS_URL = "https://api.hyperliquid-testnet.xyz"

# Reconnection Settings
RECONNECT_DELAY = 120  # seconds (2 minutes)
# MAX_RECONNECT_ATTEMPTS = 10 # Removed - will retry indefinitely

def check_hyperliquid_version():
    """Check if the Hyperliquid package version is compatible"""
    try:
        version = importlib.metadata.version('hyperliquid')
        print(f"Detected Hyperliquid package version: {version}")
        return version
    except importlib.metadata.PackageNotFoundError:
        print("Warning: Unable to determine Hyperliquid package version")
        return None
    
class HyperliquidMonitor:
    def __init__(self, 
                 addresses: List[str], 
                 db_path: Optional[str] = None,
                 callback: Optional[TradeCallback] = None,
                 silent: bool = False,
                 shutdown_event: Optional[threading.Event] = None):
        """
        Initialize the Hyperliquid monitor.
        
        Args:
            addresses: List of addresses to monitor
            db_path: Optional path to SQLite database. If None, trades won't be stored
            callback: Optional callback function that will be called for each trade
            silent: If True, callback notifications will be suppressed even if callback is provided.
                   Useful for silent database recording. Default is False.
            shutdown_event: Optional threading.Event to coordinate shutdown
        """
        # Check Hyperliquid package version
        hl_version = check_hyperliquid_version()
        
        # Use testnet URL if TESTNET_MODE is enabled
        self.api_url = TESTNET_WS_URL if TESTNET_MODE else MAINNET_WS_URL
        self.info = self._create_info_client()
        self.addresses = addresses
        self.callback = callback if not silent else None
        self.silent = silent
        self.db = TradeDatabase(db_path) if db_path else None
        self._stop_event = shutdown_event if shutdown_event else threading.Event()
        self._db_lock = threading.Lock() if db_path else None
        self._subscriptions = []
        self._reconnect_count = 0
        self._connection_active = True
        # Store processed event IDs to prevent duplicates after reconnect
        self._processed_event_ids = set()
        
        if silent and not db_path:
            raise ValueError("Silent mode requires a database path to be specified")
    
    def _create_info_client(self):
        """Create a new Hyperliquid Info client with the current API URL"""
        try:
            # The hyperliquid.info.Info class expects the base URL without the '/ws' suffix
            # It will construct the proper WebSocket URLs internally
            print(f"Creating Hyperliquid client with base URL: {self.api_url}")
            
            client = Info(self.api_url)
            print("Successfully created Hyperliquid Info client")
            return client
        except Exception as e:
            print(f"Error creating Hyperliquid Info client: {e}")
            return None
            
    def _reconnect(self):
        """Attempt to reconnect to the Hyperliquid API indefinitely"""
        if self._stop_event.is_set() or not self._connection_active:
            return False
            
        # Removed max attempt logic
        # self._reconnect_count += 1
        # if self._reconnect_count > MAX_RECONNECT_ATTEMPTS:
        #     print(f"Maximum reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) reached. Stopping monitor.")
        #     self._stop_event.set()
        #     return False
            
        print(f"Attempting to reconnect to Hyperliquid API (delay: {RECONNECT_DELAY}s)...")
        
        # Wait before attempting the reconnection
        self._stop_event.wait(RECONNECT_DELAY)
        if self._stop_event.is_set(): # Check again after wait
            return False
        
        # Clean up old client if it exists
        self._cleanup_client()
        
        # Create new client
        self.info = self._create_info_client()
        if not self.info:
            print("Failed to create new client. Will retry...")
            # No need to explicitly call _reconnect here, the monitor thread will trigger it again
            return False # Indicate reconnect attempt failed for now
            
        # Resubscribe to all events
        self._subscriptions = []
        try:
            for address in self.addresses:
                self._subscribe_to_address(address)
            print(f"Successfully reconnected and resubscribed to {len(self.addresses)} addresses")
            # self._reconnect_count = 0 # No longer needed
            return True
        except Exception as e:
            print(f"Error during resubscription: {e}")
            # No need to explicitly call _reconnect here, the monitor thread will trigger it again
            return False # Indicate resubscription failed
            
    def _cleanup_client(self):
        """Clean up the current client instance"""
        if not self.info:
            return
            
        # Try to unsubscribe from all topics
        for sub_id in self._subscriptions:
            try:
                if hasattr(self.info, 'unsubscribe'):
                    self.info.unsubscribe(sub_id)
            except Exception:
                pass  # Ignore errors during cleanup
                
        # Try to close the connection
        try:
            if hasattr(self.info, 'close'):
                self.info.close()
        except Exception:
            pass  # Ignore errors during cleanup
        
    def handle_shutdown(self, signum=None, frame=None):
        """Handle shutdown signals"""
        if self._stop_event.is_set():
            return
            
        print("\nShutting down monitor gracefully...")
        self._stop_event.set()
        self._connection_active = False
        self.cleanup()
        
    def cleanup(self):
        """Clean up resources"""
        self._connection_active = False
        # Cancel all subscriptions
        self._cleanup_client()
                    
        # Close database
        if self.db:
            with self._db_lock:
                self.db.close()
            if not self.silent:
                print("Database connection closed.")
    
    def _subscribe_to_address(self, address):
        """Subscribe to events for a specific address"""
        if not self.info:
            print("Cannot subscribe: Hyperliquid client not initialized")
            return
            
        handler = self.create_event_handler(address)
        
        # Store subscription IDs for cleanup
        try:
            sub_id1 = self.info.subscribe(
                {"type": "userEvents", "user": address},
                handler
            )
            sub_id2 = self.info.subscribe(
                {"type": "userFills", "user": address},
                handler
            )
            self._subscriptions.extend([sub_id1, sub_id2])
        except Exception as e:
            print(f"Error subscribing to events for address {address}: {e}")
            raise
    
    def _update_heartbeat(self):
        """Update the heartbeat to indicate the monitor is still running"""
        if HAS_HEARTBEAT and monitor_heartbeat is not None:
            monitor_heartbeat.set()

    def _monitor_connection(self):
        """Thread function to monitor WebSocket connection health"""
        while not self._stop_event.is_set() and self._connection_active:
            try:
                # Update heartbeat
                self._update_heartbeat()
                
                # Check if the WebSocket client object or the ws attribute is None
                # The hyperliquid SDK sets self.info.ws = None on error/close
                if not self.info or self.info.ws is None:
                    print("WebSocket connection appears to be down (ws is None). Attempting to reconnect...")
                    # Trigger reconnect only if not already reconnecting and connection is supposed to be active
                    if self._connection_active and not self._stop_event.is_set(): 
                         # Use a lock or flag if starting multiple reconnect threads is an issue
                         # For now, assume _reconnect handles overlapping calls reasonably
                         # Run _reconnect in a separate thread to avoid blocking the monitor thread
                         threading.Thread(target=self._reconnect).start() 
                         # Sleep a bit after triggering reconnect to avoid spamming checks/logs
                         time.sleep(RECONNECT_DELAY / 2) # Sleep for half the reconnect delay
                         
            except Exception as e:
                print(f"Error in connection monitor: {e}")
                
            # Sleep for a while before checking again
            # Check less frequently now
            interval = 30 # Check every 30 seconds
            self._stop_event.wait(interval)

    def create_event_handler(self, address: str):
        """Creates an event handler for a specific address"""
        def handle_event(event: Dict[str, Any]) -> None:
            if self._stop_event.is_set():
                return
            
            # Update heartbeat to indicate activity    
            self._update_heartbeat()
                
            # Check for connection errors (handle_event might receive string errors)
            if isinstance(event, str) and "error" in event.lower() and "connection" in event.lower():
                print(f"WebSocket error detected: {event}")
                # Initiate reconnect in a separate thread to avoid blocking the event handler
                if not self._stop_event.is_set(): # Don't try reconnecting if we're shutting down
                    threading.Thread(target=self._reconnect).start()
                return

            if not isinstance(event, dict):
                # Log unexpected event types if needed
                # print(f"Received non-dict event: {event}")
                return
                
            data = event.get("data", {})
            
            # Handle fills
            if "fills" in data:
                for fill in data["fills"]:
                    if not isinstance(fill, dict):
                        continue
                    
                    fill_hash = fill.get("hash")
                    if not fill_hash:
                        continue # Skip fills without a hash
                        
                    # Check if this fill has already been processed
                    if fill_hash in self._processed_event_ids:
                        continue # Skip duplicate fill
                        
                    try:
                        trade = self._process_fill(fill, address)
                        # Add to processed set *before* calling callback
                        self._processed_event_ids.add(fill_hash)
                        if self.db:
                            with self._db_lock:
                                self.db.store_fill(fill)
                        if self.callback and not self.silent:
                            self.callback(trade)
                    except Exception as e:
                        if not self.silent:
                            print(f"Error processing fill {fill_hash}: {e}")
                        
            # Handle order updates        
            if "orderUpdates" in data:
                for update in data["orderUpdates"]:
                    if not isinstance(update, dict):
                        continue
                        
                    order_id = None
                    update_type = None
                    if "placed" in update and isinstance(update["placed"], dict):
                        order_id = update["placed"].get("oid")
                        update_type = "placed"
                    elif "canceled" in update and isinstance(update["canceled"], dict):
                        order_id = update["canceled"].get("oid")
                        update_type = "canceled"
                        
                    if order_id is None or update_type is None:
                        continue # Skip invalid order updates
                        
                    # Create a unique ID for this order update event
                    order_event_id = (order_id, update_type)
                    
                    # Check if this order update has already been processed
                    if order_event_id in self._processed_event_ids:
                        continue # Skip duplicate order update
                    
                    try:
                        trades = self._process_order_update(update, address)
                        # Add to processed set *before* calling callback
                        self._processed_event_ids.add(order_event_id)
                        if self.db:
                            with self._db_lock:
                                if "placed" in update:
                                    self.db.store_order(update, "placed")
                                elif "canceled" in update:
                                    self.db.store_order(update, "canceled")
                        if self.callback and not self.silent:
                            for trade in trades:
                                self.callback(trade)
                    except Exception as e:
                        if not self.silent:
                            print(f"Error processing order update {order_event_id}: {e}")
        
        return handle_event

    def _process_fill(self, fill: Dict, address: str) -> Trade:
        """Process fill information and return Trade object"""
        timestamp = datetime.fromtimestamp(int(fill.get("time", 0)) / 1000)
        
        return Trade(
            timestamp=timestamp,
            address=address,
            coin=fill.get("coin", "Unknown"),
            side="BUY" if fill.get("side", "B") == "A" else "SELL",
            size=float(fill.get("sz", 0)),
            price=float(fill.get("px", 0)),
            trade_type="FILL",
            direction=fill.get("dir"),
            tx_hash=fill.get("hash"),
            fee=float(fill.get("fee", 0)),
            fee_token=fill.get("feeToken"),
            start_position=float(fill.get("startPosition", 0)),
            closed_pnl=float(fill.get("closedPnl", 0))
        )
        
    def _process_order_update(self, update: Dict, address: str) -> List[Trade]:
        """Process order update information and return Trade objects"""
        timestamp = datetime.fromtimestamp(int(update.get("time", 0)) / 1000)
        trades = []
        
        if "placed" in update:
            order = update["placed"]
            trades.append(Trade(
                timestamp=timestamp,
                address=address,
                coin=update.get("coin", "Unknown"),
                side="BUY" if order.get("side", "B") == "A" else "SELL",
                size=float(order.get("sz", 0)),
                price=float(order.get("px", 0)),
                trade_type="ORDER_PLACED",
                order_id=int(order.get("oid", 0))
            ))
        elif "canceled" in update:
            order = update["canceled"]
            trades.append(Trade(
                timestamp=timestamp,
                address=address,
                coin=update.get("coin", "Unknown"),
                side="BUY" if order.get("side", "B") == "A" else "SELL",
                size=float(order.get("sz", 0)),
                price=float(order.get("px", 0)),
                trade_type="ORDER_CANCELLED",
                order_id=int(order.get("oid", 0))
            ))
            
        return trades
            
    def start(self) -> None:
        """Start monitoring addresses"""
        if not self.addresses:
            raise ValueError("No addresses configured to monitor")
            
        # Print connection information for debugging
        print(f"Connecting to Hyperliquid API at: {self.api_url} ({'TESTNET' if TESTNET_MODE else 'MAINNET'})")
            
        # Loop until initial connection is successful or shutdown is requested
        while not self.info and not self._stop_event.is_set():
            print("Attempting initial connection to Hyperliquid API...")
            self.info = self._create_info_client()
            if not self.info:
                print("Initial connection failed. Retrying...")
                # Use _reconnect logic (which includes delay) for retries
                # We don't need the return value here, just triggering the wait+retry
                # Run in current thread to block start until connected or stopped
                self._reconnect() 
                # After _reconnect, self.info might be set if it succeeded
                # The loop will check self.info again
            
        # If loop exited due to stop event, don't proceed
        if self._stop_event.is_set():
            print("Shutdown requested during initial connection phase.")
            self.cleanup()
            return
            
        print("Initial Hyperliquid connection established.")
        
        # Subscribe to events for each address
        # Loop for initial subscriptions, retrying if necessary
        subscription_successful = False
        while not subscription_successful and not self._stop_event.is_set():
            try:
                print("Subscribing to events...")
                self._subscriptions = [] # Clear previous attempts if any
                for address in self.addresses:
                    self._subscribe_to_address(address)
                    print(f"Successfully subscribed to events for address: {address}")
                subscription_successful = True
            except Exception as e:
                print(f"Error during initial subscription: {e}. Retrying connection...")
                # If subscription fails, assume connection issue and trigger reconnect
                self._reconnect() 
                # Reconnect might update self.info, loop will retry subscription
        
        # If loop exited due to stop event during subscription
        if self._stop_event.is_set():
            print("Shutdown requested during initial subscription phase.")
            self.cleanup()
            return
        
        # Start the connection monitor thread ONLY after successful initial connection and subscription
        self._connection_active = True
        connection_monitor = threading.Thread(target=self._monitor_connection)
        connection_monitor.daemon = True
        connection_monitor.start()
        
        print(f"Monitoring {len(self.addresses)} addresses on {'TESTNET' if TESTNET_MODE else 'MAINNET'}")
        
        try:
            # Keep the main monitor loop simple, relying on events and shutdown signal
            while not self._stop_event.is_set():
                self._update_heartbeat() # Keep updating heartbeat in the main loop
                self._stop_event.wait(5) # Check shutdown event periodically
        except KeyboardInterrupt:
            self.handle_shutdown()
        finally:
            # Make sure resources are cleaned up
            self._connection_active = False
            self.cleanup()

    def stop(self):
        """Stop the monitor"""
        if not self._stop_event.is_set():
            self._stop_event.set()
            self._connection_active = False
            self.cleanup()