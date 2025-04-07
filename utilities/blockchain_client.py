import asyncio
import re
import traceback
from typing import Optional, Tuple, Dict, Any, List, Union

from utilities.utils import convert_to_float, format_float, remove_ansi

# Command Constants
CMD_BLOCK_HEIGHT = "ruskquery block-height"
CMD_PEERS = "ruskquery peers"
CMD_WALLET_PROFILES = "rusk-wallet --password {password} profiles"
CMD_WALLET_BALANCE = "rusk-wallet --password {password} balance --spendable --address {address}"
CMD_STAKE_INFO = "rusk-wallet --password {password} stake-info"
CMD_WITHDRAW = "rusk-wallet --password {password} withdraw"
CMD_UNSTAKE = "rusk-wallet --password {password} unstake"
CMD_STAKE = "rusk-wallet --password {password} stake --amt {amount}"

class BlockchainClient:
    """
    Client for interacting with the Dusk blockchain.
    Handles command execution, balance fetching, and stake information parsing.
    """
    
    def __init__(self, use_sudo: bool, password: str, log_action_func=None):
        """
        Initialize the blockchain client.
        
        Args:
            use_sudo: Whether to use sudo for commands
            password: Wallet password
            log_action_func: Function to call for logging
        """
        self.use_sudo = "sudo" if use_sudo else ""
        self.password = password
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        
    async def execute_command(self, command: str, log_output: bool = True) -> Optional[str]:
        """
        Execute a shell command asynchronously and return its output (stdout).
        
        Args:
            command: Command to execute
            log_output: Whether to log the command and its output
            
        Returns:
            Command output as string, or None if the command failed
        """
        try:
            if log_output:
                cmd2 = command
                self.log_action("Executing Command", cmd2.replace(self.password, '#####'), "debug")
                
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()

            if process.returncode != 0:
                self.log_action(
                    f"Command failed with return code {process.returncode}:\\n {command.replace(self.password, '#####')}",
                    stderr_str.replace(self.password, '#####'),
                    "error"
                )
                return None
            else:
                if log_output and stdout_str:
                    self.log_action(
                        f"Command output",
                        stdout_str.replace(self.password, '#####'),
                        'debug'
                    )
                # Return raw stdout for parsing later, don't remove password here
                return stdout.decode().strip()
        except asyncio.CancelledError: # Explicitly handle cancellation first
            raise # Re-raise cancellation to allow proper shutdown
        except Exception as e: # Catch other exceptions, including potential subprocess errors
            # Check if it looks like a subprocess error based on context/type if possible,
            # otherwise log as a general error during command execution.
            error_type = type(e).__name__ # Get the specific exception type name
            self.log_action(
                f"Error executing command: {command.replace(self.password, '#####')}",
                f"Type: {error_type}, Error: {str(e)}\\n{traceback.format_exc()}", # Include type and traceback
                "error"
            )
            return None
            
    async def get_block_height(self) -> Optional[int]:
        """
        Get the current block height from the blockchain.
        
        Returns:
            Current block height as integer, or None if the command failed
        """
        block_height_str = await self.execute_command(f"{self.use_sudo} {CMD_BLOCK_HEIGHT}", False)
        if not block_height_str:
            self.log_action("Failed to fetch block height", "Could not retrieve block height", "error")
            return None
        
        try:
            return int(block_height_str)
        except ValueError:
            self.log_action("Invalid block height", f"Could not parse block height: {block_height_str}", "error")
            return None
            
    async def get_peer_count(self) -> Optional[int]:
        """
        Get the current peer count from the blockchain.
        
        Returns:
            Current peer count as integer, or None if the command failed
        """
        peer_count_str = await self.execute_command(f"{self.use_sudo} {CMD_PEERS}", False)
        if not peer_count_str:
            self.log_action("Failed to fetch peers", "Could not retrieve peer count", "error")
            return None
        
        try:
            return int(peer_count_str)
        except ValueError:
            self.log_action("Invalid peer count", f"Could not parse peer count: {peer_count_str}", "error")
            return None
            
    async def get_wallet_balances(self, shared_state: Dict[str, Any], monitor_wallet: bool, first_run: bool = False) -> Tuple[float, float]:
        """
        Fetches the wallet balances for public and shielded addresses.
        
        Args:
            shared_state: Shared state dictionary to update
            monitor_wallet: Whether to monitor wallet balance changes
            first_run: Whether this is the first run
            
        Returns:
            Tuple of (public_balance, shielded_balance)
        """
        try:
            # Fetch address from 'rusk-wallet profiles'
            addresses = {
                "public": [],
                "shielded": []
            }

            cmd_profiles = f"{self.use_sudo} {CMD_WALLET_PROFILES.format(password=self.password)}"
            output_profiles = await self.execute_command(cmd_profiles)
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
            self.log_action(
                f"Error in get_wallet_balances(): ",
                str(e).replace(self.password, '#####'),
                "error"
            )
            await asyncio.sleep(5)
            return 0.0, 0.0

        # Track if we've encountered the specific error before
        error_logged = False
        error_fixed = False
        
        async def get_spendable_for_address(addr):
            """
            Fetches the spendable balance for the given address
            """
            nonlocal error_logged, error_fixed
            
            cmd_balance = f"{self.use_sudo} {CMD_WALLET_BALANCE.format(password=self.password, address=addr)}"
            max_retries = 5  # Maximum number of retries
            retry_count = 0
            encountered_error = False
            
            while retry_count < max_retries:
                try:
                    out = await self.execute_command(cmd_balance, log_output=False)
                    if out:
                        # Clean the output first
                        cleaned_output = remove_ansi(out)
                        
                        # Log the cleaned output if needed for debugging
                        # self.log_action("Cleaned Balance Output", cleaned_output.replace(self.password, '#####'), "debug")

                        total_str = cleaned_output.replace("Total: ", "").strip()
                        
                        # Check if the cleaned string is a valid float representation
                        if re.match(r'^-?\d+(\.\d+)?$', total_str):
                            result = float(total_str)
                            
                            # If we previously encountered the error and now it's fixed, log it
                            if encountered_error and not error_fixed:
                                self.log_action(
                                    "Balance parsing fixed",
                                    f"Successfully parsed balance for address {addr} after previous failures",
                                    "info"
                                )
                                error_fixed = True
                                
                            return result
                        else:
                            # If cleaning didn't result in a valid number, treat as parsing error
                            raise ValueError(f"Cleaned output '{total_str}' is not a valid float")

                except ValueError as e:
                    encountered_error = True
                    # Only log the specific parsing error once per cycle until fixed
                    if not error_logged:
                        self.log_action(
                            f"Error parsing balance for address {addr}",
                            f"Could not convert string to float: {e}. Output: '{out[:100]}...' - Retrying...",
                            "error"
                        )
                        error_logged = True
                        error_fixed = False

                    # Wait with exponential backoff
                    backoff_time = 15 * (2 ** retry_count)
                    self.log_action("Retrying balance fetch", f"Waiting {backoff_time}s before retry {retry_count + 1}/{max_retries} for address {addr}", "debug")
                    await asyncio.sleep(backoff_time)
                    retry_count += 1
                    continue

                except Exception as e:
                    # Handle connection errors or other unexpected issues
                    encountered_error = True
                    log_msg = str(e).replace(self.password, '#####')
                    
                    if 'Connection to Rusk Failed' in log_msg:
                        if not error_logged:
                            self.log_action(f"Connection Error getting balance for {addr}", log_msg, "error")
                            error_logged = True
                            error_fixed = False
                        # Use a shorter, fixed retry delay for connection issues
                        await asyncio.sleep(10)
                    else:
                        if not error_logged:
                            self.log_action(f"Unexpected Error getting balance for {addr}", log_msg, "error")
                            error_logged = True
                            error_fixed = False
                        # Use standard backoff for other errors
                        backoff_time = 5 * (2 ** retry_count)
                        await asyncio.sleep(backoff_time)

                    retry_count += 1
                    continue
                
                # If execute_command returned None or empty string without throwing an error
                self.log_action(f"Empty response getting balance for {addr}", "Retrying...", "debug")
                await asyncio.sleep(5 * (2 ** retry_count))
                retry_count += 1

            # If we've exhausted all retries
            if encountered_error and not error_fixed:
                self.log_action(
                    f"Failed to get balance for address {addr} after {max_retries} retries.",
                    "Will try again in the next cycle.",
                    "error"
                )
                # error_logged state persists until the next successful parse in this cycle
                
            return 0.0
        error_logged = False
        error_fixed = False
        tasks_public = [get_spendable_for_address(addr) for addr in addresses["public"]]
        tasks_shielded = [get_spendable_for_address(addr) for addr in addresses["shielded"]]

        results_public = await asyncio.gather(*tasks_public)
        results_shielded = await asyncio.gather(*tasks_shielded)

        new_public_total = sum(results_public)
        new_shielded_total = sum(results_shielded)

        # Check for balance changes
        old_public_total = shared_state.get("balances", {}).get("public", 0.0)
        old_shielded_total = shared_state.get("balances", {}).get("shielded", 0.0)

        if (float(format_float(old_public_total + old_shielded_total)) != 
            float(format_float(new_public_total + new_shielded_total))) and monitor_wallet and not first_run:
            if new_public_total != old_public_total:
                self.log_action(
                    "Balance Change Detected",
                    f"Public balance changed from {format_float(old_public_total)} → {format_float(new_public_total)} DUSK.",
                    "info"
                )

            if new_shielded_total != old_shielded_total:
                self.log_action(
                    "Balance Change Detected",
                    f"Shielded balance changed from {format_float(old_shielded_total)} → {format_float(new_shielded_total)} DUSK.",
                    "info"
                )

        # Update shared_state
        shared_state["balances"]["public"] = new_public_total
        shared_state["balances"]["shielded"] = new_shielded_total

        return new_public_total, new_shielded_total
        
    def parse_stake_info(self, output: str, shared_state: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], float]:
        """
        Parse the output of the 'rusk-wallet --password <password> stake-info' command.
        
        Args:
            output: Command output to parse
            shared_state: Shared state dictionary to update
            
        Returns:
            Tuple of (eligible_stake, reclaimable_slashed_stake, accumulated_rewards)
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
                self.log_action("Incomplete stake-info values.", f"Could not parse fully.\n{lines}", "error")
                return None, None, 0.0

            # Return the parsed values
            return eligible_stake, reclaimable_slashed_stake, accumulated_rewards
        except Exception as e:
            self.log_action(f"Error parsing stake-info output: ", str(e), "error")
            return None, None, 0.0
            
    async def get_stake_info(self, shared_state: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], float]:
        """
        Get stake information from the blockchain.
        
        Args:
            shared_state: Shared state dictionary to update
            
        Returns:
            Tuple of (eligible_stake, reclaimable_slashed_stake, accumulated_rewards)
        """
        stake_output = await self.execute_command(f"{self.use_sudo} {CMD_STAKE_INFO.format(password=self.password)}")
        if not stake_output:
            self.log_action("Error", "Failed to fetch stake-info.", "error")
            return None, None, 0.0
            
        return self.parse_stake_info(stake_output, shared_state)
        
    async def withdraw_rewards(self) -> bool:
        """
        Withdraw staking rewards.
        
        Returns:
            True if successful, False otherwise
        """
        cmd = f"{self.use_sudo} {CMD_WITHDRAW.format(password=self.password)}"
        cmd_success = await self.execute_command(cmd)
        if not cmd_success:
            self.log_action("Withdraw Failed", "Command execution failed", 'error')
            return False
        if 'Withdrawing 0 reward is not allowed' in cmd_success:
            self.log_action("Withdraw Notice", "No rewards to withdraw", 'info')
            return True
        return True
        
    async def unstake(self) -> bool:
        """
        Unstake funds.
        
        Returns:
            True if successful, False otherwise
        """
        cmd = f"{self.use_sudo} {CMD_UNSTAKE.format(password=self.password)}"
        cmd_success = await self.execute_command(cmd)
        if not cmd_success or 'rror' in cmd_success:
            self.log_action("Unstake Failed", "Command execution failed", 'error')
            return False
        return True
        
    async def stake(self, amount: float) -> bool:
        """
        Stake funds.
        
        Args:
            amount: Amount to stake
            
        Returns:
            True if successful, False otherwise
        """
        cmd = f"{self.use_sudo} {CMD_STAKE.format(password=self.password, amount=amount)}"
        cmd_success = await self.execute_command(cmd)
        if not cmd_success or 'rror' in cmd_success:
            self.log_action("Stake Failed", f"Command execution failed", 'error')
            return False
        return True
