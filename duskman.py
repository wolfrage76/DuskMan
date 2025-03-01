#!/usr/bin/env python3
"""
DuskMan: The Dusk Network stake manager

Automates the monitoring and management of DUSK Network staking, balances,
compounding, and monitoring system health.
"""

import os
import sys
import asyncio
import argparse
from rich.traceback import install
from rich.console import Console
from dotenv import load_dotenv

# Import utility modules
from utilities.config import initialize_config
from utilities.logger import Logger
from utilities.notifications import NotificationService
from utilities.blockchain_client import BlockchainClient
from utilities.blockchain_monitor import BlockchainMonitor
from utilities.market_data import MarketDataClient
from utilities.stake_manager import StakeManager
from utilities.display_manager import DisplayManager
from utilities.colors import *

# Initialize rich traceback handler
install()

# Load environment variables
load_dotenv()

# Initialize console
console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────────────────────────────────────────

def create_shared_state():
    """Create and initialize the shared state dictionary."""
    return {
        "block_height": 0,
        "remain_time": 0,                 # seconds left in the current sleep
        "last_no_action_block": None,     # track 'No Action' blocks
        "last_claim_block": 0,
        "stake_info": {
            "stake_amount": 0.0,
            "reclaimable_slashed_stake": 0.0,
            "rewards_amount": 0.0,
        },
        "balances": {
            "public": 0.0,
            "shielded": 0.0
        },
        "last_action_taken": "Starting Up",
        "completion_time": "--:--",
        "peer_count": 0,
        "price": 0.0,
        "market": 0,
        "volume": 0,
        "usd_24h_change": 0,
        "rendered": "",
        "stake_active_blk": 0,
        "options": "",
        "rewards_per_epoch": 0.0,
        "log_entries": [],
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """Main entry point for the application."""
    # Initialize configuration
    config_data = initialize_config()
    
    # Create shared state
    shared_state = create_shared_state()
    
    # Initialize notification service
    notification_config = config_data['notification_config']
    notifier = NotificationService(notification_config)
    shared_state["notifier"] = notifier
    
    # Initialize logger
    logger = Logger(shared_state, config_data, notifier)
    log_action = logger.log_action
    
    # Initialize blockchain client
    blockchain_client = BlockchainClient(
        config_data['use_sudo'],
        config_data['password'],
        log_action
    )
    
    # Initialize market data client
    market_data_client = MarketDataClient(log_action)
    
    # Initialize blockchain monitor
    blockchain_monitor = BlockchainMonitor(
        blockchain_client,
        market_data_client,
        shared_state,
        config_data,
        log_action
    )
    
    # Initialize stake manager
    stake_manager = StakeManager(
        blockchain_client,
        shared_state,
        config_data,
        log_action
    )
    
    # Initialize display manager
    display_manager = DisplayManager(
        shared_state,
        config_data['status_bar_config'],
        config_data['display_gui'],
        config_data['enable_tmux'],
        log_action
    )
    
    # Helper function to colorize boolean values
    def colorize_bool(value):
        return f"{GREEN}True{DEFAULT}" if value else f"{RED}False{DEFAULT}"

    # Ensure balances are initialized for display
    await blockchain_monitor.init_balance()

    # Collect enabled notification services
    notification_services = [
        service for service, enabled in {
            "Discord": notification_config.get('discord_webhook', False),
            "PushBullet": notification_config.get('pushbullet_token', False),
            "Telegram": notification_config.get('telegram_bot_token', False) and notification_config.get('telegram_chat_id', False),
            "Pushover": notification_config.get('pushover_user_key', False) and notification_config.get('pushover_app_token', False),
            "Webhook": notification_config.get('webhook_url', False),
            "Slack": notification_config.get('slack_webhook', False),
        }.items() if enabled
    ]

    # Format the notification services display
    if notification_services:
        services = "\n\t  " + " ".join(notification_services) if len(notification_services) > 2 else " ".join(notification_services)
    else:
        services = "None"

    # Determine dashboard status
    enable_webdash = bool(config_data['dash_ip'] and config_data['dash_port'] and config_data['enable_dashboard'])

    # Build the status messages
    notification_status = f'Enabled Notifications:{YELLOW}   {services}\n'
    
    auto_status = (
        f'\n\t{LIGHT_WHITE}Enable Web Dashboard:{DEFAULT}    {colorize_bool(enable_webdash)}'
        f'\n\t{LIGHT_WHITE}Enable tmux Support:{DEFAULT}     {colorize_bool(config_data["enable_tmux"])}'
        f'\n\t{LIGHT_WHITE}Auto Staking Rewards:{DEFAULT}    {colorize_bool(config_data["auto_stake_rewards"])}'
        f'\n\t{LIGHT_WHITE}Auto Restake to Reclaim:{DEFAULT} {colorize_bool(config_data["auto_reclaim_full_restakes"])}'
        f'\n\t{LIGHT_WHITE}{notification_status}'
    )
    
    byline = f"DuskMan Stake Management System: by Wolfrage"
    if not config_data['display_options']:
        byline = f"{UNDERLINE}{byline}{END_UNDERLINE}\n"
        
    separator = f"       {LIGHT_WHITE}{('=' * len(byline))}{DEFAULT}"

    # Update shared state with options display
    if config_data['display_options']:
        shared_state["options"] = byline + '\n' + separator + auto_status
    else:
        shared_state["options"] = byline 

    # Start web dashboard if enabled
    if enable_webdash:
        from utilities.web_dashboard import start_dashboard
        await start_dashboard(shared_state, shared_state["log_entries"], host=config_data['dash_ip'], port=config_data['dash_port'])
    
    # Start all the main loops
    await asyncio.gather(
        blockchain_monitor.frequent_update_loop(),
        display_manager.realtime_display_loop(),
        stake_manager.stake_management_loop(),
    )

if __name__ == "__main__":
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="Process command line arguments")
        parser.add_argument('-d', action='store_true', help="Run without GUI display, for background usage")
        args = parser.parse_args()
        
        # Run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nCTRL-C detected. Exiting gracefully.\n")
        sys.exit(0)
