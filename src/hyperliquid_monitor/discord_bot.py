import os
import sys
import logging
import discord
import asyncio
import threading
import time
from pathlib import Path
from discord.ext import commands
from dotenv import load_dotenv

# Fix the import path
current_dir = Path(__file__).resolve().parent
src_dir = current_dir.parent.parent
sys.path.insert(0, str(src_dir))

# Try different import strategies
try:
    # Try to import as a package first
    from hyperliquid_monitor.types import Trade, TradeCallback
    from .config import TESTNET_MODE, ADDRESSES
except ModuleNotFoundError:
    # Fall back to relative imports if package import fails
    try:
        from .types import Trade, TradeCallback
        from .config import TESTNET_MODE, ADDRESSES
    except ImportError:
        # Last resort: try absolute import from src
        from src.hyperliquid_monitor.types import Trade, TradeCallback
        from src.hyperliquid_monitor.config import TESTNET_MODE, ADDRESSES

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class HyperliquidDiscordBot:
    def __init__(self, shutdown_event=None):
        """
        Initialize the Discord bot for Hyperliquid trade notifications.
        
        Args:
            shutdown_event: Optional threading.Event to coordinate shutdown
        """
        # Load environment variables
        load_dotenv()
        
        # Get Discord configuration from environment
        self.token = os.getenv("DISCORD_TOKEN")
        self.channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
        self.log_level = os.getenv("DISCORD_LOG_LEVEL", "INFO")
        self.send_all_events = os.getenv("DISCORD_SEND_ALL_EVENTS", "false").lower() == "true"
        self.enable_large_trade_alerts = os.getenv("ENABLE_LARGE_TRADE_ALERTS", "false").lower() == "true"
        self.large_trade_threshold = float(os.getenv("LARGE_TRADE_THRESHOLD", "10000"))
        
        # Set up logging
        self.logger = logging.getLogger("discord_bot")
        self.logger.setLevel(getattr(logging, self.log_level))
        
        # Create a very minimal set of intents to avoid permissions issues
        # We only need to connect and send messages
        intents = discord.Intents.none()  # Start with no intents
        intents.guilds = True  # Need to see guilds to find the channel
        
        # Create the bot with minimal intents
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        
        # Save the shutdown event
        self._shutdown_event = shutdown_event
        
        # Set up event handlers
        self.setup_event_handlers()
        
    def setup_event_handlers(self):
        """Set up Discord bot event handlers."""
        @self.bot.event
        async def on_ready():
            self.logger.info(f'Bot connected as {self.bot.user.name} ({self.bot.user.id})')
            network_mode = "TESTNET" if TESTNET_MODE else "MAINNET"
            self.logger.info(f'Running in {network_mode} mode')
            self.channel = self.bot.get_channel(self.channel_id)
            if not self.channel:
                self.logger.error(f'Could not find channel with ID {self.channel_id}')
            else:
                # Comment out the startup message sending
                # embed = discord.Embed(...)
                # await self.channel.send(embed=embed)
                pass # Keep the else block for structure if needed later
                
            # Start a task to monitor for shutdown events
            if self._shutdown_event:
                self.bot.loop.create_task(self._check_shutdown())
                
        @self.bot.event
        async def on_error(event, *args, **kwargs):
            self.logger.error(f'Discord error in {event}: {args} {kwargs}')

    async def _check_shutdown(self):
        """Monitor the shutdown event and close the bot when it's set"""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(1)
        
        # Shutdown was triggered, send a goodbye message
        self.logger.info("Shutdown event detected, closing Discord bot...")
        
        try:
            # Try to send a shutdown message - COMMENTED OUT
            # if hasattr(self, 'channel') and self.channel:
            #     embed = discord.Embed(
            #         title="Hyperliquid Monitor Shutting Down",
            #         description="Bot is shutting down gracefully...",
            #         color=discord.Color.dark_grey(),
            #         timestamp=discord.utils.utcnow()
            #     )
            #     await self.channel.send(embed=embed)
            pass # No longer sending shutdown message
        except Exception as e:
            self.logger.error(f"Error during shutdown sequence (message sending commented out): {e}")
        
        # Close the bot connection after a short delay
        await asyncio.sleep(1)
        await self.bot.close()

    def start_bot(self):
        """Start the Discord bot."""
        if not self.token:
            self.logger.error("Discord token not provided. Bot will not start.")
            return
            
        if not self.channel_id:
            self.logger.error("Discord channel ID not provided. Bot will not start.")
            return
            
        self.logger.info("Starting Discord bot...")
        
        # Add a handler to close the bot on keyboard interrupt
        if self._shutdown_event:
            def check_shutdown():
                if self._shutdown_event.is_set() and self.bot.is_ready():
                    self.logger.info("Shutdown requested, closing bot...")
                    if not self.bot.is_closed():
                        asyncio.run_coroutine_threadsafe(self.bot.close(), self.bot.loop)
            
            # Create a monitoring thread
            shutdown_thread = threading.Thread(target=lambda: [
                check_shutdown() if self._shutdown_event.wait(1) else None
            ])
            shutdown_thread.daemon = True
            shutdown_thread.start()
        
        try:
            # Run the bot with handlers for graceful shutdown and auto-reconnect
            self.bot.run(self.token, reconnect=True, log_handler=None)
        except (KeyboardInterrupt, SystemExit):
            self.logger.info("Keyboard interrupt detected, closing bot...")
        except Exception as e:
            self.logger.error(f"Discord bot error: {e}")
            # Try to restart the bot after a short delay if not shutting down
            if self._shutdown_event and not self._shutdown_event.is_set():
                self.logger.info("Attempting to restart Discord bot in 10 seconds...")
                time.sleep(10)
                # Only try to restart if we're not in shutdown mode
                if not self._shutdown_event.is_set():
                    self.logger.info("Restarting Discord bot...")
                    self.bot.run(self.token, reconnect=True, log_handler=None)
        finally:
            # Make sure everything is properly closed
            if not self.bot.is_closed():
                asyncio.run_coroutine_threadsafe(self.bot.close(), self.bot.loop)
            self.logger.info("Discord bot stopped.")
        
    def create_trade_callback(self) -> TradeCallback:
        """
        Create a callback function that sends trade notifications to Discord.
        
        Returns:
            TradeCallback: A function to be used as a callback for trade events
        """
        async def send_discord_message(content, embed=None):
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                try:
                    await channel.send(content=content, embed=embed)
                except Exception as e:
                    self.logger.error(f"Error sending message to Discord: {e}")
        
        def callback(trade: Trade) -> None:
            # Skip non-fill events if send_all_events is False
            if not self.send_all_events and trade.trade_type != "FILL":
                return
                
            try:
                # Default values
                title_text = f"{trade.trade_type}: {trade.coin}"
                side_text = trade.side
                title_emoji = "ℹ️"
                embed_color = discord.Color.default()
                show_pnl = False

                # Customize based on trade type and direction
                if trade.trade_type == "FILL":
                    side = "LONG" if trade.side == "BUY" else "SHORT"
                    if trade.direction:
                        if "Open" in trade.direction or "Increase" in trade.direction:
                            action = "OPENED" if "Open" in trade.direction else "INCREASED"
                            title_text = f"{side} {action}"
                            title_emoji = "⬆️" if side == "LONG" else "⬇️"
                            embed_color = discord.Color.green() if side == "LONG" else discord.Color.red()
                            side_text = side # Keep side_text simple for open/increase
                        elif "Close" in trade.direction or "Decrease" in trade.direction:
                            action = "CLOSED" if "Close" in trade.direction else "DECREASED"
                            title_text = f"{side} {action}"
                            title_emoji = "💰"
                            embed_color = discord.Color.dark_gold()
                            side_text = side # Keep side_text simple for close/decrease
                            show_pnl = True # Show PnL for closing actions
                        elif "Liquidated" in trade.direction:
                            title_text = f"{side} LIQUIDATED"
                            title_emoji = "💀"
                            embed_color = discord.Color.dark_red()
                            side_text = side
                            show_pnl = True # Show PnL for liquidations
                        elif "Settled" in trade.direction: # Handle settlement if needed
                            title_text = f"{side} SETTLED"
                            title_emoji = "⚖️"
                            embed_color = discord.Color.light_grey()
                            side_text = side
                            show_pnl = True
                        else:
                            # Fallback for unknown directions
                            title_text = f"FILL: {trade.coin} {side}"
                            title_emoji = "❓"
                            embed_color = discord.Color.orange()
                            side_text = side
                    else:
                         # Fallback if direction is missing
                         title_text = f"FILL: {trade.coin} {side}"
                         title_emoji = "❓"
                         embed_color = discord.Color.orange()
                         side_text = side
                         
                elif trade.trade_type == "ORDER_PLACED":
                    side_text = "PLACE LONG" if trade.side == "BUY" else "PLACE SHORT"
                    title_text = "ORDER PLACED"
                    title_emoji = "📝"
                    embed_color = discord.Color.blue()
                elif trade.trade_type == "ORDER_CANCELLED":
                    side_text = "CANCEL LONG" if trade.side == "BUY" else "CANCEL SHORT"
                    title_text = "ORDER CANCELLED"
                    title_emoji = "🗑️"
                    embed_color = discord.Color.light_grey()
                
                embed = discord.Embed(
                    title=f"{title_emoji} {title_text}: {trade.coin}",
                    color=embed_color,
                    timestamp=trade.timestamp
                )
                
                embed.add_field(name="Address", value=f"`{trade.address}`", inline=False)
                embed.add_field(name="Side", value=side_text, inline=True) # Display derived side_text
                embed.add_field(name="Size", value=f"{trade.size:,.4f}", inline=True)
                embed.add_field(name="Price", value=f"${trade.price:,.2f}", inline=True)
                
                usd_value = trade.size * trade.price
                embed.add_field(name="Value", value=f"${usd_value:,.2f}", inline=True)
                
                # Add additional fields for FILL type
                if trade.trade_type == "FILL":
                    if trade.fee is not None:
                        embed.add_field(name="Fee", value=f"{trade.fee:,.6f} {trade.fee_token}", inline=True)
                    # Only show Closed PnL if it's a closing action
                    if show_pnl and trade.closed_pnl is not None:
                        pnl_emoji = "📈" if trade.closed_pnl >= 0 else "📉"
                        embed.add_field(name=f"{pnl_emoji} Closed PnL", value=f"${trade.closed_pnl:,.2f}", inline=True)
                    if trade.direction:
                        # Don't add direction field as it's now in the title
                        pass 
                    if trade.tx_hash:
                        base_url = "https://app.hyperliquid-testnet.xyz" if TESTNET_MODE else "https://app.hyperliquid.xyz"
                        tx_url = f"{base_url}/explorer/tx/{trade.tx_hash}"
                        embed.add_field(name="Transaction", value=f"[View]({tx_url})", inline=True)
                # Add order ID for order events
                elif trade.order_id:
                    embed.add_field(name="Order ID", value=str(trade.order_id), inline=True)
                
                # Set footer with simplified trade type and network mode
                footer_trade_type = trade.trade_type.replace("_", " ").title()
                network_label = "TESTNET" if TESTNET_MODE else "MAINNET"
                embed.set_footer(text=f"Hyperliquid {footer_trade_type} [{network_label}]")
                
                # Determine if this is a large trade that needs alerting
                if (self.enable_large_trade_alerts and 
                    trade.trade_type == "FILL" and 
                    usd_value >= self.large_trade_threshold):
                    
                    # Create a separate alert embed for large trades
                    alert_embed = discord.Embed(
                        title="🚨 LARGE TRADE ALERT 🚨",
                        description=f"**${usd_value:,.2f}** {title_text} detected", # Add context to description
                        color=discord.Color.gold(),
                        timestamp=trade.timestamp
                    )
                    alert_embed.add_field(name="Coin", value=trade.coin, inline=True)
                    # Use LONG/SHORT in large trade alert as well
                    alert_embed.add_field(name="Side", value=side_text, inline=True) 
                    alert_embed.add_field(name="Size", value=f"{trade.size:,.4f}", inline=True)
                    alert_embed.add_field(name="Address", value=f"`{trade.address}`", inline=False)
                    # Conditionally add PnL to large trade alert if closing
                    if show_pnl and trade.closed_pnl is not None:
                        pnl_emoji = "📈" if trade.closed_pnl >= 0 else "📉"
                        alert_embed.add_field(name=f"{pnl_emoji} Closed PnL", value=f"${trade.closed_pnl:,.2f}", inline=True)
                    alert_embed.set_footer(text=f"Hyperliquid Large Trade Alert [{network_label}]")
                    
                    # Send alert embed with @everyone mention
                    self.bot.loop.create_task(send_discord_message("@everyone", alert_embed))
                
                # Send the regular trade embed (without @everyone)
                self.bot.loop.create_task(send_discord_message(None, embed))
                
            except Exception as e:
                self.logger.error(f"Error processing trade callback: {e}")
                
        return callback 