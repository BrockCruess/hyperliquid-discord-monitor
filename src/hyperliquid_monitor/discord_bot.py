import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
from hyperliquid_monitor.types import Trade, TradeCallback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class HyperliquidDiscordBot:
    def __init__(self):
        """Initialize the Discord bot for Hyperliquid trade notifications."""
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
        
        # Initialize the Discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        
        # Set up event handlers
        self.setup_event_handlers()
        
    def setup_event_handlers(self):
        """Set up Discord bot event handlers."""
        @self.bot.event
        async def on_ready():
            self.logger.info(f'Bot connected as {self.bot.user.name} ({self.bot.user.id})')
            self.channel = self.bot.get_channel(self.channel_id)
            if not self.channel:
                self.logger.error(f'Could not find channel with ID {self.channel_id}')
                
        @self.bot.event
        async def on_error(event, *args, **kwargs):
            self.logger.error(f'Discord error in {event}: {args} {kwargs}')

    def start_bot(self):
        """Start the Discord bot."""
        if not self.token:
            self.logger.error("Discord token not provided. Bot will not start.")
            return
            
        if not self.channel_id:
            self.logger.error("Discord channel ID not provided. Bot will not start.")
            return
            
        self.logger.info("Starting Discord bot...")
        self.bot.run(self.token)
        
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
                # Create a Discord embed with trade information
                embed = discord.Embed(
                    title=f"{trade.trade_type}: {trade.coin} {trade.side}",
                    color=discord.Color.green() if trade.side == "BUY" else discord.Color.red(),
                    timestamp=trade.timestamp
                )
                
                embed.add_field(name="Address", value=f"`{trade.address}`", inline=False)
                embed.add_field(name="Size", value=f"{trade.size:,.4f}", inline=True)
                embed.add_field(name="Price", value=f"${trade.price:,.2f}", inline=True)
                
                usd_value = trade.size * trade.price
                embed.add_field(name="Value", value=f"${usd_value:,.2f}", inline=True)
                
                # Add additional fields for FILL type
                if trade.trade_type == "FILL":
                    if trade.fee is not None:
                        embed.add_field(name="Fee", value=f"{trade.fee:,.6f} {trade.fee_token}", inline=True)
                    if trade.closed_pnl is not None:
                        embed.add_field(name="Closed PnL", value=f"${trade.closed_pnl:,.2f}", inline=True)
                    if trade.direction:
                        embed.add_field(name="Direction", value=trade.direction, inline=True)
                    if trade.tx_hash:
                        tx_url = f"https://hyperliquid.xyz/transactions/{trade.tx_hash}"
                        embed.add_field(name="Transaction", value=f"[View]({tx_url})", inline=True)
                # Add order ID for order events
                elif trade.order_id:
                    embed.add_field(name="Order ID", value=str(trade.order_id), inline=True)
                
                # Set footer with trade type
                embed.set_footer(text=f"Hyperliquid {trade.trade_type}")
                
                # Determine if this is a large trade that needs alerting
                alert_message = ""
                if (self.enable_large_trade_alerts and 
                    trade.trade_type == "FILL" and 
                    usd_value >= self.large_trade_threshold):
                    alert_message = f"@everyone Large trade detected: ${usd_value:,.2f}"
                
                # Use the bot's event loop to send the message
                self.bot.loop.create_task(send_discord_message(alert_message, embed))
                
            except Exception as e:
                self.logger.error(f"Error processing trade callback: {e}")
                
        return callback 