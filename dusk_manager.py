import os
import sys
import subprocess
import re
import logging
import datetime
import yaml
import asyncio
import aiohttp

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import print
from utilities.notifications import NotificationService

import utilities.conf as c

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
        logging.error(f"Configuration file {file_path} not found. Exiting.")
        sys.exit(1)
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML file {file_path}: {e}")
        sys.exit(1)

# Load configuration
config = load_config('GENERAL')
notification_config = load_config('NOTIFICATIONS')
status_bar = load_config('STATUSBAR')
web_dashboard = load_config('WEB_DASHBOARD')

min_rewards = config.get('min_rewards', 1)
min_slashed = config.get('min_slashed', 1)
buffer_blocks = config.get('buffer_blocks', 60)
min_stake_amount = config.get('min_stake_amount', 1000)
min_peers = config.get('min_peers', 10)
auto_stake_rewards = config.get('auto_stake_rewards', False)
auto_reclaim_full_restakes = config.get('auto_reclaim_full_restakes', False)
pwd_var = config.get('pwd_var_name', 'MY_WALLET_VARIABLE')
enable_dashboard = web_dashboard.get('enable_dashboard', True)
dash_port = web_dashboard.get('dash_port')
dash_ip = web_dashboard.get('dash_ip', '0.0.0.0')

if config.get('use_sudo', False):
    use_sudo = 'sudo'
else:
    use_sudo = ''

errored = False
log_entries = []

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
    "first_run": True,
    "completion_time": "--:--",
    "peer_count": 0,
    "price":0.0,
    "market": 0,
    "volume": 0,
    "usd_24h_change": 0,
}

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING CONFIG
# ─────────────────────────────────────────────────────────────────────────────

LOG_FILE = "actions.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE)
    ]
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
def get_env_variable(var_name='WALLET_PASSWORD', dotenv_key='WALLET_PASSWORD'):
    """
    Retrieve an environment variable or a fallback value from .env file.
    """
    value = os.getenv(var_name)
    if not value:
        # logging.warning(f"Environment variable '{var_name}' not found. Checking .env file...")
        value = os.getenv(dotenv_key)
        if not value:
            logging.error(f"Neither environment variable '{var_name}' nor .env key '{dotenv_key}' found for wallet password.")
            sys.exit(1)
            
    return value

password = get_env_variable(config.get('pwd_var_name', 'WALLET_PASSWORD'), dotenv_key="WALLET_PASSWORD")


def display_wallet_distribution_bar(public_amount, shielded_amount, width=30):
    """
    Displays a single horizontal bar (ASCII blocks) with two colored segments:

    :param public_amount: float, the public balance
    :param shielded_amount: float, the shielded balance
    :param width: int, total number of blocks in the bar
    """
    total = public_amount + shielded_amount
    if total <= 0:
        console.print("[bold yellow]No funds found (total=0).[/bold yellow]")
        return

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

    
    bar_str = (
        f"{YELLOW}{'▅' * pub_blocks}"
        f"{BLUE}{'▅' * shd_blocks}"
    )
    
    bar_str2 = (
        f"{BLUE}{'▅' * shd_blocks}"
        f"{YELLOW}{'▅' * pub_blocks}"
    )

    # Display the percentages
    pub_pct = public_ratio * 100
    shd_pct = shielded_ratio * 100
    
    return f"{YELLOW}{pub_pct:6.2f}% {bar_str} {BLUE}{shd_pct:6.2f}%"
        
    

def remove_ansi(text):
    # Regular expression to match ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

async def execute_command_async(command, log_output=True):
    """Execute a shell command asynchronously and return its output (stdout)."""
    try:
        if log_output:
            logging.debug(f"Executing command: {command}")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        stdout_str = stdout.decode().strip()
        stderr_str = stderr.decode().strip()

        if process.returncode != 0:
            logging.error(f"Command failed with return code {process.returncode}: {command}\n{stderr_str}")
            return None # Or raise an exception
        else:
            if log_output and stdout_str:
                logging.debug(f"Command output: {stdout_str}")
            return stdout_str
    except Exception as e:
        logging.error(f"Error executing command: {command}\n{e}")
        return None


async def fetch_dusk_data():
    """
    Fetch DUSK token data from CoinGecko API.
    Returns a dictionary with relevant data or logs an error if the request fails.
    """
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "dusk-network",  # CoinGecko's ID for DUSK
        "vs_currencies": "usd",  # Fetch price in USD
        "include_market_cap": "true",
        "include_24hr_vol": "true",
        "include_24hr_change": "true",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    dusk_data = data.get("dusk-network", {})
                    return dusk_data
                else:
                    logging.debug(f"Failed to fetch DUSK data. HTTP Status: {response.status}")
                    return None
    except Exception as e:
        logging.debug(f"Error while fetching DUSK data: {e}")
        return None


def format_float(value, places=4):
    """Convert float to a string with max 4 decimal digits."""
    parts = str(value).split('.')
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1][:places]}" if len(parts[1]) > 0 else parts[0]
    return parts[0]

def log_action(action, details, type='info'):
    """Log actions to file/console and send notifications."""
    notifier.notify(f"{action}: {details}", shared_state)
    
    if type == 'debug':
        logging.debug(f"\n{action}: {details}")
    elif type == 'error':
        logging.error(f"\n{action}: {details}")    
    else:
        logging.info(f"\n{action}: {details}")

def parse_stake_info(output):
    """
    Parse 'stake-info' output and return (eligible_stake, reclaimable_slashed_stake, accumulated_rewards).
    If any is missing, return (None, None, None).
    """
    try:
        lines = output.splitlines()
        eligible_stake = None
        reclaimable_slashed_stake = None
        accumulated_rewards = None

        for line in lines:
            line = line.strip()
            if "Eligible stake:" in line:
                match = re.search(r"Eligible stake:\s*([\d\.]+)\s*DUSK", line)
                if match:
                    eligible_stake = float(match.group(1))
            elif "Reclaimable slashed stake:" in line:
                match = re.search(r"Reclaimable slashed stake:\s*([\d\.]+)\s*DUSK", line)
                if match:
                    reclaimable_slashed_stake = float(match.group(1))
            elif "Accumulated rewards is:" in line:
                match = re.search(r"Accumulated rewards is:\s*([\d\.]+)\s*DUSK", line)
                if match:
                    accumulated_rewards = float(match.group(1))

        if (eligible_stake is None or
            reclaimable_slashed_stake is None or
            accumulated_rewards is None):
            logging.warning("Incomplete stake-info values. Could not parse fully.")
            return None, None, None

        return eligible_stake, reclaimable_slashed_stake, accumulated_rewards
    except Exception as e:
        logging.error(f"Error parsing stake-info output: {e}")
        return None, None, None

async def get_wallet_balances(password):
    """
    1) Fetch addresses from 'rusk-wallet profiles'
    2) For each address, sum its spendable balances
    Return (public_total, shielded_total).
    """
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

    async def get_spendable_for_address(addr):
        cmd_balance = f"{use_sudo} rusk-wallet --password {password} balance --spendable --address {addr}"
        out = await execute_command_async(cmd_balance)
        if out:
            total_str = out.replace("Total: ", "")
            try:
                return float(total_str)
            except:
                return 0.0
        return 0.0

    tasks_public = [get_spendable_for_address(addr) for addr in addresses["public"]]
    tasks_shielded = [get_spendable_for_address(addr) for addr in addresses["shielded"]]

    results_public = await asyncio.gather(*tasks_public)
    results_shielded = await asyncio.gather(*tasks_shielded)

    return sum(results_public), sum(results_shielded)

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
    return auto_reclaim_full_restakes and (reclaimable_slashed_stake > config.get('min_slashed',1) and reclaimable_slashed_stake >= downtime_loss)

def should_claim_and_stake(rewards, incremental_threshold):
    """Determine if claiming and staking rewards is worthwhile."""
    return auto_stake_rewards and (rewards > config.get('min_rewards',1) and rewards >= incremental_threshold)

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
    parts.append(f"{s}s")  # always include seconds
    return ' '.join(parts)


    

async def sleep_with_feedback(seconds_to_sleep, msg=None):
    """
    Asynchronous version of sleep with visual feedback.
    Updates shared_state['remain_time'] for real-time display.
    """
    completion_time = (datetime.datetime.now() + datetime.timedelta(seconds=seconds_to_sleep)).strftime('%H:%M')

    shared_state["remain_time"] = seconds_to_sleep
    shared_state["completion_time"] = "@ " + completion_time
    
    while shared_state["remain_time"] > 0:
        interval = min(1, shared_state["remain_time"])
        
        await asyncio.sleep(interval)
        shared_state["remain_time"] -= interval

    # Optionally clear or log
    #sys.stdout.write("\r" + (" " * 120) + "\r")
    #sys.stdout.flush()

async def sleep_until_next_epoch(block_height, buffer_blocks=60, msg=None):
    """
    Sleep until near the end of the current epoch.
    Each epoch is 2160 blocks, 10s each. Subtract buffer_blocks from remainder.
    If result <= 0, do a minimal sleep of 300s.
    """
    if not msg:
        msg = "until closer to next epoch..."

    blocks_left = 2160 - (block_height % 2160) - buffer_blocks
    sleep_time = blocks_left * 10  # 10s per block

    if sleep_time <= 0:
        sleep_time = 300
        msg = "Epoch boundary reached; forcing minimal sleep."

    await sleep_with_feedback(sleep_time, msg)

def minutes_until_next_epoch(block_height, buffer_blocks=60):
    """
    Return how many whole minutes remain until next epoch minus buffer_blocks.
    """
    blocks_left = 2160 - (block_height % 2160) - buffer_blocks
    total_seconds = max(blocks_left * 10, 0)
    return total_seconds // 60


# ─────────────────────────────────────────────────────────────────────────────
# FREQUENT UPDATE LOOP (every 10 seconds) for display
# ─────────────────────────────────────────────────────────────────────────────

async def frequent_update_loop():
    """
    Update the block height and balances every 20 seconds.
    Checks if the block height changes to ensure node responsiveness.
    """
    # password = get_env_variable("MY_WALLET_VARIABLE", dotenv_key="WALLET_PASSWORD")

    loopcnt = 0
    consecutive_no_change = 0  # Counter for consecutive no-change in block height
    last_known_block_height = None  # Track the last block height
    consecutive_low_peers = 0 # Track loops of low peer counts
    
    while True:
        # 1) Fetch block height
        block_height_str = await execute_command_async(f"{use_sudo} ruskquery block-height")
        if not block_height_str:
            logging.error("Failed to fetch block height. Retrying in 10s...")
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
            logging.error(message)
            notifier.notify(message, shared_state)
            consecutive_no_change = 0  # Reset after notifying to avoid spamming
            await asyncio.sleep(1)
            continue # Need to double check this

        # Update last known block height and shared state
        last_known_block_height = current_block_height
        shared_state["block_height"] = current_block_height
        
        # Perform balance and stake-info updates every X  loops (e.g., 30 is 5 minutes)
        if loopcnt >= 33:
            pub_bal, shld_bal = await get_wallet_balances(password)
            shared_state["balances"]["public"] = pub_bal
            shared_state["balances"]["shielded"] = shld_bal
            
            stake_output = await execute_command_async(f"{use_sudo} rusk-wallet --password {password} stake-info")
            if stake_output:
                e_stake, r_slashed, a_rewards = parse_stake_info(stake_output)
                shared_state["stake_info"]["stake_amount"] = e_stake or 0.0
                shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed or 0.0
                shared_state["stake_info"]["rewards_amount"] = a_rewards or 0.0
            
            dusk_data = await fetch_dusk_data()
            if dusk_data:
                shared_state["price"] = dusk_data.get("usd", "N/A")
                shared_state["market_cap"]  = dusk_data.get("usd_market_cap", "N/A")
                shared_state["volume"]  = dusk_data.get("usd_24h_vol", "N/A")
                shared_state["usd_24h_change"]  = dusk_data.get("usd_24h_change", "N/A")
                
                
            loopcnt = 0  # Reset loop count after update
        
        
        shared_state["peer_count"] = await execute_command_async(f"{use_sudo} ruskquery peers")
        peer_count = int(shared_state["peer_count"])
        
        if not peer_count:
            logging.error("Failed to fetch peers. Retrying in 10s...")
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
            logging.error(message)
            notifier.notify(message, shared_state)
            consecutive_low_peers = 0  # Reset after notifying to avoid spamming

        loopcnt += 1
        await asyncio.sleep(10)  # Wait 10 seconds before the next loop


async def init_balance():
    """
        Init display values
    """
    dusk_data = await fetch_dusk_data()
    if not dusk_data:
        dusk_data = {}
    shared_state["price"] = dusk_data.get("usd", "N/A")
    shared_state["market_cap"]  = dusk_data.get("usd_market_cap", "N/A")
    shared_state["volume"]  = dusk_data.get("usd_24h_vol", "N/A")
    shared_state["usd_24h_change"]  = dusk_data.get("usd_24h_change", "N/A")

    # 1) Fetch block height
    block_height_str = await execute_command_async(f"{use_sudo} ruskquery block-height")
    if block_height_str:
        shared_state["block_height"] = int(block_height_str)

    # 2) Fetch wallet balances
    pub_bal, shld_bal = await get_wallet_balances(password)
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
            dusk_info = await fetch_dusk_data()
            shared_state["price"] = dusk_info.get('usd',0)
        except Exception as e:
            #logging.error(f"Error in real-time display: {e}")
            #await sleep_with_feedback(10, "retry block height fetch")
            await asyncio.sleep(5)
            continue
        
        # For logic, we may want a fresh block height right before we do anything:
        block_height_str = await execute_command_async(f"{use_sudo} ruskquery block-height")
        if not block_height_str:
            logging.error("Failed to fetch block height. Retrying in 60s...")
            await sleep_with_feedback(30, "retry block height fetch")
            continue

        block_height = int(block_height_str)
        shared_state["block_height"] = block_height

        # If we already saw 'No Action' for this block, wait a bit
        if shared_state["last_no_action_block"] == block_height:
            msg = f"Already did 'No Action' at block {block_height}; sleeping 60s."
            await sleep_with_feedback(60, msg)
            continue

        # Fetch stake-info
        stake_output = await execute_command_async(f"{use_sudo} rusk-wallet --password {password} stake-info")
        if not stake_output:
            logging.error("Failed to fetch stake-info. Retrying in 60s...")
            await sleep_with_feedback(30, "retry stake-info fetch")
            continue

        e_stake, r_slashed, a_rewards = parse_stake_info(stake_output)
        if e_stake is None or r_slashed is None or a_rewards is None:
            logging.warning("Parsing stake info failed or incomplete. Skipping cycle...")
            await sleep_with_feedback(30, "skipping cycle")
            continue

        # Update in shared state
        shared_state["stake_info"]["stake_amount"] = e_stake
        shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed
        shared_state["stake_info"]["rewards_amount"] = a_rewards

        # For logic thresholds
        last_claim_block = shared_state["last_claim_block"]
        stake_amount = e_stake
        reclaimable_slashed_stake = r_slashed
        rewards_amount = a_rewards

        rewards_per_epoch = calculate_rewards_per_epoch(rewards_amount, last_claim_block, block_height)
        downtime_loss = calculate_downtime_loss(rewards_per_epoch)
        incremental_threshold = rewards_per_epoch
        total_restake = stake_amount + rewards_amount + reclaimable_slashed_stake

        # Decide
        if should_unstake_and_restake(reclaimable_slashed_stake, downtime_loss):
            if total_restake < min_stake_amount:
                shared_state["last_action_taken"] = "Unstake/Restake Skipped (Below Min)"
                log_action(
                    f"Balance Info (#{block_height})", 
                    f"Rwd: {format_float(rewards_amount)}, Stk: {format_float(stake_amount)}, Rcl: {format_float(reclaimable_slashed_stake)}"
                )
                
                log_action(
                    f"Unstake/Restake Skipped (Block #{block_height})",
                    f"Total restake ({format_float(total_restake)} DUSK) < {min_stake_amount} DUSK."
                )
            else:
                # Unstake & Restake
                act_msg = f"Unstake/Restake @ Block #{block_height}"
                shared_state["last_action_taken"] = act_msg

                log_action(
                    f"Balance Info (#{block_height})",
                    f"Rwd: {format_float(rewards_amount)}, Stake: {format_float(stake_amount)}, Rcl: {format_float(reclaimable_slashed_stake)}"
                )
                log_action(
                    act_msg,
                    f"Reclaimable: {format_float(reclaimable_slashed_stake)}, Downtime Loss: {format_float(downtime_loss)}"
                )

                # 1) Withdraw
                curr_cmd = f"{use_sudo} rusk-wallet --password {password} withdraw"
                curr_cmd2 = f"{use_sudo} rusk-wallet --password ####### withdraw"
                cmd_success = await execute_command_async(curr_cmd)
                if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd2}", 'error')
                    raise Exception("CMD execution failed")
                
                # 2) Unstake
                curr_cmd =f"{use_sudo} rusk-wallet --password {password} unstake"
                curr_cmd2 =f"{use_sudo} rusk-wallet --password ####### unstake"
                cmd_success = await execute_command_async(curr_cmd)
                if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd2}", 'error')
                    raise Exception("CMD execution failed")
                
                # 3) Stake
                curr_cmd = f"{use_sudo} rusk-wallet --password {password} stake --amt {total_restake}"
                curr_cmd2 = f"{use_sudo} rusk-wallet --password ####### stake --amt {total_restake}"
                cmd_success = await execute_command_async(curr_cmd)
                if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd2}", 'error')
                    raise Exception("CMD execution failed")

                log_action("Restake Completed", f"New Stake: {format_float(float(total_restake))}")
                shared_state["last_claim_block"] = block_height

                # Sleep 2 epochs
                await sleep_until_next_epoch(block_height + 2160, msg="2-epoch wait after restaking...")
                continue

        elif should_claim_and_stake(rewards_amount, incremental_threshold):
            # Claim & Stake
            shared_state["last_action_taken"] = f"Claim/Stake @ Block {block_height}"
            log_action(
                f"Balance Info (#{block_height})",
                f"Rwd: {format_float(rewards_amount)}, Stk: {format_float(stake_amount)}, Rcl: {format_float(reclaimable_slashed_stake)}"
            )
            log_action("Claim and Stake", f"Rewards: {format_float(rewards_amount)}")

            # 1) Withdraw
            curr_cmd =f"{use_sudo} rusk-wallet --password {password} withdraw"
            curr_cmd2 =f"{use_sudo} rusk-wallet --password ###### withdraw"
            cmd_success = await execute_command_async(curr_cmd) # TODO: have it use curr_cmd.replace('######',f"{password}"))
            if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd2}", 'error')
                    raise Exception("CMD execution failed")
                
            # 2) Stake
            curr_cmd = f"{use_sudo} rusk-wallet --password {password} stake --amt {rewards_amount}"
            curr_cmd2 = f"{use_sudo} rusk-wallet --password ###### stake --amt {rewards_amount}"
            cmd_success = await execute_command_async(curr_cmd)
            if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd2}", 'error')
                    raise Exception("CMD execution failed")
                
            new_stake = stake_amount + rewards_amount
            log_action("Stake Completed", f"New Stake: {format_float(new_stake)}")
            shared_state["last_claim_block"] = block_height
            
            await sleep_until_next_epoch(block_height, msg="Waiting until next Epoch")
            continue

        else:
            # No action
            shared_state["last_no_action_block"] = block_height
            shared_state["last_action_taken"] = f"No Action @ Block {block_height}"

            b = shared_state["balances"]
            totBal = b["public"] + b["shielded"]
            
            now_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            
            if shared_state["first_run"]:
                
                byline = Text("\n  DuskMan: Stake Management System - By Wolfrage", style="bold blue")
                
                #auto_status = f'\n\tEnable tmux Support:     {enable_tmux}\n\tAuto Staking Rewards:    {auto_stake_rewards}\n\tAuto Restake to Reclaim: {auto_reclaim_full_restakes}\n\t{notification_status}'
                #separator = "  [bold white]" + ("=" * 47) + "[/bold white]"
                
                #console.print(byline)
               # print(separator + auto_status)
                
                
                shared_state["first_run"] = False
                shared_state["last_action_taken"] = f"Startup @ Block #{block_height}"
                action = shared_state["last_action_taken"]
                
                stats = (
                f"\n{"=" * 44}\n"
                f"  Action       : {now_ts} {action}\n"
                f"  Balance      : {format_float(totBal)} DUSK\n"
                f"    ├─ Public  :   {format_float(b['public'])} DUSK (${format_float(b['public'] * float(shared_state["price"]))})\n"
                f"    └─ Shielded:   {format_float(b['shielded'])} DUSK (${format_float(b['shielded'] * float(shared_state["price"]))})\n"
                f"  Staked       : {format_float(stake_amount)} DUSK (${format_float(stake_amount * float(shared_state["price"]))})\n"
                f"  Rewards      : {format_float(rewards_amount)} DUSK (${format_float(rewards_amount * float(shared_state["price"]))})\n"
                f"  Reclaimable  : {format_float(reclaimable_slashed_stake)} DUSK (${format_float(reclaimable_slashed_stake * float(shared_state["price"]))})\n"
                    )
                notifier.notify(stats, shared_state)

            action = shared_state["last_action_taken"]
            
            
            now_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

            # Fetch required data
            block_height = shared_state["block_height"]
            action = shared_state["last_action_taken"]
            st_info = shared_state["stake_info"]

            x = 0
            while x < 10:
                # Generate log entry
                log_entry = (
                    f"\n\t==== Activity @{now_ts}====\n"
                    f"\n"
                    #f"\t Current Block : #{block_height}\n"
                    f"\t Last Action   : {action}\n"
                    f"\t Staked        : {format_float(st_info['stake_amount'])} (${format_float(st_info['stake_amount'] * shared_state['price'], 2)})\n"
                    f"\t Rewards       : {format_float(st_info['rewards_amount'])} (${format_float(st_info['rewards_amount'] * shared_state['price'], 2)})\n"
                    f"\t Reclaimable   : {format_float(st_info['reclaimable_slashed_stake'])} (${format_float(st_info['reclaimable_slashed_stake'] * shared_state['price'], 2)})\n"
                    f"\t \n"
                    )
                
                if len(log_entries) > 20:
                    log_entries.pop(0)
                log_entries.append(log_entry)
                x += 1
            # Display logs above the real-time display
            
            #if not first_run:
                #for entry in log_entries:
                #console.clear()
                #console.print(log_entries[0])

            # Mark first run as completed after the first iteration 
            first_run = False

        # Sleep until near the next epoch
        await sleep_until_next_epoch(block_height, buffer_blocks=buffer_blocks)


# ─────────────────────────────────────────────────────────────────────────────
# REAL-TIME DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.box import ROUNDED
import datetime


async def realtime_display(enable_tmux=False):
    """
    Continuously display real-time info in the console using Rich Layout.
    Also updates TMUX status bar if enabled.
    """

    # Create the main layout
    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        # Remove or reduce the footer if space is tight:
        # Layout(name="footer", size=1),
    )

    # The body is split into a left and right column.
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1, ),
    )

    # The left column is further split vertically for Node Stats and Balances
    layout["left"].split_column(
        Layout(name="node_stats", size=9),
        Layout(name="balances"),
        #Layout(name="options",size=10),
    )

    def truncate_to(num, decimals=4):
        """Truncate a number to a certain number of decimals (no rounding)."""
        if not isinstance(num, (float, int)):
            return str(num)
        s = str(num)
        if "." not in s:
            return s
        front, back = s.split(".", 1)
        return f"{front}.{back[:decimals]}"

    def update_layout():
        """
        Updates all sections of the layout with real-time data.
        """
        # 1) HEADER
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_text = Text.assemble(
            ("DuskMan: Dusk Stake Manager  ", "bold cyan"),
            (f"{now_str}", "bold white"),
        )
        layout["header"].update(
            Panel(Align.center(header_text), )
        )

        # 2) NODE STATS
        stats_table = Table(
            expand=True,
            show_header=False,
            padding=(0, 0),
        )
        
        stats_table.add_column("Metric", style="bold yellow", no_wrap=True)
        stats_table.add_column("Value", style="bold white")

        

        blk = shared_state["block_height"]
        peer_count = shared_state["peer_count"]
        remain_seconds = shared_state["remain_time"]
        disp_time = format_hms(remain_seconds) if remain_seconds > 0 else "0s"
        completion_time = shared_state["completion_time"]
        last_action = shared_state["last_action_taken"]

        stats_table.add_row("Block Height", f"#{blk}")
        stats_table.add_row("Peer Count", str(peer_count))
        stats_table.add_row("Next Check", f"{disp_time} ({completion_time})")
        stats_table.add_row("Last Action", f"{last_action}")

        node_stats_panel = Panel(
            stats_table,
            title=" Node Stats ",
            border_style="bright_cyan",
        )
        layout["left"]["node_stats"].update(node_stats_panel)

        # 3) BALANCES & STAKING
        b = shared_state["balances"]
        st_info = shared_state["stake_info"]
        price = shared_state["price"]

        pub_bal = b["public"]
        shld_bal = b["shielded"]
        tot_bal = pub_bal + shld_bal
        staked = st_info["stake_amount"]
        rewards = st_info["rewards_amount"]
        reclaimable = st_info["reclaimable_slashed_stake"]

        balance_table = Table(
            show_header=False,
            expand=True,
            padding=(0, 0),
        )
        balance_table.add_column("Label", justify="right", style="bold yellow")
        balance_table.add_column("Amount", style="bold white")

        balance_table.add_row("Public", f"{truncate_to(pub_bal,4)} DUSK (${(pub_bal*price):.2f})")
        balance_table.add_row("Shielded", f"{truncate_to(shld_bal,4)} DUSK (${(shld_bal*price):.2f})")
        balance_table.add_row("Total", f"{truncate_to(tot_bal,4)} DUSK (${(tot_bal*price):.2f})")
        balance_table.add_row("Staked", f"{truncate_to(staked,4)} (${staked*price:.2f})")
        balance_table.add_row("Rewards", f"{truncate_to(rewards,4)} (${rewards*price:.2f})")
        balance_table.add_row("Reclaimable", f"{truncate_to(reclaimable,4)} (${reclaimable*price:.2f})")

        balances_panel = Panel(
            balance_table,
            title=" Balances & Staking ",
            border_style="bright_blue",
            height=11
        )
        layout["left"]["balances"].update(balances_panel)
# 3) OPTIONS
        
        notification_services = []
        if notification_config.get('discord_webhook'):
            notification_services.append('Discord')
        if notification_config.get('pushbullet_token'):
            notification_services.append('PushBullet')
        if notification_config.get('telegram_bot_token') and notification_config.get('telegram_chat_id'):
            notification_services.append('Telegram')
        if notification_config.get('pushover_user_key') and notification_config.get('pushover_app_token'):
            notification_services.append('Pushover')
        if notification_config.get('webhook_url'):
            notification_services.append('Webhook')
        
        if len(notification_services) > 2 and notification_services:
            services = "\n\t\t  " + " ".join(notification_services)
        elif len(notification_services) <= 2 and notification_services:   
            services = " ".join(notification_services)
        else:
            services = "None"
            
        
        notification_status = f'Enabled Notifications:[yellow]   {services}\n'
            
        options_table = Table(expand=True, show_header=False,)
        options_table.add_column("Option", style="bold yellow", no_wrap=True)
        options_table.add_column("Value", style="bold white")
        options_table.add_row("Enabled tmux Support","True" if config.get("enable_tmux", False) else "Disabled")
        options_table.add_row("Auto Stake Rewards", "True" if config.get("auto_stake_rewards", False) else "Disabled")
        options_table.add_row("Auto Reclaim Full Restakes","True" if config.get("auto_reclaim_full_restakes", False) else "Disabled",)
        options_table.add_row("Enabled Notifications", services)
        
        # Limit height so it doesn't push everything else off the screen
        options_panel = Panel(
            options_table,
            title=" Options ",
            border_style="bright_magenta",
            height=10,
            expand=True,
        )
        # layout["left"]["options"].update(options_panel)
        
        
        # 4) RECENT LOGS (limit its height!)
        log_table = Table(
            expand=True,
            show_header=False,
            padding=(0, 0),
        )
        log_table.add_column("Logs", style="bold white", no_wrap=True, overflow="fold")

        # Show the last 5 logs, newest first
        recent_logs = reversed(log_entries[-5:])
        for raw_log in recent_logs:
            log_table.add_row(raw_log.strip())

        # Limit height so it doesn't push everything else off the screen
        logs_panel = Panel(
            log_table,
            title=" Recent Logs ",
            border_style="bright_magenta",
            expand=True,
        )
        layout["right"].update(logs_panel)

        # 5) FOOTER (Removed or commented out to save space)
        # footer_text = Text("Hello!", justify="center", style="bold white")
        # footer_panel = Panel(
        #     footer_text,
        #     box=box.ROUNDED,
        #     style="on black",
        # )
        # layout["footer"].update(footer_panel)

    async def update_tmux_status():
        """
        Update the TMUX status bar with current stats.
        """
        if not enable_tmux:
            return

        blk = f"Blk: #{shared_state['block_height']}"
        pcount = f"Peers: {shared_state['peer_count']}"
        laction = f"Last: {shared_state['last_action_taken']}"
        status_text = f"{blk} | {pcount} | {laction}"

        try:
            subprocess.check_call(["tmux", "set-option", "-g", "status-left", remove_ansi(status_text)])
        except subprocess.CalledProcessError:
            logging.error("Failed to update TMUX status bar. Is tmux running?")

    # The real-time display loop
    with Live(layout, console=console, refresh_per_second=10, auto_refresh=False) as live:
        while True:
            try:
                # Update the layout with fresh data
                update_layout()

                # Refresh the live display
                live.refresh()

                # Update TMUX
                await update_tmux_status()

                await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"Error in real-time display loop: {e}")
                await asyncio.sleep(5)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """
    Concurrently run:
        - frequent_update_loop: refresh block height & balances every 20s
        - stake_management_loop: performs staking logic and sleeps until next epoch
        - realtime_display: shows real-time info in console
        - update_tmux_status_bar: updates TMUX (if enabled)
    """
    # console.clear()
    await init_balance() # Make sure balances are initialized for display
    if enable_dashboard and dash_port and dash_ip:
        from utilities.web_dashboard import start_dashboard
        await start_dashboard(shared_state, log_entries, host=dash_ip, port=dash_port)
        
    await asyncio.gather(
        stake_management_loop(),
        realtime_display(enable_tmux),
        frequent_update_loop(),
        
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nCTRL-C detected. Exiting gracefully.\n")
        sys.exit(0)
