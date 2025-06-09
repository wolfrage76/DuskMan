import asyncio
import re
import os
import signal
from typing import Optional, Tuple, Dict, Any, List, Union
from datetime import datetime

from utilities.utils import convert_to_float, format_float
from utilities.process_watchdog import ProcessWatchdog

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
    Enhanced with process monitoring and robust timeout handling.
    """
    
    def __init__(self, use_sudo: bool, password: str, log_action_func=None, watchdog_config: Dict[str, Any] = None, sudo_config: Dict[str, Any] = None):
        """
        Initialize the blockchain client.
        
        Args:
            use_sudo: Whether to use sudo for commands
            password: Wallet password
            log_action_func: Function to call for logging
            watchdog_config: Configuration for process watchdog timeouts and retries
            sudo_config: Configuration for sudo handling
        """
        self.use_sudo = "sudo" if use_sudo else ""
        self.password = password
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        
        # Configure sudo handling
        self.sudo_config = sudo_config or {}
        self.sudo_password = None
        
        if self.use_sudo and sudo_config:
            # Check if we should use passwordless sudo
            if sudo_config.get('passwordless_sudo', False):
                self.use_sudo = "sudo"
            # Check if we should use stdin for password
            elif sudo_config.get('use_stdin_password', False):
                self.use_sudo = "sudo -S"
                self.sudo_password = sudo_config.get('sudo_password', '')
            # Check if sudo password is provided directly
            elif sudo_config.get('sudo_password'):
                self.use_sudo = "sudo -S"
                self.sudo_password = sudo_config.get('sudo_password', '')
        
        # Initialize process watchdog
        self.watchdog = ProcessWatchdog(log_action_func)
        
        # Load timeout configurations from config or use defaults
        if watchdog_config:
            self.default_timeout = 60.0  # Default timeout for most commands
            self.wallet_timeout = watchdog_config.get('wallet_command_timeout', 120)
            self.critical_timeout = watchdog_config.get('wallet_command_timeout', 120) + 30  # Extra time for critical ops
            self.max_retries = watchdog_config.get('max_retries', 3)
            self.retry_delay = watchdog_config.get('retry_delay', 5.0)
        else:
            # Fallback defaults
            self.default_timeout = 60.0
            self.wallet_timeout = 120.0
            self.critical_timeout = 150.0
            self.max_retries = 3
            self.retry_delay = 5.0
        
    async def start_watchdog(self):
        """Start the process watchdog."""
        await self.watchdog.start()
        
    async def stop_watchdog(self):
        """Stop the process watchdog."""
        await self.watchdog.stop()
        
    async def execute_command_with_retry(self, command: str, log_output: bool = True, 
                                       timeout: Optional[float] = None, max_retries: Optional[int] = None) -> Optional[str]:
        """
        Execute a command with retry logic and enhanced error handling.
        
        Args:
            command: Command to execute
            log_output: Whether to log the command and its output
            timeout: Custom timeout for this command
            max_retries: Custom max retries for this command
            
        Returns:
            Command output as string, or None if all retries failed
        """
        if timeout is None:
            # Determine timeout based on command type
            if 'rusk-wallet' in command:
                if 'stake-info' in command or 'stake' in command or 'unstake' in command:
                    timeout = self.critical_timeout
                else:
                    timeout = self.wallet_timeout
            else:
                timeout = self.default_timeout
                
        if max_retries is None:
            max_retries = self.max_retries
            
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    self.log_action(
                        "Command Retry", 
                        f"Attempt {attempt + 1}/{max_retries + 1} for: {command.replace(self.password, '#####')[:100]}...",
                        "warning"
                    )
                    await asyncio.sleep(self.retry_delay * attempt)  # Exponential backoff
                    
                result = await self.execute_command(command, log_output, timeout)
                if result is not None:
                    if attempt > 0:
                        self.log_action(
                            "Command Retry Success", 
                            f"Command succeeded on attempt {attempt + 1}",
                            "info"
                        )
                    return result
                    
            except asyncio.CancelledError:
                # Don't retry on cancellation, just re-raise
                self.log_action(
                    "Command Cancelled", 
                    f"Command was cancelled during retry: {command.replace(self.password, '#####')[:100]}...",
                    "debug"
                )
                raise
                
            except Exception as e:
                last_error = e
                self.log_action(
                    "Command Execution Error", 
                    f"Attempt {attempt + 1} failed: {str(e)}",
                    "error"
                )
                
        # All retries failed
        self.log_action(
            "Command Failed", 
            f"All {max_retries + 1} attempts failed for: {command.replace(self.password, '#####')[:100]}...",
            "error"
        )
        return None
        
    async def execute_command(self, command: str, log_output: bool = True, timeout: float = 60.0) -> Optional[str]:
        """
        Execute a shell command asynchronously with enhanced monitoring and timeout handling.
        
        Args:
            command: Command to execute
            log_output: Whether to log the command and its output
            timeout: Timeout in seconds
            
        Returns:
            Command output as string, or None if the command failed
        """
        process = None
        start_time = datetime.now()
        
        try:
            if log_output:
                cmd_display = command.replace(self.password, '#####')
                if self.sudo_password:
                    cmd_display = cmd_display.replace(self.sudo_password, '#####')
                self.log_action("Executing Command", cmd_display, "debug")
                
            # Create the subprocess
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if self.sudo_password else None,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None  # Create new process group
            )
            
            # Register with watchdog
            if process.pid:
                self.watchdog.register_process(process.pid, command, start_time)
            
            try:
                # Handle sudo password input if needed
                stdin_input = None
                if self.sudo_password and "-S" in self.use_sudo:
                    stdin_input = f"{self.sudo_password}\n".encode()
                
                # Wait for the process with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=stdin_input), 
                    timeout=timeout
                )
                
                # Unregister from watchdog
                if process.pid:
                    self.watchdog.unregister_process(process.pid)
                    
            except asyncio.TimeoutError:
                elapsed = (datetime.now() - start_time).total_seconds()
                self.log_action(
                    "Command Timeout", 
                    f"Command timed out after {elapsed:.1f}s (limit: {timeout}s): {command.replace(self.password, '#####')[:100]}...",
                    "error"
                )
                
                # Kill the process and its children
                await self._kill_process_group(process)
                
                # Unregister from watchdog
                if process.pid:
                    self.watchdog.unregister_process(process.pid)
                    
                return None
                
            except asyncio.CancelledError:
                # Handle cancellation gracefully
                self.log_action(
                    "Command Cancelled", 
                    f"Command was cancelled: {command.replace(self.password, '#####')[:100]}...",
                    "debug"
                )
                
                # Kill the process and its children
                if process:
                    await self._kill_process_group(process)
                
                # Unregister from watchdog
                if process and process.pid:
                    self.watchdog.unregister_process(process.pid)
                    
                # Re-raise the CancelledError so the cancellation propagates properly
                raise

            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()

            if process.returncode != 0:
                # Mask passwords in error output
                error_display = stderr_str.replace(self.password, '#####')
                if self.sudo_password:
                    error_display = error_display.replace(self.sudo_password, '#####')
                    
                self.log_action(
                    "Command Failed", 
                    f"Return code {process.returncode}: {command.replace(self.password, '#####')[:100]}...\nError: {error_display}",
                    "error"
                )
                return None
            else:
                if log_output and stdout_str:
                    output_display = stdout_str.replace(self.password, '#####')
                    if self.sudo_password:
                        output_display = output_display.replace(self.sudo_password, '#####')
                    self.log_action(
                        "Command Output",
                        output_display,
                        'debug'
                    )
                
                # Mask passwords in return value
                result = stdout_str.replace(self.password, '#####')
                if self.sudo_password:
                    result = result.replace(self.sudo_password, '#####')
                return result
                
        except Exception as e:
            # Unregister from watchdog
            if process and process.pid:
                self.watchdog.unregister_process(process.pid)
                
            error_msg = str(e)
            if self.password:
                error_msg = error_msg.replace(self.password, '#####')
            if self.sudo_password:
                error_msg = error_msg.replace(self.sudo_password, '#####')
                
            self.log_action(
                "Command Execution Error", 
                f"Error executing: {command.replace(self.password, '#####')[:100]}...\nError: {error_msg}",
                "error"
            )
            return None
            
    async def _kill_process_group(self, process):
        """
        Kill a process and its entire process group.
        
        Args:
            process: The subprocess to kill
        """
        try:
            if process.pid:
                # Try to kill the entire process group
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    await asyncio.sleep(2)  # Give it time to terminate gracefully
                    
                    # Check if still running
                    if process.returncode is None:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        
                except (OSError, ProcessLookupError):
                    # Fallback to killing just the main process
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                        
                # Wait for cleanup
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                    
        except Exception as e:
            self.log_action(
                "Process Kill Error", 
                f"Error killing process {process.pid}: {str(e)}",
                "error"
            )
            
    async def get_block_height(self) -> Optional[int]:
        """
        Get the current block height from the blockchain.
        
        Returns:
            Current block height as integer, or None if the command failed
        """
        block_height_str = await self.execute_command_with_retry(
            f"{self.use_sudo} {CMD_BLOCK_HEIGHT}", 
            False, 
            timeout=30.0,  # Shorter timeout for simple queries
            max_retries=2
        )
        if not block_height_str:
            self.log_action("Failed to fetch block height", "Could not retrieve block height", "error")
            return None
        
        try:
            return int(block_height_str)
        except ValueError as e:
            self.log_action("Invalid block height", f"Could not parse block height: {block_height_str}\n {e}", "error")
            return None
            
    async def get_peer_count(self) -> Optional[int]:
        """
        Get the current peer count from the blockchain.
        
        Returns:
            Current peer count as integer, or None if the command failed
        """
        peer_count_str = await self.execute_command_with_retry(
            f"{self.use_sudo} {CMD_PEERS}", 
            False,
            timeout=30.0,  # Shorter timeout for simple queries
            max_retries=2
        )
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
            output_profiles = await self.execute_command_with_retry(cmd_profiles, timeout=self.wallet_timeout)
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
                f"Error in get_wallet_balances(): {cmd_profiles.replace(self.password, '#####')}", str(e).replace(self.password, '#####'),
                "error"
            )
            await asyncio.sleep(5)
            return 0.0, 0.0

        # Track if we've encountered the specific error before
        error_logged = False
        error_fixed = False
        
        async def get_spendable_for_address(addr):
            """
            Fetches the spendable balance for the given address with enhanced retry logic
            """
            nonlocal error_logged, error_fixed
            
            cmd_balance = f"{self.use_sudo} {CMD_WALLET_BALANCE.format(password=self.password, address=addr)}"
            
            # Use the retry mechanism for balance fetching
            result = await self.execute_command_with_retry(
                cmd_balance, 
                timeout=self.wallet_timeout,
                max_retries=3
            )
            
            if result:
                try:
                    total_str = result.replace("Total: ", "")
                    return float(total_str)
                except ValueError as e:
                    # Handle the specific '\x1b[?25h' error
                    if '\\x1b[?25h' in str(e) or '\x1b[?25h' in total_str:
                        if not error_logged:
                            self.log_action(
                                "Balance Parsing Error",
                                f"Encountered terminal escape sequence in balance output: {total_str}",
                                "warning"
                            )
                            error_logged = True
                        return 0.0
                    else:
                        self.log_action(
                            "Balance Conversion Error",
                            f"Could not convert balance to float: {total_str}\nError: {str(e)}",
                            "error"
                        )
                        return 0.0
            else:
                return 0.0

        # Execute balance fetching for all addresses
        tasks_public = [get_spendable_for_address(addr) for addr in addresses["public"]]
        tasks_shielded = [get_spendable_for_address(addr) for addr in addresses["shielded"]]

        results_public = await asyncio.gather(*tasks_public, return_exceptions=True)
        results_shielded = await asyncio.gather(*tasks_shielded, return_exceptions=True)

        # Handle exceptions in results
        new_public_total = 0.0
        for result in results_public:
            if isinstance(result, Exception):
                self.log_action("Public Balance Error", f"Error fetching public balance: {str(result)}", "error")
            else:
                new_public_total += result

        new_shielded_total = 0.0
        for result in results_shielded:
            if isinstance(result, Exception):
                self.log_action("Shielded Balance Error", f"Error fetching shielded balance: {str(result)}", "error")
            else:
                new_shielded_total += result

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
            eligible_stake = None  # Changed to None to detect if we found any stake info
            reclaimable_slashed_stake = None  # Changed to None to detect if we found any stake info
            accumulated_rewards = 0.0  # Accumulated rewards from staking
            found_stake_data = False  # Track if we found any actual stake data

            # Check if there's no stake first
            for line in lines:
                line = line.strip()
                if "A stake does not exist for this key" in line:
                    # This is a normal condition, not an error
                    return 0.0, 0.0, 0.0

            for line in lines:
                line = line.strip()
                if "Eligible stake:" in line:
                    # Example: "Eligible stake: 100.0 DUSK"
                    match = re.search(r"Eligible stake:\s*([\d]+(?:\.\d+)?)\s*DUSK", line)
                    if match:
                        eligible_stake = convert_to_float(match.group(1))
                        found_stake_data = True
                elif "Reclaimable slashed stake:" in line:
                    # Example: "Reclaimable slashed stake: 50.0 DUSK"
                    match = re.search(r"Reclaimable slashed stake:\s*([\d]+(?:\.\d+)?)\s*DUSK", line)
                    if match:
                        reclaimable_slashed_stake = convert_to_float(match.group(1))
                        found_stake_data = True
                elif "Accumulated rewards is:" in line:
                    # Example: "Accumulated rewards is: 10.0 DUSK"
                    match = re.search(r"Accumulated rewards is:\s*([\d]+(?:\.\d+)?)\s*DUSK", line)
                    if match:
                        accumulated_rewards = convert_to_float(match.group(1))
                        found_stake_data = True
                elif "Stake active from block #" in line:
                    # Example: "Stake active from block #123456"
                    match = re.search(r"#(\d+)", line)
                    if match:
                        stake_active_blk = int(match.group(1))
                        shared_state["active_blk"] = stake_active_blk
                        found_stake_data = True

            # If we found some stake data but couldn't parse all expected values
            if found_stake_data and (eligible_stake is None or reclaimable_slashed_stake is None):
                # Format the lines properly for logging
                full_output = "\n".join(lines)
                self.log_action("Incomplete stake-info values.", f"Could not parse fully.\n{full_output}", "error")
                return 0.0, 0.0, 0.0

            # If no stake data was found at all, this might be unexpected
            if not found_stake_data:
                # Format the lines properly for logging
                full_output = "\n".join(lines)
                self.log_action("No stake data found", f"Unexpected stake-info output:\n{full_output}", "warning")
                return 0.0, 0.0, 0.0

            # Return the parsed values (convert None to 0.0 for safety)
            return (eligible_stake or 0.0), (reclaimable_slashed_stake or 0.0), accumulated_rewards
        except Exception as e:
            self.log_action(f"Error parsing stake-info output: ", str(e), "error")
            return None, None, 0.0
            
    async def get_stake_info(self, shared_state: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], float]:
        """
        Get stake information from the blockchain with enhanced retry and timeout handling.
        
        Args:
            shared_state: Shared state dictionary to update
            
        Returns:
            Tuple of (eligible_stake, reclaimable_slashed_stake, accumulated_rewards)
        """
        # Use critical timeout and more retries for stake-info as it's crucial
        stake_output = await self.execute_command_with_retry(
            f"{self.use_sudo} {CMD_STAKE_INFO.format(password=self.password)}",
            timeout=self.critical_timeout,
            max_retries=5  # More retries for critical operations
        )
        
        if not stake_output:
            self.log_action("Error", "Failed to fetch stake-info after all retries.", "error")
            return None, None, 0.0
            
        return self.parse_stake_info(stake_output, shared_state)
        
    async def withdraw_rewards(self) -> bool:
        """
        Withdraw staking rewards with enhanced error handling.
        
        Returns:
            True if successful, False otherwise
        """
        cmd = f"{self.use_sudo} {CMD_WITHDRAW.format(password=self.password)}"
        cmd_success = await self.execute_command_with_retry(
            cmd,
            timeout=self.critical_timeout,
            max_retries=3
        )
        
        if not cmd_success:
            self.log_action("Withdraw Failed", "Command execution failed after all retries", 'error')
            return False
            
        if 'Withdrawing 0 reward is not allowed' in cmd_success:
            self.log_action("Withdraw Notice", "No rewards to withdraw", 'info')
            return True
            
        if 'error' in cmd_success.lower() or 'failed' in cmd_success.lower():
            self.log_action("Withdraw Failed", f"Command returned error: {cmd_success}", 'error')
            return False
            
        return True
        
    async def unstake(self) -> bool:
        """
        Unstake funds with enhanced error handling.
        
        Returns:
            True if successful, False otherwise
        """
        cmd = f"{self.use_sudo} {CMD_UNSTAKE.format(password=self.password)}"
        cmd_success = await self.execute_command_with_retry(
            cmd,
            timeout=self.critical_timeout,
            max_retries=3
        )
        
        if not cmd_success:
            self.log_action("Unstake Failed", "Command execution failed after all retries", 'error')
            return False
            
        if 'error' in cmd_success.lower() or 'failed' in cmd_success.lower():
            self.log_action("Unstake Failed", f"Command returned error: {cmd_success}", 'error')
            return False
            
        return True
        
    async def stake(self, amount: float) -> bool:
        """
        Stake funds with enhanced error handling.
        
        Args:
            amount: Amount to stake
            
        Returns:
            True if successful, False otherwise
        """
        cmd = f"{self.use_sudo} {CMD_STAKE.format(password=self.password, amount=amount)}"
        cmd_success = await self.execute_command_with_retry(
            cmd,
            timeout=self.critical_timeout,
            max_retries=3
        )
        
        if not cmd_success:
            self.log_action("Stake Failed", f"Command execution failed after all retries", 'error')
            return False
            
        if 'error' in cmd_success.lower() or 'failed' in cmd_success.lower():
            self.log_action("Stake Failed", f"Command returned error: {cmd_success}", 'error')
            return False
            
        return True
