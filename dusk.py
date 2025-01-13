import os
import sys
import subprocess
import re
import time
import logging
import datetime
import yaml
import asyncio

from utilities.notifications import NotificationService

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
notification_config = load_config('NOTIFICATIONS')
config = load_config('GENERAL')
buffer_blocks = config.get('buffer_blocks', 60)
min_stake_amount = config.get('min_stake_amount', 1000)
min_peers = config.get('min_peers', 8)
errored = False

# If user passes "tmux" as first argument, override enable_tmux
if config.get('enable_tmux', False) or (len(sys.argv) > 1 and sys.argv[1].lower() == 'tmux'):
    enable_tmux = True
else:
    enable_tmux = False

# Initialize the notification service
notifier = NotificationService(notification_config)

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

def get_env_variable(var_name):
    """Retrieve an environment variable or exit if missing."""
    value = os.getenv(var_name)
    if not value:
        logging.error(f"Error: The environment variable {var_name} is not set.")
        sys.exit(1)
    return value

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

def format_float(value):
    """Convert float to a string with max 4 decimal digits."""
    parts = str(value).split('.')
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1][:4]}" if len(parts[1]) > 0 else parts[0]
    return parts[0]

def log_action(action, details, type='info'):
    """Log actions to file/console and send notifications."""
    notifier.notify(f"{action}: {details}")
    
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

    cmd_profiles = f"sudo rusk-wallet --password {password} profiles"
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
        cmd_balance = f"sudo rusk-wallet --password {password} balance --spendable --address {addr}"
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
    return reclaimable_slashed_stake > 1 and reclaimable_slashed_stake >= downtime_loss

def should_claim_and_stake(rewards, incremental_threshold):
    """Determine if claiming and staking rewards is worthwhile."""
    return rewards > 1 and rewards >= incremental_threshold

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
    shared_state["completion_time"] = "@" + completion_time
    
    while shared_state["remain_time"] > 0:
        interval = min(1, shared_state["remain_time"])
        
        await asyncio.sleep(interval)
        shared_state["remain_time"] -= interval

    # Optionally clear or log
    sys.stdout.write("\r" + (" " * 80) + "\r")
    sys.stdout.flush()

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
    password = get_env_variable("MY_SUDO_PASSWORD")
    loopcnt = 0
    consecutive_no_change = 0  # Counter for consecutive no-change in block height
    last_known_block_height = None  # Track the last block height
    consecutive_low_peers = 0 # Track loops of low peer counts
    
    while True:
        # 1) Fetch block height
        block_height_str = await execute_command_async("sudo ruskquery block-height")
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
            notifier.notify(message)
            consecutive_no_change = 0  # Reset after notifying to avoid spamming

        # Update last known block height and shared state
        last_known_block_height = current_block_height
        shared_state["block_height"] = current_block_height
        
        # Perform balance and stake-info updates every 30 loops (e.g., 5 minutes)
        if loopcnt >= 30:
            pub_bal, shld_bal = await get_wallet_balances(password)
            shared_state["balances"]["public"] = pub_bal
            shared_state["balances"]["shielded"] = shld_bal
            
            stake_output = await execute_command_async(f"sudo rusk-wallet --password {password} stake-info")
            if stake_output:
                e_stake, r_slashed, a_rewards = parse_stake_info(stake_output)
                shared_state["stake_info"]["stake_amount"] = e_stake or 0.0
                shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed or 0.0
                shared_state["stake_info"]["rewards_amount"] = a_rewards or 0.0
            
            loopcnt = 0  # Reset loop count after update
        
        
        shared_state["peer_count"] = await execute_command_async("sudo ruskquery peers")
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
            notifier.notify(message)
            consecutive_low_peers = 0  # Reset after notifying to avoid spamming

        loopcnt += 1
        await asyncio.sleep(10)  # Wait 10 seconds before the next loop


async def init_balance():
    """
    Update the block height and balances every 20 seconds.
    This is for display purposes to keep data fresh, 
    even while the main staking logic might be sleeping until the next epoch.
    """
    password = get_env_variable("MY_SUDO_PASSWORD")

    # 1) Fetch block height
    block_height_str = await execute_command_async("sudo ruskquery block-height")
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
    password = get_env_variable("MY_SUDO_PASSWORD")

    while True:
        # For logic, we may want a fresh block height right before we do anything:
        block_height_str = await execute_command_async("sudo ruskquery block-height")
        if not block_height_str:
            logging.error("Failed to fetch block height. Retrying in 60s...")
            await sleep_with_feedback(60, "retry block height fetch")
            continue

        block_height = int(block_height_str)
        shared_state["block_height"] = block_height

        # If we already saw 'No Action' for this block, wait a bit
        if shared_state["last_no_action_block"] == block_height:
            msg = f"Already did 'No Action' at block {block_height}; sleeping 60s."
            await sleep_with_feedback(60, msg)
            continue

        # Fetch stake-info
        stake_output = await execute_command_async(f"sudo rusk-wallet --password {password} stake-info")
        if not stake_output:
            logging.error("Failed to fetch stake-info. Retrying in 60s...")
            await sleep_with_feedback(60, "retry stake-info fetch")
            continue

        e_stake, r_slashed, a_rewards = parse_stake_info(stake_output)
        if e_stake is None or r_slashed is None or a_rewards is None:
            logging.warning("Parsing stake info failed or incomplete. Skipping cycle...")
            await sleep_with_feedback(60, "skipping cycle")
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
                curr_cmd = await execute_command_async(f"sudo rusk-wallet --password {password} withdraw")
                cmd_success = await execute_command_async(curr_cmd)
                if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd}", 'error')
                    raise Exception("CMD execution failed")
                
                # 2) Unstake
                curr_cmd = await execute_command_async(f"sudo rusk-wallet --password {password} unstake")
                cmd_success = await execute_command_async(curr_cmd)
                if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd}", 'error')
                    raise Exception("CMD execution failed")
                
                # 3) Stake
                curr_cmd = await execute_command_async(
                    f"sudo rusk-wallet --password {password} stake --amt {total_restake}"
                )
                cmd_success = await execute_command_async(curr_cmd)
                if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd}", 'error')
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
            curr_cmd = await execute_command_async(f"sudo rusk-wallet --password {password} withdraw")
            cmd_success = await execute_command_async(curr_cmd)
            if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd}", 'error')
                    raise Exception("CMD execution failed")
            # 2) Stake
            curr_cmd = await execute_command_async(f"sudo rusk-wallet --password {password} stake --amt {rewards_amount}")
            cmd_success = await execute_command_async(curr_cmd)
            if not cmd_success:
                    log_action(f"Withdraw Failed (Block #{block_height})", f"Command: {curr_cmd}", 'error')
                    raise Exception("CMD execution failed")
                
            new_stake = stake_amount + rewards_amount
            log_action("Stake Completed", f"New Stake: {format_float(new_stake)}")
            shared_state["last_claim_block"] = block_height

        else:
            # No action
            shared_state["last_no_action_block"] = block_height
            shared_state["last_action_taken"] = f"No Action @ Block {block_height}"

            b = shared_state["balances"]
            totBal = b["public"] + b["shielded"]
            
            now_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            
            if shared_state["first_run"]:
                byline = "\nDusk Stake Management & Monitoring: By Wolfrage"
               # sepline = ("-" * (len(byline ) -2))
                print(byline) # + sepline)
                
                shared_state["first_run"] = False
                shared_state["last_action_taken"] = f"Startup @ Block #{block_height}"
                action = shared_state["last_action_taken"]
                separator = "=" * 50
                
                stats = (
                f"\n{separator}\n"
                f"  Timestamp    : {now_ts}\n"
                f"  Last Action  : {action}\n"
                f"  Balance      : {format_float(totBal)} DUSK\n"
                f"    ├─ Public  :  {format_float(b['public'])} DUSK\n"
                f"    └─ Shielded:  {format_float(b['shielded'])} DUSK\n"
                f"  Staked       : {format_float(stake_amount)} DUSK\n"
                f"  Rewards      : {format_float(rewards_amount)} DUSK\n"
                f"  Reclaimable  : {format_float(reclaimable_slashed_stake)} DUSK\n"
            )
                notifier.notify(stats)

            action = shared_state["last_action_taken"]
            
            stats = (
                f"\n{separator}\n"
                f"  Timestamp    : {now_ts}\n"
                f"  Last Action  : {action}\n"
                f"  Balance      : {format_float(totBal)} DUSK\n"
                f"    ├─ Public  :  {format_float(b['public'])} DUSK\n"
                f"    └─ Shielded:  {format_float(b['shielded'])} DUSK\n"
                f"  Staked       : {format_float(stake_amount)} DUSK\n"
                f"  Rewards      : {format_float(rewards_amount)} DUSK\n"
                f"  Reclaimable  : {format_float(reclaimable_slashed_stake)} DUSK\n"
                f"{separator}\n"
            )
            
            print(stats)

        # Sleep until near the next epoch
        await sleep_until_next_epoch(block_height, buffer_blocks=buffer_blocks)


# ─────────────────────────────────────────────────────────────────────────────
# REAL-TIME DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

async def realtime_display(config=False):
    """
    Continuously display real-time info in the console (updates every 1 second).
    Reflects frequent updates from 'frequent_update_loop' + stake_info, etc.
    """
    first_run = True
    
    if config:
        enable_tmux = True
    else:
        enable_tmux = False
    
    while True:
        try:
            if first_run:
                first_run = False
                await asyncio.sleep(2)
                continue
                
            blk = shared_state["block_height"]
            st_info = shared_state["stake_info"]
            b = shared_state["balances"]
            last_act = shared_state["last_action_taken"]
            remain_seconds = shared_state["remain_time"]
            disp_time = format_hms(remain_seconds) if remain_seconds > 0 else "0s"
            peers = shared_state["peer_count"] or 0
            last_txt = str()
            
            if errored:  # TODO: add visual alerts
                error_txt = "- !ERROR DETECTED!"
            else:
                error_txt = str()
            
            status_txt = f"\r> Blk: #{blk} | Stk: {format_float(st_info['stake_amount'])} | Rcl: {format_float(st_info['reclaimable_slashed_stake'])} | Rwd: {format_float(st_info['rewards_amount'])} | Bal: P:{format_float(b['public'])} S:{format_float(b['shielded'])} | Peers: {peers} |{last_txt} Next: {disp_time} ({shared_state["completion_time"]}) {error_txt}      \r"
            
            sys.stdout.write(status_txt)
            sys.stdout.flush()
        except Exception as e:
            logging.error(f"Error in real-time display: {e}")
        
        
        if enable_tmux:
            try:
                last_txt = f" Last: {last_act} |"
            
                status_txt = f"\r> Blk: #{blk} | Stk: {format_float(st_info['stake_amount'])} | Rcl: {format_float(st_info['reclaimable_slashed_stake'])} | Rwd: {format_float(st_info['rewards_amount'])} | Bal: P:{format_float(b['public'])} S:{format_float(b['shielded'])} | Peers: {peers} |{last_txt} Next Check: {disp_time}      \r"

                subprocess.check_call(["tmux", "set-option", "-g", "status-left", status_txt])
            except subprocess.CalledProcessError:
                config.enable_tmux = False
                enable_tmux = False
                logging.error("Failed to update tmux status bar. Are you running inside tmux? Disabling tmux.")
                notifier.notify('Disabling tmux due to status bar update failure')
            except Exception as e:
                logging.error(f"Error updating Tmux status bar: {e}")

        await asyncio.sleep(1)


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
    
    await init_balance() # Make sure balances are initialized for display
    
    await asyncio.gather(
        stake_management_loop(),
        realtime_display(enable_tmux),
        #update_tmux_status_bar(),
        frequent_update_loop(),
        
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nCTRL-C detected. Exiting gracefully.\n")
        sys.exit(0)
