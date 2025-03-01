import re
import os
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, Union, List

# Import color constants
from utilities.colors import *

def get_env_variable(var_name='WALLET_PASSWORD', dotenv_key='WALLET_PASSWORD', log_action_func=None):
    """
    Retrieve an environment variable or a fallback value from .env file.
    
    Args:
        var_name: Name of the environment variable to retrieve
        dotenv_key: Fallback key to check in .env file
        log_action_func: Function to call for logging errors
        
    Returns:
        The value of the environment variable
        
    Raises:
        SystemExit: If neither environment variable nor .env key is found
    """
    value = os.getenv(var_name)
    if not value:
        value = os.getenv(dotenv_key)
        if not value:
            if log_action_func:
                log_action_func("Wallet Password Variable Error", 
                              f"Neither environment variable '{var_name}' nor .env key '{dotenv_key}' found for wallet password.", 
                              "error")
            import sys
            sys.exit(1)
            
    return value

def format_number(number: int) -> str:
    """Format an integer with thousands separators."""
    return f"{number:,}"

def convert_timestamp(timestamp: str) -> str:
    """Convert ISO timestamp to MM/DD/YY format."""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.strftime('%m/%d/%y')
    except ValueError as e:
        return f"Error: Invalid timestamp format - {e}"

def display_wallet_distribution_bar(public_amount: float, shielded_amount: float, width: int = 30) -> str:
    """
    Displays a single horizontal bar (ASCII blocks) with two colored segments
    to visualize the distribution of funds between public and shielded balances.

    Args:
        public_amount: The public balance
        shielded_amount: The shielded balance
        width: Total number of blocks in the bar
        
    Returns:
        A string representation of the distribution bar
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

def convert_to_float(value: Any) -> float:
    """
    Tries to convert a value to a float. 
    If successful, returns the float. Otherwise, returns 0.0.
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
    
def remove_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    # Regular expression to match ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def format_float(value: Union[float, str], places: int = 4) -> str:
    """
    Convert float to a string with max (4 default) decimal digits.
    
    Args:
        value: The value to format
        places: Maximum number of decimal places
        
    Returns:
        Formatted string representation of the float
    """
    parts = str(convert_to_float(value)).split('.')
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1][:places]}" if len(parts[1]) > 0 else parts[0]
    return parts[0]

def format_hms(seconds: int) -> str:
    """
    Given an integer number of seconds, return a string like "1h 20m 5s"
    skipping any 0 values. Always show seconds for less jittery feedback.
    
    Args:
        seconds: Number of seconds to format
        
    Returns:
        Formatted time string
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

def write_to_log(file_path: str, message: str) -> None:
    """
    Write a message to the specified log file.
    
    Args:
        file_path: Path to the log file
        message: Message to write
    """
    try:
        with open(file_path, "a") as log_file:
            log_file.write(message + "\n")
    except Exception as e:
        # This is a bit of a circular dependency, but we'll handle it in the main app
        print(f"Error writing to log file {file_path}: {e}")

def calculate_rewards_per_epoch(rewards_amount: float, last_claim_block: int, current_block: int) -> float:
    """
    Estimate how many rewards are generated per epoch (2160 blocks) since last claim.
    
    Args:
        rewards_amount: Current rewards amount
        last_claim_block: Block number of the last claim
        current_block: Current block number
        
    Returns:
        Estimated rewards per epoch
    """
    blocks_elapsed = current_block - last_claim_block
    epochs_elapsed = blocks_elapsed / 2160
    if epochs_elapsed > 0:
        return rewards_amount / epochs_elapsed
    return 0.0

def calculate_downtime_loss(rewards_per_epoch: float, downtime_epochs: int = 1) -> float:
    """
    Calculate downtime loss for unstaking and restaking.
    
    Args:
        rewards_per_epoch: Rewards earned per epoch
        downtime_epochs: Number of epochs of downtime
        
    Returns:
        Estimated loss during downtime
    """
    return rewards_per_epoch * downtime_epochs
