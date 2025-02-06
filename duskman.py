import os
import sys
import subprocess
import re
import yaml
import asyncio
import aiohttp
import argparse

from rich.live import Live
from rich.text import Text
from dotenv import load_dotenv
from rich.console import Console
from rich import print
from datetime import datetime, timedelta
from utilities.notifications import NotificationService
from rich.traceback import install

install()
load_dotenv()
console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION AND INITIALIZING
# ─────────────────────────────────────────────────────────────────────────────



def load_config(section="GENERAL", file_path="config.yaml"):
    """Load configuration from a YAML file."""
    try:
        with open(file_path, "r") as file:
            config = yaml.safe_load(file)
            return config.get(section, {})
    except FileNotFoundError:
        log_action("Config File error", f"Configuration file {file_path} not found. Exiting.", "error")
        sys.exit(1)
    except yaml.YAMLError as e:
        log_action("Config File Error", f"Error parsing YAML file {file_path}: {e}", "error")
        sys.exit(1)

# Load configuration
config = load_config('GENERAL')
notification_config = load_config('NOTIFICATIONS')
status_bar = load_config('STATUSBAR')
web_dashboard = load_config('WEB_DASHBOARD')
logs_config = load_config('LOG_FILES')

min_rewards = config.get('min_rewards', 1)
min_slashed = config.get('min_slashed', 1)
buffer_blocks = config.get('buffer_blocks', 60)
min_stake_amount = config.get('min_stake_amount', 1000)
min_peers = config.get('min_peers', 10)
auto_stake_rewards = config.get('auto_stake_rewards', False)
auto_reclaim_full_restakes = config.get('auto_reclaim_full_restakes', False)
pwd_var = config.get('pwd_var_name', 'MY_WALLET_VARIABLE')
enable_dashboard = web_dashboard.get('enable_dashboard', True)
dash_port = web_dashboard.get('dash_port', '5000')
dash_ip = web_dashboard.get('dash_ip', '0.0.0.0')
include_rendered = web_dashboard.get('include_rendered', False)
isDebug = logs_config.get('debug', False)
display_options = config.get('display_options', True)
monitor_wallet = notification_config.get('monitor_balance', False)

# Initialize parser
parser = argparse.ArgumentParser(description="Process command line arguments")
enable_logging = logs_config.get('enable_logging', False)

# Add boolean flag for `-d`
parser.add_argument('-d', action='store_true', help="Run without GUI display, for background usage")

# Parse arguments
args = parser.parse_args() or {}

# Store it as a boolean variable
display_gui = not args.d

if config.get('use_sudo', False):
    use_sudo = 'sudo'
else:
    use_sudo = ''

errored = False
log_entries = []
stake_checking = False

INFO_LOG_FILE = logs_config.get("action_log","duskman_actions.log")
ERROR_LOG_FILE =  logs_config.get("error_log","duskman_errors.log")
DEBUG_LOG_FILE =  logs_config.get("debug_log","duskman_tmp_debug.log")

if isDebug and os.path.exists(DEBUG_LOG_FILE):
    os.remove(DEBUG_LOG_FILE)

END_UNDERLINE = "\033[0m"
UNDERLINE = "\033[4m"

byline = f"DuskMan Stake Management System: by Wolfrage"
if not config.get('display_options', True):
    byline = f"{UNDERLINE}{byline}{END_UNDERLINE}\n"
    
# If user passes "tmux" as first argument, override enable_tmux
if config.get('enable_tmux', False) or (len(sys.argv) > 1 and sys.argv[1].lower() == 'tmux'):
    enable_tmux = True
else:
    enable_tmux = False

# Initialize the notification service
notifier = NotificationService(notification_config)


BLACK = "\033[0;30m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
BROWN = "\033[0;33m"
BLUE = "\033[0;34m"
PURPLE = "\033[0;35m"
CYAN = "\033[0;36m"
LIGHT_GRAY = "\033[0;37m"
DARK_GRAY = "\033[1;30m"
LIGHT_RED = "\033[1;31m"
LIGHT_GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
LIGHT_BLUE = "\033[1;34m"
LIGHT_PURPLE = "\033[1;35m"
LIGHT_CYAN = "\033[1;36m"
LIGHT_WHITE = "\033[1;37m"

DEFAULT = "\033[1;39m"



# ─────────────────────────────────────────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────────────────────────────────────────

shared_state = {
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
    "price":0.0,
    "market": 0,
    "volume": 0,
    "usd_24h_change": 0,
    "rendered":"",
    "stake_active_blk": 0,
    "options":"",
    "rewards_per_epoch":0.0,
}

# Define log file paths


# Log format
LOG_FORMAT = "{timestamp} - {message}"

# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
def get_env_variable(var_name='WALLET_PASSWORD', dotenv_key='WALLET_PASSWORD'):
    """
    Retrieve an environment variable or a fallback value from .env file.
    """
    value = os.getenv(var_name)
    if not value:
        value = os.getenv(dotenv_key)
        if not value:
            log_action("Wallet Password Variable Error", f"Neither environment variable '{var_name}' nor .env key '{dotenv_key}' found for wallet password.", "error")
            sys.exit(1)
            
    return value

password = get_env_variable(config.get('pwd_var_name', 'WALLET_PASSWORD'), dotenv_key="WALLET_PASSWORD")


def display_wallet_distribution_bar(public_amount, shielded_amount, width=30):
    """
    Displays a single horizontal bar (ASCII blocks) with two colored segments
    to visualize the distribution of funds between public and shielded balances.

    :param public_amount: float, the public balance
    :param shielded_amount: float, the shielded balance
    :param width: int, total number of blocks in the bar
    :return: str, the rendered bar
    """
    total = public_amount + shielded_amount
    if total <= 0:
        # No funds, return empty string
        return str()

    # Calculate ratio
    public_ratio = public_amount / total
    shielded_ratio = shielded_amount / total

    # Convert ratio to # of blocks
    pub_blocks = int(public_ratio * width)
    shd_blocks = int(shielded_ratio * width)

    # If rounding left out a block, fix that
    used = pub_blocks + shd_blocks
    if used < width:
        # Add leftover to shielded or whichever you prefer
        shd_blocks += (width - used)

    # Construct the bar string
    bar_str = (
        # Public block color
        f"{YELLOW}{'▅' * pub_blocks}"
        # Shielded block color
        f"{BLUE}{'▅' * shd_blocks}"
    )

    # Calculate and display the percentages
    pub_pct = public_ratio * 100
    shd_pct = shielded_ratio * 100

    # Format the percentages
    p_pct = f"{pub_pct:.2f}%"
    s_pct = f"{shd_pct:.2f}%"

    # Return the rendered bar with percentages
    return f"{YELLOW}{p_pct} {bar_str} {s_pct}"

def convert_to_float(value):
    """
    Tries to convert a string to a float. 
    If successful, returns the float. Otherwise, returns 0.0.
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
    
def remove_ansi(text):
    # Regular expression to match ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

async def execute_command_async(command=str(), log_output=True):
    """Execute a shell command asynchronously and return its output (stdout)."""
    try:
        if log_output:
            cmd2 = command
            if log_output:
                log_action("Executing Command", cmd2.replace(password,'#####'), "debug")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        stdout_str = stdout.decode().strip()
        stderr_str = stderr.decode().strip()

        if process.returncode != 0:
            log_action(f"Command failed with return code {process.returncode}:\n {command.replace(password,'#####')}", stderr_str.replace(password,'#####'),"error")
            return None # Or raise an exception
        else:
            if log_output and stdout_str:
                log_action(f"Command output", stdout_str.replace(password,'#####'), 'debug')
            return stdout_str.replace(password,'#####')
    except Exception as e:
        log_action(f"Error executing command: {command.replace(password,'#####')}", e, "error")
        return None

async def fetch_dusk_data():
    """
    Fetch DUSK token data from CoinGecko's /coins/markets endpoint and update shared_state.
    Logs an error if the request fails or data is incomplete.
    """
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",  # Convert price to USD
        "ids": "dusk-network",  # CoinGecko's ID for DUSK
        "order": "market_cap_desc",  # Sort by market cap
        "per_page": 1,
        "page": 1,
        "sparkline": "false",  # Do not include sparkline data
        "price_change_percentage": "1h,24h,7d,14d,30d,200d,1y",  # Include price change percentages
        "locale": "en",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    dusk_data = {}
                    if data:
                        dusk_data = data[0]  # Extract the first result for "dusk-network"
                        
                    # Update shared_state directly
                    shared_state["price"] = dusk_data.get("current_price", 0.0)
                    shared_state["market_cap"] = dusk_data.get("market_cap", 0.0)
                    shared_state["volume"] = dusk_data.get("total_volume", 0.0)
                    shared_state["usd_24h_change"] = dusk_data.get("price_change_percentage_24h", 0.0)
                    shared_state["market_cap_rank"] = dusk_data.get("market_cap_rank", None)
                    shared_state["circulating_supply"] = dusk_data.get("circulating_supply", None)
                    shared_state["total_supply"] = dusk_data.get("total_supply", None)
                    shared_state["ath"] = dusk_data.get("ath", 0.0)
                    shared_state["ath_change_percentage"] = dusk_data.get("ath_change_percentage", 0.0)
                    shared_state["price_change_percentage_1h"] = dusk_data.get("price_change_percentage_1h_in_currency", 0.0)
                    shared_state["last_updated"] = dusk_data.get("last_updated", "N/A")
                    shared_state["fully_diluted_valuation"] = dusk_data.get("fully_diluted_valuation", 0.0)
                    shared_state["high_24h"] = dusk_data.get("high_24h", 0.0)
                    shared_state["low_24h"] = dusk_data.get("low_24h", 0.0)
                    shared_state["price_change_24h"] = dusk_data.get("price_change_24h", 0.0)
                    shared_state["market_cap_change_24h"] = dusk_data.get("market_cap_change_24h", 0.0)
                    shared_state["market_cap_change_percentage_24h"] = dusk_data.get("market_cap_change_percentage_24h", 0.0)
                    shared_state["max_supply"] = dusk_data.get("max_supply", 0.0)
                    shared_state["ath_date"] = dusk_data.get("ath_date", 0.0)
                    shared_state["atl"] = dusk_data.get("atl", 0.0)
                    shared_state["atl_date"] = dusk_data.get("atl_date", 0.0)
                    shared_state["price_change_percentage_14d_in_currency"] = dusk_data.get("price_change_percentage_14d_in_currency", 0.0)
                    shared_state["price_change_percentage_1y_in_currency"] = dusk_data.get("price_change_percentage_1y_in_currency", 0.0)
                    shared_state["price_change_percentage_200d_in_currency"] = dusk_data.get("price_change_percentage_200d_in_currency", 0.0)
                    shared_state["price_change_percentage_24h_in_currency"] = dusk_data.get("price_change_percentage_24h_in_currency", 0.0)
                    shared_state["price_change_percentage_30d_in_currency"] = dusk_data.get("price_change_percentage_30d_in_currency", 0.0)
                    shared_state["price_change_percentage_7d_in_currency"] = dusk_data.get("price_change_percentage_7d_in_currency", 0.0)
                    shared_state["price_change_percentage_1h_in_currency"] = dusk_data.get("price_change_percentage_1h_in_currency", 0.0)
                    
                else:
                    log_action("Failed to fetch DUSK data", f"HTTP Status: {response.status}", 'debug')
    except Exception as e:
        log_action("Error while fetching DUSK data", str(e), 'debug')



def format_float(value, places=4):
    """Convert float to a string with max 4 (default) decimal digits."""
    parts = str(convert_to_float(value)).split('.')
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1][:places]}" if len(parts[1]) > 0 else parts[0]
    return parts[0]

def write_to_log(file_path, message):
    """
    Write a message to the specified log file.
    """
    try:
        with open(file_path, "a") as log_file:
            log_file.write(message + "\n")
    except Exception as e:
        # Handle potential errors during file writing, if necessary
        log_action(f"Error writing to log file {file_path}",e,"error")

def log_action(action="Action", details="No Details", type='info'):
    """
    Write log messages to specific files based on type.
    """
    
    # Create a timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Format the message
    formatted_message = LOG_FORMAT.format(timestamp=timestamp, message=f"{action}: {details}")
    
    formatted_message = formatted_message.replace(password, '#####').replace(password, '#####')
    if len(log_entries) > 15: # TODO: Make configurable
                log_entries.pop(0)
    
    # Write to the appropriate log file
    if type == 'debug' and enable_logging:
        if isDebug:
            write_to_log(DEBUG_LOG_FILE, formatted_message)
            return
    elif type == 'error' and enable_logging:
        if isDebug:
            write_to_log(DEBUG_LOG_FILE, formatted_message)
            
        log_entries.append(formatted_message)    
        write_to_log(ERROR_LOG_FILE, formatted_message)
    elif enable_logging:
        write_to_log(INFO_LOG_FILE, formatted_message)
        log_entries.append(formatted_message)
        
    notifier.notify(formatted_message, shared_state)
        
    

def parse_stake_info(output):
    """
    Parse the output of the 'rusk-wallet --password <password> stake-info' command and
    return a tuple containing the eligible stake, reclaimable slashed stake, and
    accumulated rewards.

    If any of the values are missing from the output, return a tuple of (None, None, 0.0).
    """
    try:
        lines = output.splitlines()
        eligible_stake = None  # Eligible stake for staking
        reclaimable_slashed_stake = None  # Reclaimable slashed stake (from penalties)
        accumulated_rewards = 0.0  # Accumulated rewards from staking

        for line in lines:
            line = line.strip()
            if "Eligible stake:" in line:
                # Example: "Eligible stake: 100.0 DUSK"
                match = re.search(r"Eligible stake:\s*([\d]+(?:\.\d+)?)\s*DUSK", line)
                if match:
                    eligible_stake = convert_to_float(match.group(1))
            elif "Reclaimable slashed stake:" in line:
                # Example: "Reclaimable slashed stake: 50.0 DUSK"
                match = re.search(r"Reclaimable slashed stake:\s*([\d]+(?:\.\d+)?)\s*DUSK", line)
                if match:
                    reclaimable_slashed_stake = convert_to_float(match.group(1))
            elif "Accumulated rewards is:" in line:
                # Example: "Accumulated rewards is: 10.0 DUSK"
                match = re.search(r"Accumulated rewards is:\s*([\d]+(?:\.\d+)?)\s*DUSK", line)
                if match:
                    accumulated_rewards = convert_to_float(match.group(1))
            elif "Stake active from block #" in line:
                # Example: "Stake active from block #123456"
                match = re.search(r"#(\d+)", line)
                if match:
                    stake_active_blk = int(match.group(1))
                    shared_state["active_blk"] = stake_active_blk

        if (eligible_stake is None or
            reclaimable_slashed_stake is None):
            # If we couldn't parse the stake-info output fully, log an error
            log_action("Incomplete stake-info values.",f"Could not parse fully.\n{lines}", "error")
            return None, None, 0.0

        # Return the parsed values
        return eligible_stake, reclaimable_slashed_stake, accumulated_rewards
    except Exception as e:
        log_action(f"Error parsing stake-info output: ",e,"error")
        return None, None, 0.0

async def get_wallet_balances(password, first_run=False):
    """
    Fetches the wallet balances for public and shielded addresses.

    1. Fetches addresses from 'rusk-wallet profiles'
    2. For each address, sums its spendable balances
    3. Detects and notifies if balances change for public or shielded amounts.
    """
    try:
        # Fetch address from 'rusk-wallet profiles'
        addresses = {
            "public": [],
            "shielded": []
        }

        cmd_profiles = f"{use_sudo} rusk-wallet --password {password} profiles"
        output_profiles = await execute_command_async(cmd_profiles)
        if not output_profiles:
            return 0.0, 0.0

        # Parse addresses
        for line in output_profiles.splitlines():
            line = line.strip()
            if "Shielded account" in line:
                match = re.search(r"Shielded account\s*-\s*(\S+)", line)
                if match:
                    addresses["shielded"].append(match.group(1))
            elif "Public account" in line:
                match = re.search(r"Public account\s*-\s*(\S+)", line)
                if match:
                    addresses["public"].append(match.group(1))
    except Exception as e:
        log_action(
            f"Error in get_wallet_balances(): ",
            str(e).replace(password, '#####'),
            "error"
        )
        await asyncio.sleep(5)
        return 0.0, 0.0

    async def get_spendable_for_address(addr):
        """
        Fetches the spendable balance for the given address
        """
        cmd_balance = f"{use_sudo} rusk-wallet --password {password} balance --spendable --address {addr}"
        try:
            out = await execute_command_async(cmd_balance)
            if out:
                total_str = out.replace("Total: ", "")
                return float(total_str)
        except Exception as e:
            if 'Connection to Rusk Failed' in str(e):
                log_action(
                    f"Error in get_spendable_for_address() reaching Node", f"{str(e).replace(password, '#####')}",
                    "error"
                )
            else:
                log_action(
                    f"Error in get_spendable_for_address()", f"{str(e).replace(password, '#####')}",
                    "error"
                )

        return 0.0

    tasks_public = [get_spendable_for_address(addr) for addr in addresses["public"]]
    tasks_shielded = [get_spendable_for_address(addr) for addr in addresses["shielded"]]

    results_public = await asyncio.gather(*tasks_public)
    results_shielded = await asyncio.gather(*tasks_shielded)

    new_public_total = sum(results_public)
    new_shielded_total = sum(results_shielded)

    # Check for balance changes
    old_public_total = shared_state.get("balances", {}).get("public", 0.0)
    old_shielded_total = shared_state.get("balances", {}).get("shielded", 0.0)

    if (float(format_float(old_public_total + old_shielded_total)) != float(format_float(new_public_total + new_shielded_total))) and monitor_wallet and not first_run:
        if new_public_total != old_public_total:
            log_action(
                "Balance Change Detected",
                f"Public balance changed from {format_float(old_public_total)} → {format_float(new_public_total)} DUSK.",
                "info"
            )

        if new_shielded_total != old_shielded_total:
            log_action(
                "Balance Change Detected",
                f"Shielded balance changed from {format_float(old_shielded_total)} → {format_float(new_shielded_total)} DUSK.",
                "info"
            )

    # Update shared_state
    shared_state["balances"]["public"] = new_public_total
    shared_state["balances"]["shielded"] = new_shielded_total

    return new_public_total, new_shielded_total

def calculate_rewards_per_epoch(rewards_amount, last_claim_block, current_block):
    """Estimate how many rewards are generated per epoch (2160 blocks) since last claim."""
    
    blocks_elapsed = current_block - last_claim_block
    epochs_elapsed = blocks_elapsed / 2160
    if epochs_elapsed > 0:
        return rewards_amount / epochs_elapsed
    return 0.0

def calculate_downtime_loss(rewards_per_epoch, downtime_epochs=1):
    """Calculate downtime loss for unstaking and restaking."""
    return rewards_per_epoch * downtime_epochs

def should_unstake_and_restake(reclaimable_slashed_stake, downtime_loss):
    """Determine if unstaking/restaking is worthwhile."""
    return auto_reclaim_full_restakes and (reclaimable_slashed_stake >= config.get('min_slashed',1) and reclaimable_slashed_stake >= downtime_loss)

def should_claim_and_stake(rewards, incremental_threshold):
    """Determine if claiming and staking rewards is worthwhile."""
    return auto_stake_rewards and (rewards >= config.get('min_rewards',1) and rewards >= incremental_threshold)

def format_hms(seconds):
    """
    Given an integer number of seconds, return a string like "1h 20m 5s"
    skipping any 0 values. Always show seconds for less jittery feedback.
    """
    h = seconds // 3600
    remainder = seconds % 3600
    m = remainder // 60
    s = remainder % 60

    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s" if s > 9 else f"{s}s ")  # always include seconds
    return ' '.join(parts)


    

async def sleep_with_feedback(seconds_to_sleep, msg=None):
    """
    Asynchronous version of sleep with visual feedback.
    Updates shared_state['remain_time'] for real-time display.
    """
    completion_time = (datetime.now() + timedelta(seconds=seconds_to_sleep)).strftime('%H:%M')

    shared_state["remain_time"] = seconds_to_sleep
    shared_state["completion_time"] = "@ " + completion_time
    
    while shared_state["remain_time"] > 0:
        interval = min(1, shared_state["remain_time"])
        
        await asyncio.sleep(interval)
        shared_state["remain_time"] -= interval
        

async def sleep_until_next_epoch(block_height, buffer_blocks=60, msg=None):
    """
    Sleep until near the end of the current epoch.
    Each epoch is 2160 blocks, 10s each. Subtract buffer_blocks from remainder.
    If result <= 0, do a minimal sleep of buffer blocks * 11.
    """
    if not msg:
        msg = "until closer to next epoch..."

    blocks_left = 2160 - (block_height % 2160) - buffer_blocks
    sleep_time = blocks_left * 10  # 10s per block

    if sleep_time <= 0:
        sleep_time = buffer_blocks * 11
        msg = "Epoch boundary reached; forcing minimal sleep."

    await sleep_with_feedback(sleep_time, msg)

# def minutes_until_next_epoch(block_height, buffer_blocks=60):
#     """
#     Return how many whole minutes remain until next epoch minus buffer_blocks.
#     """
#     blocks_left = 2160 - (block_height % 2160) - buffer_blocks
#     total_seconds = max(blocks_left * 10, 0)
#     return total_seconds // 60


# ─────────────────────────────────────────────────────────────────────────────
# FREQUENT UPDATE LOOP (every 10 seconds) for display
# ─────────────────────────────────────────────────────────────────────────────

async def frequent_update_loop():
    """
    Update the block height and balances every 20 seconds.
    Checks if the block height changes to ensure node responsiveness.
    """

    loopcnt = 0
    consecutive_no_change = 0  # Counter for consecutive no-change in block height
    last_known_block_height = None  # Track the last block height
    consecutive_low_peers = 0 # Track loops of low peer counts
    
    while True:
            
            # 1) Fetch block height
            block_height_str = await execute_command_async(f"{use_sudo} ruskquery block-height", False)
            if not block_height_str:
                log_action("Failed to fetch block height.", ' Retrying in 10s...', "error")
                await asyncio.sleep(10)
                continue
            
            current_block_height = int(block_height_str)
            
            # Compare with last known block height
            if last_known_block_height is not None:
                if current_block_height == last_known_block_height:
                    consecutive_no_change += 1
                else:
                    consecutive_no_change = 0  # Reset counter if block height changes
            else:
                consecutive_no_change = 0  # Reset counter on first valid block height
            
            # Log and notify if block height hasn't changed for 10 loops (100 seconds)
            if consecutive_no_change >= 10:
                message = f"WARNING! Block height has not changed for {consecutive_no_change * 10} seconds.\nLast height: {last_known_block_height}"
                log_action("Block Height Error!", message,"error")
                
                consecutive_no_change = 0  # Reset after notifying to avoid spamming
                await asyncio.sleep(1)
                continue # Need to double check this

            # Update last known block height and shared state
            last_known_block_height = current_block_height
            shared_state["block_height"] = current_block_height
            
            # Perform balance and stake-info updates every X  loops (e.g., 30 is 5 minutes)
            if loopcnt >= 20 and not stake_checking:
                pub_bal, shld_bal = await get_wallet_balances(password)
                shared_state["balances"]["public"] = pub_bal or 0.0
                shared_state["balances"]["shielded"] = shld_bal or 0.0
                
                stake_output = await execute_command_async(f"{use_sudo} rusk-wallet --password {password} stake-info")
                if stake_output:
                    e_stake, r_slashed, a_rewards = parse_stake_info(stake_output)
                    shared_state["stake_info"]["stake_amount"] = e_stake or 0.0
                    shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed or 0.0
                    shared_state["stake_info"]["rewards_amount"] = a_rewards or 0.0
                
                await fetch_dusk_data()  
                    
                loopcnt = 0  # Reset loop count after update
            
            
            shared_state["peer_count"] = await execute_command_async(f"{use_sudo} ruskquery peers", False)
            peer_count = int(shared_state["peer_count"])
            
            if not peer_count:
                log_action("Failed to fetch peers.", "Retrying in 10s...", "error")
                await asyncio.sleep(10)
                continue
            
            # check peer count
            if peer_count is not None:
                if peer_count < min_peers or peer_count <=0:
                    consecutive_low_peers += 1
                else:
                    consecutive_low_peers = 0  # Reset counter if block height changes
            else:
                consecutive_low_peers = 0  # Reset counter on first valid block height
            
            # Log and notify if low count for too long
            if consecutive_low_peers >= 240:
                message = f"WARNING! Low peer count for {consecutive_low_peers * 10} seconds.\nCurrent Count: {peer_count}"
                log_action("Low peer count!", message, "error")
                
                consecutive_low_peers = 0  # Reset after notifying to avoid spamming

            loopcnt += 1
            await asyncio.sleep(10)  # Wait 10 seconds before the next loop

async def init_balance():
    """
        Init display values
    """
    
    await fetch_dusk_data() # grab data from Coingecko

    # Fetch block height
    block_height_str = await execute_command_async(f"{use_sudo} ruskquery block-height", False)
    if block_height_str:
        shared_state["block_height"] = int(block_height_str)
    # Fetch wallet balances
    pub_bal, shld_bal = await get_wallet_balances(password, True)
    shared_state["balances"]["public"] = pub_bal
    shared_state["balances"]["shielded"] = shld_bal
    

# ─────────────────────────────────────────────────────────────────────────────
# STAKE MANAGEMENT LOOP
# ─────────────────────────────────────────────────────────────────────────────

async def stake_management_loop():
    """
    Main staking logic. Sleeps until the next epoch after each action/no-action.
    Meanwhile, frequent_update_loop updates block height & balances for display.
    """

    first_run = True

    while True:
        try:
            stake_checking = True     
            # For logic, we may want a fresh block height right before we do anything:
            block_height_str = await execute_command_async(f"{use_sudo} ruskquery block-height", False)
            if not block_height_str:
                log_action("Failed to fetch block height", "Retrying in 30s...", "error")
                stake_checking = False
                await sleep_with_feedback(30, "retry block height fetch")
                
                continue

            block_height = int(block_height_str)
            shared_state["block_height"] = block_height

            # If we already saw 'No Action' for this block, wait a bit
            if shared_state["last_no_action_block"] == block_height:
                msg = f"Already did 'No Action' at block {block_height}; sleeping 30s."
                stake_checking = False
                await sleep_with_feedback(30, msg)
                continue

            # Fetch stake-info
            stake_output = await execute_command_async(f"{use_sudo} rusk-wallet --password {password} stake-info")
            if not stake_output:
                log_action("Error", "Failed to fetch stake-info. Retrying in 60s...", "error")
                stake_checking = False
                await sleep_with_feedback(30, "retry stake-info fetch")
                continue

            e_stake, r_slashed, a_rewards = parse_stake_info(stake_output)
            if e_stake is None or r_slashed is None or a_rewards is None:
                log_action("Skiping Cycle","Parsing stake info failed or incomplete. Skipping cycle...", 'debug')
                stake_checking = False
                await sleep_with_feedback(60, "skipping cycle")
                continue
            
            
            # Update in shared state
            shared_state["stake_info"]["stake_amount"] = e_stake
            shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed
            shared_state["stake_info"]["rewards_amount"] = a_rewards

            stake_checking = False
            # For logic thresholds
            last_claim_block = shared_state["last_claim_block"]
            stake_amount = e_stake or 0.0
            reclaimable_slashed_stake = r_slashed or 0.0
            rewards_amount = a_rewards or 0.0

            rewards_per_epoch = calculate_rewards_per_epoch(rewards_amount, last_claim_block, block_height)
            shared_state["rewards_per_epoch"] = rewards_per_epoch
            downtime_loss = calculate_downtime_loss(rewards_per_epoch, downtime_epochs=2)
            incremental_threshold = rewards_per_epoch
            total_restake = stake_amount + rewards_amount + reclaimable_slashed_stake
            
            # Should this check first run and wait till first epoch? need to test
            if should_unstake_and_restake(reclaimable_slashed_stake, downtime_loss) and not first_run and reclaimable_slashed_stake and e_stake > 0:
                if total_restake < min_stake_amount:
                    shared_state["last_action_taken"] = "Unstake/Restake Skipped (Below Min)"
                    log_action(
                        f"Unstake/Restake Skipped (Block #{block_height})",
                        f"Total restake ({format_float(total_restake)} DUSK) < {min_stake_amount} DUSK.\nRwd: {format_float(rewards_amount)}, Stk: {format_float(stake_amount)}, Rcl: {format_float(reclaimable_slashed_stake)}"
                    )
                    stake_checking = False
                else:
                    # Unstake & Restake
                    act_msg = f"Start Unstake/Restake @ Block #{block_height}"
                    shared_state["last_action_taken"] = act_msg
                    
                    log_action(act_msg,
                        f"Rwd: {format_float(rewards_amount)}, Stake: {format_float(stake_amount)}, Rcl: {format_float(reclaimable_slashed_stake)}\nReclaimable: {format_float(reclaimable_slashed_stake)}, Downtime Loss: {format_float(downtime_loss)}"
                    )
                    
                    # 1) Withdraw
                
                    curr_cmd = f"{use_sudo} rusk-wallet --password ####### withdraw"
                    curr2 = curr_cmd
                    cmd_success = await execute_command_async(curr_cmd.replace('#######',password))
                    if not cmd_success:
                        log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr2}", 'error')
                        raise Exception("CMD execution failed")
                    if 'Withdrawing 0 reward is not allowed' in cmd_success:
                        rewards_amount = 0.0
                    
                    # 2) Unstake
                
                    curr_cmd =f"{use_sudo} rusk-wallet --password ####### unstake"
                    curr2 = curr_cmd
                    cmd_success = await execute_command_async(curr_cmd.replace('#######',password))
                    if not cmd_success or 'rror' in cmd_success:
                        log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr2}", 'error')
                        raise Exception("CMD execution failed")
                    
                    # 3) Stake
                    total_restake = stake_amount + rewards_amount + reclaimable_slashed_stake
                    curr_cmd = f"{use_sudo} rusk-wallet --password ####### stake --amt {total_restake}"
                    curr2 = curr_cmd
                    cmd_success = await execute_command_async(curr_cmd.replace('#######', password))
                    if not cmd_success or 'rror' in cmd_success:
                        log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr2}", 'error')
                        raise Exception("CMD execution failed")

                    log_action("Restake Completed", f"New Stake: {format_float(float(total_restake))}")
                    shared_state["last_claim_block"] = block_height

                    stake_checking = False
                    # Sleep 2 epochs
                    await sleep_until_next_epoch(block_height + 2160, msg="2-epoch wait after restaking...")
                    continue

            elif should_claim_and_stake(rewards_amount, incremental_threshold) and not first_run:
                # Claim & Stake
                shared_state["last_action_taken"] = f"Claim/Stake @ Block {block_height}"
                log_action(
                    shared_state["last_action_taken"],
                    f"Rwd: {format_float(rewards_amount)}, Stk: {format_float(stake_amount)}, Rcl: {format_float(reclaimable_slashed_stake)}"
                )

                # 1) Withdraw
                
                curr_cmd = f"{use_sudo} rusk-wallet --password ####### withdraw"
                curr2 = curr_cmd
                cmd_success = await execute_command_async(curr_cmd.replace('#######',password))
                if not cmd_success or 'rror' in cmd_success:
                        log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr2}", 'error')
                        raise Exception("CMD execution failed")
                    
                # 2) Stake
                
                curr_cmd = f"{use_sudo} rusk-wallet --password ####### stake --amt {rewards_amount}"
                curr2 = curr_cmd
                cmd_success = await execute_command_async(curr_cmd.replace('#######',password))
                if not cmd_success or 'rror' in cmd_success:
                        log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr2}", 'error')
                        raise Exception("CMD execution failed")
                    
                new_stake = stake_amount + rewards_amount

                log_action("Stake Completed", f"New Stake: {format_float(new_stake)}")
                shared_state["last_claim_block"] = block_height
                stake_checking = False
                await sleep_with_feedback(2160 * 10, "1 epoch wait after claiming")
                continue
            else:
                # No action
                shared_state["last_no_action_block"] = block_height
                shared_state["last_action_taken"] = f"No Action @ Block {block_height}"
                
                b = shared_state["balances"]
                now_ts = datetime.now().strftime('%Y-%m-%d %H:%M')
                
                # block_height = shared_state["block_height"]
                if first_run:
                    shared_state["last_action_taken"] = f"Startup @ Block #{block_height}"
                    first_run = False
                else:
                    stake_checking = False
                    # If no action, just wait and don't log since it's no longer first run
                    await sleep_until_next_epoch(block_height, buffer_blocks=buffer_blocks)
                    continue    
                
            action = shared_state["last_action_taken"]
            Log_info = (
            f"\t==== Activity @{now_ts}====\n"
            f"  Action              :  {action}\n\n"
            f"  Balance           :  {format_float(b['public'] + b['shielded'],)}\n"
            f"    ├─ Public      :    {format_float(b['public'])} (${format_float(b['public'] * float(shared_state["price"]))})\n"
            f"    └─ Shielded  :    {format_float(b['shielded'])} (${format_float(b['shielded'] * float(shared_state["price"]))})\n\n"
            f"  Staked              :  {format_float(shared_state.get('stake_info',{}).get('stake_amount','0.0'))} (${format_float(shared_state.get('stake_info',{}).get('stake_amount','0.0') * float(shared_state["price"]))})\n"
            f"  Rewards           :  {format_float(shared_state.get('stake_info',{}).get('rewards_amount','0.0'))} (${format_float(shared_state.get('stake_info',{}).get('rewards_amount',{}) * float(shared_state["price"]))})\n"
            f"  Reclaimable    :  {format_float(shared_state.get('stake_info',{}).get('reclaimable_slashed_stake','0.0'))} (${format_float(shared_state.get('stake_info',{}).get('reclaimable_slashed_stake') * float(shared_state["price"]))})\n"
                )
            
            if len(log_entries) > 15: # TODO: Make configurable
                log_entries.pop(0)
            log_entries.append(Log_info)
            notifier.notify(Log_info, shared_state) # 
            
            first_run = False
            stake_checking = False
        except Exception as e:
                stake_checking = False
                log_action("Error in stake management loop", e, "error")
                raise Exception("Error in stake management loop")
        # Sleep until near the next epoch
        stake_checking = False
        await sleep_until_next_epoch(block_height, buffer_blocks=buffer_blocks)


# ─────────────────────────────────────────────────────────────────────────────
# REAL-TIME DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

async def realtime_display(tmux=False):
    """
    Continuously display real-time info in the console.
    Initially shows configuration and byline, then switches to real-time stats.
    """
    first_run = True
    enable_tmux = tmux

    with Live(console=console, refresh_per_second=4, auto_refresh=False) as live:
        while True:
            try:
                blk = shared_state["block_height"]
                st_info = shared_state["stake_info"]
                b = shared_state["balances"]
                last_act = shared_state["last_action_taken"]
                remain_seconds = shared_state["remain_time"]
                disp_time = format_hms(remain_seconds) if remain_seconds > 0 else "0s"
                donetime = shared_state["completion_time"]
                if donetime == '--:--':
                    await asyncio.sleep(2)
                    continue
                tot_bal = b["public"] + b["shielded"]
                price = shared_state["price"]
                
                charclr =str()
                charclr = (
                    RED if remain_seconds <= 3600 else
                    YELLOW if remain_seconds <= 7200 else
                    GREEN if remain_seconds <= 10800 else
                    LIGHT_WHITE
                )
                    
                timer = f"Next:{charclr} {disp_time} "
                chg24 = f"{GREEN if shared_state['usd_24h_change'] > 0 else RED if shared_state['usd_24h_change'] < 0 else DEFAULT}{shared_state['usd_24h_change']:.2f}% 24h"
                usd = f"$USD: {format_float(shared_state['price'],3)} {chg24} | "
                
                peercolor = next(
                    color for color, condition in {
                        RED: lambda x: x <= 16,
                        YELLOW: lambda x: 16 < x <= 40,
                        LIGHT_GREEN: lambda x: x > 40
                    }.items() if condition(int(shared_state['peer_count']))
)

                currenttime = datetime.now().strftime('%H:%M:%S')
                epoch_num = int(blk / 2160)
                
                active_block = shared_state.get("active_blk", 2160)
                if int(blk) - active_block >= 0:
                    is_active = str() 
                    
                else:
                    active_secs = (active_block - blk) * 10
                    when_active = (datetime.now() + timedelta(seconds=active_secs)).strftime('%H:%M')
                    is_active = f"{LIGHT_RED}\n\tActive @ {when_active} - #{active_block} (E: {int(active_block/2160)}){DEFAULT}\n"               
                
                chg7d = shared_state["price_change_percentage_7d_in_currency"]
                chg30d = shared_state["price_change_percentage_30d_in_currency"]
                chg1y = shared_state["price_change_percentage_1y_in_currency"]
                
                ## Currently unused ##
                chg14d = shared_state["price_change_percentage_14d_in_currency"]
                chg1hr = shared_state["price_change_percentage_1h_in_currency"]
                
                volume = shared_state["volume"]
                
                mkt_cap = shared_state["market_cap"]
                mkt_cap_change = shared_state["market_cap_change_percentage_24h"]
                
                ath = shared_state["ath"]
                ath_change = shared_state["ath_change_percentage"]
                ath_date = shared_state["ath_date"]
                
                atl = shared_state["atl"]
                atl_date = shared_state["atl_date"]
                
                ######################
                
                top_bar = f" {LIGHT_WHITE}======={DEFAULT} {currenttime} Block: {LIGHT_BLUE}#{blk} {DEFAULT}(E: {LIGHT_BLUE}{epoch_num}{DEFAULT}) Peers: {peercolor}{shared_state['peer_count']}{DEFAULT} {LIGHT_WHITE}=======\n"
                title_spaces = int((len(remove_ansi(top_bar)) - len(remove_ansi(byline))) / 2)

                opts = '\n' + (' ' * title_spaces) + BLUE  + shared_state["options"]
                
                allocation_bar = display_wallet_distribution_bar(b['public'],b['shielded'],8)
                
                per_epoch = str()
                rpe = convert_to_float(shared_state.get('rewards_per_epoch',0.0))
                if  rpe > 0.0: # Check if we have a ~ rewards per epoch since last claim
                    if int(shared_state.get("last_claim_block", 0)) > 0:
                        per_epoch = f"@ Epoch/claim: {format_float(rpe)}"
                    # else:
                    #     per_epoch = f"Since startup: {format_float(rpe * epoch_num)}"
                
                reward_percent = 0.0
                if st_info.get('rewards_amount',0.0) > 0.0 and st_info.get('stake_amount', 0.0) > 0.0:
                    reward_percent = (st_info.get('rewards_amount',0.0) / st_info.get('stake_amount', 0.0)) * 100
                
                realtime_content = (
                    f"{opts}\n"
                    f"{top_bar}"
                    f"    {CYAN}Last Action{DEFAULT}   | {CYAN}{last_act}{DEFAULT}\n"
                    f"    {LIGHT_GREEN}Next Check    {DEFAULT}| {charclr}{disp_time}{DEFAULT} ({donetime}){DEFAULT}\n"
                    f"                  |\n"
                    f"    {LIGHT_WHITE}Price USD{DEFAULT}     | {LIGHT_WHITE}${format_float(price,3)}{DEFAULT} {chg24}\n"
                    f"                  {DEFAULT}| 7d: {chg7d:.2f}% 30d: {chg30d:.2f}% 1y: {chg1y:.2f}%\n"
                    f"                  |\n"
                    f"    {LIGHT_WHITE}Balance{DEFAULT}       | {LIGHT_WHITE}{allocation_bar}\n"
                    f"      {LIGHT_WHITE}├─ {YELLOW}Public   {DEFAULT}| {YELLOW}{format_float(b['public'])} (${format_float(b['public'] * price, 2)}){DEFAULT}\n"
                    f"      {LIGHT_WHITE}└─ {BLUE}Shielded {DEFAULT}| {BLUE}{format_float(b['shielded'])} (${format_float(b['shielded'] * price, 2)}){DEFAULT}\n"
                    f"         {LIGHT_WHITE}   Total {DEFAULT}| {LIGHT_WHITE}{format_float(tot_bal)} DUSK (${format_float((tot_bal) * price, 2)}){DEFAULT}\n"
                    f"                  |\n"
                    f"    {LIGHT_WHITE}Staked{DEFAULT}        | {LIGHT_WHITE}{format_float(st_info['stake_amount'])} (${format_float(st_info['stake_amount'] * price, 2)}){DEFAULT}{is_active}\n"
                    f"    {YELLOW}Rewards{DEFAULT}       | {YELLOW}{format_float(st_info['rewards_amount'])} ({LIGHT_BLUE}{reward_percent:.4f}%{DEFAULT}) (${format_float(st_info['rewards_amount'] * price, 2)}) {LIGHT_WHITE}{per_epoch}{DEFAULT}\n"
                    f"    {LIGHT_RED}Reclaimable{DEFAULT}   | {LIGHT_RED}{format_float(st_info['reclaimable_slashed_stake'])} (${format_float(st_info['reclaimable_slashed_stake'] * price, 2)}){DEFAULT}\n"
                    f" {LIGHT_WHITE}{('=' * (len(remove_ansi(top_bar)) - 2))}{DEFAULT}\n"  
                )
                
                if include_rendered:
                    shared_state["rendered"] = realtime_content
                else:
                    shared_state["rendered"] = None
                
                
                # Update the Live display
                if display_gui:
                    live.update(Text(realtime_content), refresh=True)

                # Update TMUX status bar

                if enable_tmux:
                    try:
                        curblk = f"\r> Blk: #{blk} | "
                        stk = f"Stk: {format_float(st_info['stake_amount'])} | "
                        rcl = f"Rcl: {format_float(st_info['reclaimable_slashed_stake'])} | "
                        rwd = f"Rwd: {format_float(st_info['rewards_amount'])} | "
                        bal = "Bal: "
                        p = f"P:{format_float(b['public'])}"
                        s = f"S:{format_float(b['shielded'])}"
                        
                        fields = {
                            'curblk': status_bar.get('show_current_block', True),
                            'stk': status_bar.get('show_staked', True),
                            'p': status_bar.get('show_public', True),
                            's': status_bar.get('show_shielded', True),
                            'bal': status_bar.get('show_total', True),
                            'rwd': status_bar.get('show_rewards', True),
                            'rcl': status_bar.get('show_reclaimable', True),
                            'usd': status_bar.get('show_price', True),
                            'timer': status_bar.get('show_timer', True),
                            'donetime': status_bar.get('show_trigger_time', True),
                            'peercnt': status_bar.get('show_peer_count', True)
                        }

                        for key, show in fields.items():
                            if not show:
                                locals()[key] = str()

                        if not fields['p'] and not fields['s']:
                            bal = splitter = str()
                        if fields['p'] and fields['s']:
                            spacer = "  "

                        error_txt = "- !ERROR DETECTED!" if errored else str()
                        last_txt = str()  # last_act
                        donetime = f"{DEFAULT}({shared_state['completion_time']}) "
                        peercnt = f"Peers: {shared_state['peer_count']}"
                        splitter = " | "
                        tmux_status = (
                            f"\r> {curblk}{stk}{rcl}{rwd}{bal}{p}{spacer}{s}{splitter}"
                            f"{usd}{last_txt}{timer}{donetime}{peercnt} {error_txt}"
                        )

                        subprocess.check_call(["tmux", "set-option", "-g", "status-left", remove_ansi(tmux_status)])
                    except subprocess.CalledProcessError:
                        log_action("tmux Error", "Failed to update tmux status bar. Is tmux running?", "debug")
                        enable_tmux = False

                await asyncio.sleep(1)

            except Exception as e:
                log_action(f"Error in real-time display", e, "error")
                await asyncio.sleep(5)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():

    # Helper function to colorize boolean values
    def colorize_bool(value):
        return f"{GREEN}True{DEFAULT}" if value else f"{RED}False{DEFAULT}"

    # Ensure balances are initialized for display
    await init_balance()

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
    enable_webdash = bool(dash_ip and dash_port and enable_dashboard)

    # Build the status messages
    notification_status = f'Enabled Notifications:{YELLOW}   {services}\n'
    
    auto_status = (
        f'\n\t{LIGHT_WHITE}Enable Web Dashboard:{DEFAULT}    {colorize_bool(enable_webdash)}'
        f'\n\t{LIGHT_WHITE}Enable tmux Support:{DEFAULT}     {colorize_bool(enable_tmux)}'
        f'\n\t{LIGHT_WHITE}Auto Staking Rewards:{DEFAULT}    {colorize_bool(auto_stake_rewards)}'
        f'\n\t{LIGHT_WHITE}Auto Restake to Reclaim:{DEFAULT} {colorize_bool(auto_reclaim_full_restakes)}'
        f'\n\t{LIGHT_WHITE}{notification_status}'
    )
    separator = f"       {LIGHT_WHITE}{("=" * len(byline))}{DEFAULT}"

    # Update shared state with options display
    
    if config.get('display_options', True):
        shared_state["options"] = byline + '\n'+ separator + auto_status
    else:
        shared_state["options"] = byline 

    if enable_webdash:
        from utilities.web_dashboard import start_dashboard
    await start_dashboard(shared_state, log_entries, host=dash_ip, port=dash_port) 
    
    await asyncio.gather(
        frequent_update_loop(),
        realtime_display(enable_tmux),
        stake_management_loop(),
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nCTRL-C detected. Exiting gracefully.\n")
        sys.exit(0)
