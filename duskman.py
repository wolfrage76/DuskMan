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
from collections import deque
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

def create_shared_state(config):
    """Create and initialize the shared state dictionary."""
    max_log_entries = config.get('max_log_entries', 15)
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
        "log_entries": deque(maxlen=max_log_entries),
        "interrupt_sleep": False,
        "stake_checking": False,
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """Main entry point for the application."""
    # Initialize configuration first to get logging settings
    config_data = initialize_config()
    
    # Delete the debug log file if it exists
    debug_log_file = config_data.get('DEBUG_LOG_FILE', 'duskman_tmp_debug.log')
    if os.path.exists(debug_log_file):
        try:
            os.remove(debug_log_file)
        except Exception as e:
            print(f"Failed to delete debug log file {debug_log_file}: {e}")
    
    # Create shared state early (needed for logger)
    shared_state = create_shared_state(config_data)

    # Initialize notification service (needed for logger)
    notification_config = config_data['notification_config']
    notifier = NotificationService(notification_config)
    shared_state["notifier"] = notifier

    # Initialize logger (pass None for now, update later if needed)
    logger = Logger(shared_state, config_data, notifier) 
    log_action = logger.log_action
    shared_state["_log_action_func"] = log_action # Make logger available via state if needed

    # --- Task variables --- 
    monitor_task = None
    display_task = None
    stake_task = None
    dash_task = None
    tasks = [] # Keep track of created tasks

    try:
        # --- Initialize Components ---
        log_action("Init", "Initializing components...", "debug")
        blockchain_client = BlockchainClient(
            config_data['use_sudo'],
            config_data['password'],
            log_action
        )
        market_data_client = MarketDataClient(log_action)
        blockchain_monitor = BlockchainMonitor(
            blockchain_client,
            market_data_client,
            shared_state,
            config_data,
            log_action
        )
        stake_manager = StakeManager(
            blockchain_client,
            shared_state,
            config_data,
            log_action
        )
        display_manager = DisplayManager(
            shared_state,
            config_data['status_bar_config'],
            config_data['display_gui'],
            config_data['enable_tmux'],
            log_action
        )

        # --- Initial Data Fetch ---
        log_action("Init", "Performing initial balance fetch...", "debug")
        await blockchain_monitor.init_balance()

        # --- Options Display Logic ---
        # This helper function needs to be defined within the try block or before it
        def colorize_bool(value):
            return f"{GREEN}True{DEFAULT}" if value else f"{RED}False{DEFAULT}"

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
        if notification_services:
            services = "\\n\\t  " + " ".join(notification_services) if len(notification_services) > 2 else " ".join(notification_services)
        else:
            services = "None"
        enable_webdash = bool(config_data['dash_ip'] and config_data['dash_port'] and config_data['enable_dashboard'])
        notification_status = f'Enabled Notifications:{YELLOW}   {services}\\n'
        options_status = (
            f'\\n\\t{LIGHT_WHITE}Enable Web Dashboard:{DEFAULT}    {colorize_bool(enable_webdash)}'
            f'\\n\\t{LIGHT_WHITE}Enable tmux Support:{DEFAULT}     {colorize_bool(config_data["enable_tmux"])}'
            f'\\n\\t{LIGHT_WHITE}Auto Staking Rewards:{DEFAULT}    {colorize_bool(config_data["auto_stake_rewards"])}'
            f'\\n\\t{LIGHT_WHITE}Auto Restake to Reclaim:{DEFAULT} {colorize_bool(config_data["auto_reclaim_full_restakes"])}'
            f'\\n\\t{LIGHT_WHITE}{notification_status}'
        )
        byline = f"DuskMan Stake Management System: by Wolfrage"
        if not config_data['display_options']:
            byline = f"{UNDERLINE}{byline}{END_UNDERLINE}\n"
        separator = f"       {LIGHT_WHITE}{('=' * len(byline.strip()))}{DEFAULT}"
        if config_data['display_options']:
            shared_state["options"] = byline + "\n" + separator + options_status
        else:
            shared_state["options"] = byline
        # --- End Options Display ---

        # Start web dashboard if enabled
        if enable_webdash:
            from utilities.web_dashboard import start_dashboard
            dash_task = asyncio.create_task(start_dashboard(shared_state, shared_state["log_entries"], host=config_data['dash_ip'], port=config_data['dash_port']), name="DashboardTask")
            tasks.append(dash_task)

        # Create main loop tasks
        monitor_task = asyncio.create_task(blockchain_monitor.frequent_update_loop(), name="MonitorTask")
        display_task = asyncio.create_task(display_manager.realtime_display_loop(), name="DisplayTask")
        stake_task = asyncio.create_task(stake_manager.stake_management_loop(), name="StakeTask")
        tasks.extend([monitor_task, display_task, stake_task])

        # Format task names for logging
        task_names = ", ".join([t.get_name() for t in tasks if t])
        log_action("Startup", f"Starting main loops: {task_names}...", "info")

        # Use gather to run tasks concurrently. It will wait for all tasks
        # or raise the first exception encountered.
        await asyncio.gather(*tasks)

        # This line should not be reached if loops are truly infinite
        log_action("Shutdown", "Main loops completed unexpectedly. Initiating shutdown.", "warning")

    except asyncio.CancelledError:
        log_action("Shutdown Signal", "Cancellation requested (likely CTRL-C or external signal).", "info")
    # KeyboardInterrupt might be caught as CancelledError by asyncio.run, but handle explicitly just in case
    except KeyboardInterrupt:
        log_action("Shutdown Signal", "CTRL-C detected. Initiating graceful shutdown...", "info")
    except Exception as e:
        log_action("Critical Error", f"An unexpected error occurred in main execution: {e}", "critical")
        import traceback
        log_action("Main Traceback", traceback.format_exc(), "critical") # Log full traceback

    finally:
        log_action("Shutdown", "Initiating cleanup sequence...", "info")
        # Signal sleep interruption flag
        if 'shared_state' in locals():
            # Use lock if available (might not be if init failed early)
            lock = shared_state.get("state_lock") # Assuming state_lock might be added to shared_state centrally
            if lock and isinstance(lock, asyncio.Lock):
                 async with lock:
                      shared_state["interrupt_sleep"] = True
            else: # Fallback if lock isn't initialized/available
                 shared_state["interrupt_sleep"] = True
            await asyncio.sleep(0.1) # Brief pause for flag propagation

        # Cancel all potentially running tasks gracefully
        # Use the task variables directly for clarity
        all_created_tasks = [t for t in [monitor_task, display_task, stake_task, dash_task] if t is not None]
        running_tasks = [t for t in all_created_tasks if not t.done()]

        if running_tasks:
            log_action("Shutdown", f"Cancelling {len(running_tasks)} tasks: {[t.get_name() for t in running_tasks]}...\", \"info")
            for task in running_tasks:
                task.cancel()

            # Wait for tasks to finish cancellation
            results = await asyncio.gather(*running_tasks, return_exceptions=True)
            log_action("Shutdown", "Task cancellation process complete.", "info")

            # Log results of cancellation attempt
            for i, result in enumerate(results):
                 task_name = running_tasks[i].get_name()
                 if isinstance(result, asyncio.CancelledError):
                     # This is expected during cancellation
                     log_action("Task Cleanup", f"Task {task_name} cancelled successfully.", "debug")
                 elif isinstance(result, Exception):
                     # Log errors that occurred *during* cancellation
                     log_action("Task Cleanup Error", f"Error during {task_name} cancellation/cleanup: {result}", "error")
                 else:
                      # Task might have finished between check and gather
                      log_action("Task Cleanup", f"Task {task_name} finished during cleanup.", "debug")
        else:
            log_action("Shutdown", "No tasks required cancellation.", "info")

        log_action("Shutdown Complete", "Exiting application.", "info")
        if 'logger' in locals() and hasattr(logger, 'shutdown'):
             logger.shutdown()

if __name__ == "__main__":
    # asyncio.run handles the main event loop start/stop and KeyboardInterrupt
        asyncio.run(main())
