import os
import subprocess
import re
import time
import logging
import sys
import datetime
import yaml

from utilities.notifications import NotificationService


# ─────────────────────────────────────────────────────────────────────────────
# LOAD CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

def load_config(section="GENERAL",file_path="config.yaml"):
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

bufferblocks = config.get('buffer_blocks',60)
enable_tmux = config.get('enable_tmux',False)


# Initialize the notification service
notifier = NotificationService(notification_config)


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL STUFF
# ─────────────────────────────────────────────────────────────────────────────

remainTime = 0  # This tracks how many seconds remain in the current sleep cycle
last_no_action_block = None  # Tracks the last block where 'No Action' was taken

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING CONFIG
# ─────────────────────────────────────────────────────────────────────────────

LOG_FILE = "actions.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M',
    handlers=[
        logging.StreamHandler(sys.stdout),  # Logs to console
        logging.FileHandler(LOG_FILE)       # Logs to file
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
        exit(1)
    return value

def get_current_timestamp():
    """Return a timestamp string matching the logging date format: YYYY-mm-dd HH:MM"""
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

def format_float(value):
    # Convert to string and split by '.'
    parts = str(value).split('.')
    if len(parts) == 2:  # There's a decimal part
        # Slice the decimal part to up to 4 digits
        return f"{parts[0]}.{parts[1][:4]}" if len(parts[1]) > 0 else parts[0]
    return parts[0]  # No decimal part

def execute_command(command):
    """
    Execute a shell command and return its *stdout* output only.
    Stderr is suppressed by redirecting it to /dev/null.
    """
    try:
        result = subprocess.check_output(
            command,
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL
        )
        return result.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Error executing command: {command}\n{e}")
        return None

def log_action(action, details):
    """Log actions to the file."""
    notifier.notify(f"{action}: {details}") # Send Notifications
    logging.info(f"{action}: {details}") # Log to File and Screen

def format_hms(seconds):
    """
    Given an integer number of seconds, return a string like:
        "1h 20m 5s"
    skipping any 0 values (e.g., "0m" won't appear).
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
    #if s > 0:
    parts.append(f"{s}s") # Just add seconds anyway to avoid text jumping

    # if everything was 0, let's just say "0s"
    if not parts:
        parts = ["0s"]

    return ' '.join(parts)

# ─────────────────────────────────────────────────────────────────────────────
# TMUX ENABLE TOGGLE
# Either set this to True/False in config or rely on CLI argument "tmux"
# ─────────────────────────────────────────────────────────────────────────────

# If the user passes "tmux" as the first argument, override enable_tmux
if len(sys.argv) > 1 and sys.argv[1].lower() == 'tmux':
    enable_tmux = True


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE & BALANCE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_profile_addresses(password):
    """
    Fetch addresses from 'rusk-wallet profiles'.
    Return a dict with:
        {
            'public': [addr1, ...],
            'shielded': [addr2, ...]
        }
    """
    addresses = {
        "public": [],
        "shielded": []
    }

    cmd = f"sudo rusk-wallet --password {password} profiles"
    output = execute_command(cmd)
    if not output:
        return addresses  # empty if fails

    # Example lines:
    # > Profile  1 (Default)
    # >   Shielded account - eox326D2m1oh...
    # >   Public account   - 24hTVdrFZUS6...
    for line in output.splitlines():
        line = line.strip()
        if "Shielded account" in line:
            match = re.search(r"Shielded account\s*-\s*(\S+)", line)
            if match:
                addresses["shielded"].append(match.group(1))
        elif "Public account" in line:
            match = re.search(r"Public account\s*-\s*(\S+)", line)
            if match:
                addresses["public"].append(match.group(1))

    return addresses

def get_spendable_balance_for_address(password, address):
    """
    For a given address:
        sudo rusk-wallet --password <pwd> balance --spendable --address <ADDRESS>
    Expected output line: "Total: 5.06348853"
    """
    cmd = f"sudo rusk-wallet --password {password} balance --spendable --address {address}"
    output = execute_command(cmd)
    if not output:
        return 0.0

    # Simple approach that removes "Total: " from the line
    total_str = output.replace("Total: ", "")
    if total_str:
        try:
            return float(total_str)
        except ValueError:
            return 0.0
    return 0.0

def get_wallet_balances(password):
    """
    1) Fetch addresses from 'profiles'
    2) For each address, sum its spendable balances
    Return (public_total, shielded_total).
    """
    addresses = get_profile_addresses(password)
    public_total = 0.0
    shielded_total = 0.0

    for addr in addresses["public"]:
        public_total += get_spendable_balance_for_address(password, addr)

    for addr in addresses["shielded"]:
        shielded_total += get_spendable_balance_for_address(password, addr)

    return (public_total, shielded_total)

# ─────────────────────────────────────────────────────────────────────────────
# STAKE LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def parse_stake_info(output):
    """Parse the stake-info output for relevant values."""
    try:
        lines = output.splitlines()
        eligible_stake = None
        reclaimable_slashed_stake = None
        accumulated_rewards = None

        for line in lines:
            line = line.strip()
            if "Eligible stake:" in line:
                if '.' in line:
                    match = re.search(r"Eligible stake:\s*([0-9]+\.[0-9]+)\s*DUSK", line)
                else:
                    match = re.search(r"Eligible stake:\s*([0-9]+)\s*DUSK", line)
                if match:
                    eligible_stake = float(match.group(1))
            elif "Reclaimable slashed stake:" in line:
                if '.' in line:
                    match = re.search(r"Reclaimable slashed stake:\s*([0-9]+\.[0-9]+)\s*DUSK", line)
                else:
                    match = re.search(r"Reclaimable slashed stake:\s*([0-9]+)\s*DUSK", line)
                if match:
                    reclaimable_slashed_stake = float(match.group(1))
            elif "Accumulated rewards is:" in line:
                if '.' in line:
                    match = re.search(r"Accumulated rewards is:\s*([0-9]+\.[0-9]+)\s*DUSK", line)
                else:
                    match = re.search(r"Accumulated rewards is:\s*([0-9]+)\s*DUSK", line)
                if match:
                    accumulated_rewards = float(match.group(1))

        if (eligible_stake is None or 
            reclaimable_slashed_stake is None or 
            accumulated_rewards is None):
            logging.warning("Incomplete stake-info values. Skipping this cycle.")
            return None, None, None

        return eligible_stake, reclaimable_slashed_stake, accumulated_rewards

    except Exception as e:
        logging.error(f"Error parsing stake-info output: {e}")
        return None, None, None

def calculate_rewards_per_epoch(rewards_amount, last_claim_block, current_block):
    """Calculate rewards per epoch based on the last claim."""
    blocks_elapsed = current_block - last_claim_block
    epochs_elapsed = blocks_elapsed / 2160
    if epochs_elapsed > 0:
        return rewards_amount / epochs_elapsed
    return 0.0

def calculate_downtime_loss(rewards_per_epoch, downtime_epochs=1):
    """Calculate the downtime loss for unstaking and restaking."""
    return rewards_per_epoch * downtime_epochs

def should_unstake_and_restake(reclaimable_slashed_stake, downtime_loss):
    """Determine if unstaking and restaking is worthwhile."""
    return reclaimable_slashed_stake > 1 and reclaimable_slashed_stake >= downtime_loss

def should_claim_and_stake(rewards, incremental_threshold):
    """Determine if claiming and staking rewards is worthwhile."""
    return rewards > 1 and rewards >= incremental_threshold

# ─────────────────────────────────────────────────────────────────────────────
# SLEEP & EPOCH FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def sleep_with_feedback(sleep_time, msg=None):
    """
    Sleep in intervals while providing feedback.
    Now displays hours/minutes/seconds as #h #m #s (skipping zeroes),
    and shows the time when the sleep will complete.
    """
    interval = 1 
    total_remaining = sleep_time

    global remainTime
    remainTime = 0

    # Calculate the completion time
    completion_time = datetime.datetime.now() + datetime.timedelta(seconds=sleep_time)
    completion_time_str = completion_time.strftime('%H:%M:%S')

    while total_remaining > 0:
        time_to_sleep = min(interval, total_remaining)
        remainTime = total_remaining

        # Format the time as h/m/s, skipping any zero components
        display_time = format_hms(total_remaining)
        # Show something like: "Sleeping for 1h 4m 10s (completes at HH:MM:SS) <message>"
        message = f"Sleeping {display_time} ({completion_time_str}) {msg or ''}"

        sys.stdout.write(f"\r{message}")
        sys.stdout.flush()

        time.sleep(time_to_sleep)
        total_remaining -= time_to_sleep

    sys.stdout.write("\r                                                                               \n")
    sys.stdout.flush()


def sleep_until_next_epoch(block_height, buffer_blocks=bufferblocks, msg=None):
    """
    Calculate sleep time until closer to the end of the epoch.
    If calculated time <= 0, force a minimal sleep (e.g. 300s) 
    so we don't loop on the same block with zero delay.
    """
    if not msg:
        msg = 'until closer to the next epoch...'
        
    blocks_left = 2160 - (block_height % 2160) - buffer_blocks
    sleep_time = blocks_left * 10  # 10s per block

    # Force minimal sleep if 0 or negative
    if sleep_time <= 0:
        sleep_time = 120
        msg = "as epoch boundary reached; forcing minimal sleep"

    sleep_with_feedback(sleep_time, msg)

def minutes_until_next_epoch(block_height, buffer_blocks=bufferblocks):
    """Return how many whole minutes remain until the next epoch minus buffer blocks."""
    blocks_left = 2160 - (block_height % 2160) - buffer_blocks
    total_seconds = max(blocks_left * 10, 0)
    return int(total_seconds // 60)

# ─────────────────────────────────────────────────────────────────────────────
# TMUX
# ─────────────────────────────────────────────────────────────────────────────

def update_tmux_status_bar(
    block_height,
    pub_balance,
    shld_balance,
    stake_amount,
    rewards_amount,
    reclaimable_slashed_stake,
    last_action,
    minutes_wait
):
    """Update the Tmux status bar (right side) with the current info."""
    if not enable_tmux:
        return  # If Tmux support is disabled, skip entirely.

    status_str = (
        f"Blk: #{block_height} | "
        f"Pub: {pub_balance:.4f} Shd:{shld_balance:.4f} | "
        f"Stk: {stake_amount:.4f} Rwd:{rewards_amount:.4f} Rcl:{reclaimable_slashed_stake:.4f} | "
        f"{last_action} | Wait:{minutes_wait}s "
    )
    try:
        subprocess.check_call(["tmux", "set-option", "-g", "status-left", status_str])
    except subprocess.CalledProcessError:
        logging.error("Failed to update tmux status bar. Are you running inside tmux?")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main(): # TODO: separate display from calculations to  display realtime
    PASSWORD_ENV_VAR = "MY_SUDO_PASSWORD"
    password = get_env_variable(PASSWORD_ENV_VAR)

    MIN_STAKE_AMOUNT = 1000  
    last_claim_block = 0
    last_action_taken = "Starting Up"
    first_run = True

    global last_no_action_block

    while True:
        # ─────────────────────────────────────────────────────────────────
        # 0. Check if we've already handled a "No Action" on this block
        # ─────────────────────────────────────────────────────────────────
        block_height_str = execute_command("sudo ruskquery block-height")
        if not block_height_str:
            logging.error("Failed to fetch block height. Retrying...")
            sleep_with_feedback(60, "retrying block height fetch")
            continue

        block_height = int(block_height_str)

        if last_no_action_block == block_height:
            # We already processed a "No Action" at this block. 
            # Force a short sleep to let block height progress.
            
            # print(f"Already saw 'No Action' at block {block_height}. Sleeping 30s to avoid repeated loop...")
            sleep_with_feedback(60,"Already saw 'No Action' at block {block_height}. Sleeping 60s to avoid repeated loop...")
            continue

        # ─────────────────────────────────────────────────────────────────
        # 1. Get stake info
        # ─────────────────────────────────────────────────────────────────
        stake_info = execute_command(f"sudo rusk-wallet --password {password} stake-info")
        if not stake_info:
            logging.error("Failed to fetch stake info. Retrying...")
            sleep_with_feedback(60, "retrying stake info fetch")
            continue

        stake_amount, reclaimable_slashed_stake, rewards_amount = parse_stake_info(stake_info)
        if stake_amount is None or reclaimable_slashed_stake is None or rewards_amount is None:
            logging.warning("Parsing failed. Skipping cycle.")
            sleep_with_feedback(60, "skipping cycle")
            continue

        # ─────────────────────────────────────────────────────────────────
        # 2. Calculate values & get balances
        # ─────────────────────────────────────────────────────────────────
        rewards_per_epoch = calculate_rewards_per_epoch(rewards_amount, last_claim_block, block_height)
        downtime_loss = calculate_downtime_loss(rewards_per_epoch)
        incremental_threshold = rewards_per_epoch
        total_restake = format_float(stake_amount + rewards_amount + reclaimable_slashed_stake)

        pub_balance, shld_balance = get_wallet_balances(password)

        # ─────────────────────────────────────────────────────────────────
        # 3. Decision logic
        # ─────────────────────────────────────────────────────────────────
        if should_unstake_and_restake(reclaimable_slashed_stake, downtime_loss):
            if total_restake < MIN_STAKE_AMOUNT:
                last_action_taken = "Unstake/Restake Skipped (Below Min)"
                log_action(f"Unstake/Restake Skipped (Block #{block_height})", 
                    f"Total restake ({total_restake:.4f} DUSK) < {MIN_STAKE_AMOUNT} DUSK.")
            else:
                # Perform Unstake & Restake
                last_action_taken = f"Unstake/Restake @ Block #{block_height}"
                log_action(f"Balance Info (#{block_height})", f"Rwd: {rewards_amount:.4f}, Stake: {stake_amount:.4f}, Rcl: {reclaimable_slashed_stake:.4f}")
                log_action(last_action_taken, f"Reclaimable: {reclaimable_slashed_stake:.4f}, Downtime Loss: {downtime_loss:.4f}")

                execute_command(f"sudo rusk-wallet --password {password} withdraw")
                execute_command(f"sudo rusk-wallet --password {password} unstake")
                execute_command(f"sudo rusk-wallet --password {password} stake --amt {total_restake}")
                log_action("Restake Completed", f"New Stake: {float(total_restake):.4f}")

                last_claim_block = block_height
                # Optional: Sleep 2 epochs from now
                sleep_until_next_epoch(block_height + 2160, msg='due to restaking 2-epoch wait period...')

        elif should_claim_and_stake(rewards_amount, incremental_threshold):
            # Claim & Stake
            last_action_taken = f"Claim/Stake @ Block {block_height}"
            log_action(f"Balance Info (#{block_height})", f"Rwd: {rewards_amount:.4f}, Stk: {stake_amount:.4f}, Rcl: {reclaimable_slashed_stake:.4f}")
            log_action("Claim and Stake", f"Rewards: {rewards_amount:.4f}")
            execute_command(f"sudo rusk-wallet --password {password} withdraw")
            execute_command(f"sudo rusk-wallet --password {password} stake --amt {rewards_amount}")
            log_action("Stake Completed", f"New Staked: {stake_amount + (rewards_amount * .9)} New Reclaimable: {rewards_amount * .1}")
            last_claim_block = block_height

        else:
            # No action
            timenow = get_current_timestamp()
            totBal = pub_balance + shld_balance
            last_action_taken = f"No Action @ Block {block_height}"
            last_no_action_block = block_height  # <=== Track the block for no action
            
            if first_run:
                first_run = False
                notifier.notify(f"Startup (Block #{block_height})\n"
                f"\tBalance: {format_float(totBal)} Dusk (P:{format_float(pub_balance)} | S:{format_float(shld_balance)})\n"  
                f"\tRewards: {format_float(rewards_amount)}\n"
                f"\tStaked:  {format_float(stake_amount)}\n"
                f"\tReclaimable: {format_float(reclaimable_slashed_stake)}")

            print(f"{timenow}\n  No action (Block #{block_height})\n"
                f"\tBalance: {format_float(totBal)} Dusk (P:{format_float(pub_balance)} | S:{format_float(shld_balance)})\n"  
                f"\tRewards: {format_float(rewards_amount)}\n"
                f"\tStaked:  {format_float(stake_amount)}\n"
                f"\tReclaimable: {format_float(reclaimable_slashed_stake)}")
            
        # ─────────────────────────────────────────────────────────────────
        # 4. Tmux status bar
        # ─────────────────────────────────────────────────────────────────
        
        if config.get('enable_tmux', False):
            update_tmux_status_bar(
                block_height=block_height,
                pub_balance=pub_balance,
                shld_balance=shld_balance,
                stake_amount=stake_amount,
                rewards_amount=rewards_amount,
                reclaimable_slashed_stake=reclaimable_slashed_stake,
                last_action=last_action_taken,
                minutes_wait=remainTime  # how many seconds remain in the last sleep
            )

        # ─────────────────────────────────────────────────────────────────
        # 5. Update last_claim_block & sleep
        # ─────────────────────────────────────────────────────────────────
        
        sleep_until_next_epoch(block_height)

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCTRL-C detected. Exiting gracefully.\n")
        sys.exit(0)
