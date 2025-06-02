import asyncio
from typing import Dict, Any, Optional, Callable

from utilities.blockchain_client import BlockchainClient
from utilities.market_data import MarketDataClient
from utilities.banner import BannerManager

class BlockchainMonitor:
    """
    Monitors the blockchain for updates to block height, peer count, and other metrics.
    Periodically updates the shared state with the latest information.
    """
    
    def __init__(
        self, 
        blockchain_client: BlockchainClient,
        market_data_client: MarketDataClient,
        banner_manager: BannerManager,
        shared_state: Dict[str, Any],
        config: Dict[str, Any],
        log_action_func: Callable = None
    ):
        """
        Initialize the blockchain monitor.
        
        Args:
            blockchain_client: Client for blockchain interactions
            market_data_client: Client for market data
            banner_manager: Manager for banner information
            shared_state: Shared state dictionary
            config: Configuration dictionary
            log_action_func: Function to call for logging
        """
        self.blockchain = blockchain_client
        self.market_data = market_data_client
        self.banner_manager = banner_manager
        self.shared_state = shared_state
        self.config = config
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        
        # Extract configuration values
        self.min_peers = config.get('min_peers', 10)
        self.monitor_wallet = config.get('monitor_wallet', False)
        self.password = config.get('password', '')
        
        self._shutdown_event = asyncio.Event()
        
    async def shutdown(self):
        """Gracefully shutdown the monitor."""
        self.log_action("Blockchain Monitor", "Shutdown requested!", "info")
        self._shutdown_event.set()
        
    async def frequent_update_loop(self) -> None:
        """
        Update the block height and balances every 20 seconds.
        Checks if the block height changes to ensure node responsiveness.
        """
        stake_checking = False
        loopcnt = 0
        banner_fetch_count = 0  # Counter for banner fetching (every 15 minutes)
        consecutive_no_change = 0  # Counter for consecutive no-change in block height
        last_known_block_height = None  # Track the last block height
        consecutive_low_peers = 0  # Track loops of low peer counts
        first_run = True  # Flag for first run to fetch banner immediately
        
        # Soft-lock prevention variables
        consecutive_failures = 0  # Track consecutive failures for circuit breaker
        max_consecutive_failures = 5  # Maximum failures before entering recovery mode
        recovery_mode = False  # Flag to indicate we're in recovery mode
        last_successful_update = None  # Track when we last successfully completed an update
        operation_timeout = 30.0  # Timeout for individual operations
        
        while not self._shutdown_event.is_set():
            loop_start_time = asyncio.get_event_loop().time()
            
            try:
                self.log_action("Frequent Update Loop", f"Loop iteration started. Recovery mode: {recovery_mode}, Consecutive failures: {consecutive_failures}", "debug")

                # Circuit breaker: If we have too many consecutive failures, enter recovery mode
                if consecutive_failures >= max_consecutive_failures and not recovery_mode:
                    recovery_mode = True
                    self.log_action("Frequent Update Loop", f"Entering recovery mode after {consecutive_failures} consecutive failures", "warning")
                
                # In recovery mode, use longer timeouts and simpler operations
                current_timeout = operation_timeout * 2 if recovery_mode else operation_timeout

                # Fetch banner info immediately on first run, then every 15 minutes
                if first_run or banner_fetch_count >= 90:
                    self.log_action("Frequent Update Loop", "Attempting to fetch banner info.", "debug")
                    try:
                        await asyncio.wait_for(
                            self.banner_manager.fetch_banner_info(self.shared_state),
                            timeout=current_timeout
                        )
                        banner_fetch_count = 0  # Reset banner fetch counter
                        first_run = False  # Clear first run flag
                    except asyncio.TimeoutError:
                        self.log_action("Frequent Update Loop", f"Banner fetch timed out after {current_timeout}s", "warning")
                        banner_fetch_count = 0  # Reset to avoid getting stuck
                        first_run = False
                    except Exception as e:
                        self.log_action("Frequent Update Loop", f"Banner fetch failed: {str(e)}", "warning")
                        banner_fetch_count = 0  # Reset to avoid getting stuck
                        first_run = False

                # 1) Fetch block height with timeout
                self.log_action("Frequent Update Loop", "Attempting to get block height.", "debug")
                block_height = None
                try:
                    block_height = await asyncio.wait_for(
                        self.blockchain.get_block_height(),
                        timeout=current_timeout
                    )
                except asyncio.TimeoutError:
                    self.log_action("Frequent Update Loop", f"Block height fetch timed out after {current_timeout}s", "warning")
                except Exception as e:
                    self.log_action("Frequent Update Loop", f"Block height fetch failed: {str(e)}", "warning")
                
                if block_height is None:
                    consecutive_failures += 1
                    self.log_action("Failed to fetch block height.", f'Retrying in 10s... (failure #{consecutive_failures})', "error")
                    await asyncio.sleep(10)
                    continue
                    
                self.log_action("Frequent Update Loop", f"Block height fetched: {block_height}. Last known: {last_known_block_height}", "debug")
                
                # Compare with last known block height
                if last_known_block_height is not None:
                    if block_height == last_known_block_height:
                        consecutive_no_change += 1
                    else:
                        consecutive_no_change = 0  # Reset counter if block height changes
                else:
                    consecutive_no_change = 0  # Reset counter on first valid block height
                
                # Log and notify if block height hasn't changed for 10 loops (100 seconds)
                # But don't get stuck in a continue loop - limit the warning frequency
                if consecutive_no_change >= 10 and consecutive_no_change % 10 == 0:  # Log every 10 loops after the first warning
                    message = f"WARNING! Block height has not changed for {consecutive_no_change * 10} seconds.\nLast height: {last_known_block_height}"
                    self.log_action("Block Height Error!", message, "error")

                # Update last known block height and shared state
                last_known_block_height = block_height
                self.shared_state["block_height"] = block_height
                
                self.log_action("Frequent Update Loop", f"Loop count: {loopcnt}. Stake checking (local): {stake_checking}", "debug")
                
                # Perform balance and stake-info updates every X loops (e.g., 20 is ~3.3 minutes)
                if loopcnt >= 20 and not stake_checking:
                    self.log_action("Frequent Update (>=20 Loops)", f"Block height: {self.shared_state['block_height']}", "debug")
                    
                    # Set stake_checking flag to prevent overlapping operations
                    stake_checking = True
                    
                    try:
                        # Update wallet balances with timeout
                        self.log_action("Frequent Update Loop", "Attempting to get wallet balances.", "debug")
                        await asyncio.wait_for(
                            self.blockchain.get_wallet_balances(self.shared_state, self.monitor_wallet),
                            timeout=current_timeout
                        )
                        self.log_action("Frequent Update Loop", f"Wallet balances updated. Public: {self.shared_state['balances']['public']}, Shielded: {self.shared_state['balances']['shielded']}", "debug")
                    except asyncio.TimeoutError:
                        self.log_action("Frequent Update Loop", f"Wallet balance fetch timed out after {current_timeout}s", "warning")
                    except Exception as e:
                        self.log_action("Frequent Update Loop", f"Wallet balance fetch failed: {str(e)}", "warning")
                    
                    try:
                        # Update stake info with timeout
                        self.log_action("Frequent Update Loop", "Attempting to get stake info.", "debug")
                        e_stake, r_slashed, a_rewards = await asyncio.wait_for(
                            self.blockchain.get_stake_info(self.shared_state),
                            timeout=current_timeout
                        )
                        self.log_action("Frequent Update Loop", f"Stake info fetched: e_stake={e_stake}, r_slashed={r_slashed}, a_rewards={a_rewards}", "debug")
                        if e_stake is not None and r_slashed is not None:
                            self.shared_state["stake_info"]["stake_amount"] = e_stake
                            self.shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed
                            self.shared_state["stake_info"]["rewards_amount"] = a_rewards or 0.0
                            self.log_action("Frequent Update Loop", "Shared state updated with new stake info.", "debug")
                        else:
                            self.log_action("Frequent Update Loop", "Failed to get complete stake info for shared state update.", "debug")
                    except asyncio.TimeoutError:
                        self.log_action("Frequent Update Loop", f"Stake info fetch timed out after {current_timeout}s", "warning")
                    except Exception as e:
                        self.log_action("Frequent Update Loop", f"Stake info fetch failed: {str(e)}", "warning")
                    
                    try:
                        # Update market data with timeout
                        self.log_action("Frequent Update Loop", "Attempting to fetch market data.", "debug")
                        await asyncio.wait_for(
                            self.market_data.fetch_dusk_data(self.shared_state),
                            timeout=current_timeout
                        )
                        self.log_action("Frequent Update Loop", f"Market data updated. Price: {self.shared_state['price']}", "debug")
                    except asyncio.TimeoutError:
                        self.log_action("Frequent Update Loop", f"Market data fetch timed out after {current_timeout}s", "warning")
                    except Exception as e:
                        self.log_action("Frequent Update Loop", f"Market data fetch failed: {str(e)}", "warning")
                    
                    # Clear stake_checking flag and reset loop count
                    stake_checking = False
                    loopcnt = 0  # Reset loop count after update
                
                # Update peer count with timeout
                self.log_action("Frequent Update Loop", "Attempting to get peer count.", "debug")
                peer_count = None
                try:
                    peer_count = await asyncio.wait_for(
                        self.blockchain.get_peer_count(),
                        timeout=current_timeout
                    )
                except asyncio.TimeoutError:
                    self.log_action("Frequent Update Loop", f"Peer count fetch timed out after {current_timeout}s", "warning")
                except Exception as e:
                    self.log_action("Frequent Update Loop", f"Peer count fetch failed: {str(e)}", "warning")
                
                self.log_action("Frequent Update Loop", f"Peer count fetched: {peer_count}", "debug")
                if peer_count is not None:
                    self.shared_state["peer_count"] = peer_count
                    
                    # Check peer count
                    if peer_count < self.min_peers or peer_count <= 0:
                        consecutive_low_peers += 1
                    else:
                        consecutive_low_peers = 0  # Reset counter if peer count is good
                
                    # Log and notify if low count for too long (but limit frequency)
                    if consecutive_low_peers >= 240 and consecutive_low_peers % 60 == 0:  # Log every 60 loops after first warning
                        message = f"WARNING! Low peer count for {consecutive_low_peers * 10} seconds.\nCurrent Count: {peer_count}"
                        self.log_action("Low peer count!", message, "error")
                else:
                    consecutive_failures += 1
                    self.log_action("Failed to fetch peers.", f"Retrying in 10s... (failure #{consecutive_failures})", "error")
                    await asyncio.sleep(10)
                    continue

                # If we reach here, the loop iteration was mostly successful
                consecutive_failures = 0  # Reset failure counter
                last_successful_update = asyncio.get_event_loop().time()
                
                # Exit recovery mode if we've had a successful update
                if recovery_mode:
                    recovery_mode = False
                    self.log_action("Frequent Update Loop", "Exiting recovery mode after successful update", "info")

                loopcnt += 1
                banner_fetch_count += 1
                
                # Calculate how long this loop took and adjust sleep accordingly
                loop_duration = asyncio.get_event_loop().time() - loop_start_time
                sleep_time = max(1, 10 - loop_duration)  # Ensure at least 1 second sleep, adjust for loop duration
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                consecutive_failures += 1
                stake_checking = False  # Clear flag on any exception
                self.log_action("Error in Frequent Update Loop", f"Failure #{consecutive_failures}: {str(e)}", "error")
                
                # Use exponential backoff in recovery mode, but cap at 60 seconds
                if recovery_mode:
                    sleep_time = min(60, 30 * (2 ** min(consecutive_failures, 3)))
                    self.log_action("Frequent Update Loop", f"Recovery mode: sleeping for {sleep_time}s before retry.", "debug")
                else:
                    sleep_time = 30
                    self.log_action("Frequent Update Loop", f"Error caught. Sleeping for {sleep_time}s before retry.", "debug")
                
                await asyncio.sleep(sleep_time)
                
                # Emergency circuit breaker: If we've been failing for too long, log critical error
                current_time = asyncio.get_event_loop().time()
                if (last_successful_update is not None and 
                    current_time - last_successful_update > 600):  # 10 minutes without success
                    self.log_action("CRITICAL: Frequent Update Loop", 
                                  f"No successful updates for {int(current_time - last_successful_update)} seconds. "
                                  f"Consecutive failures: {consecutive_failures}", "error")
                
                # Check for shutdown between operations
                if self._shutdown_event.is_set():
                    break
                
    async def init_balance(self) -> None:
        """
        Initialize display values by fetching initial blockchain and market data.
        """
        # Fetch market data
        await self.market_data.fetch_dusk_data(self.shared_state)

        # Fetch block height
        block_height = await self.blockchain.get_block_height()
        if block_height is not None:
            self.shared_state["block_height"] = block_height
            
        # Fetch wallet balances
        await self.blockchain.get_wallet_balances(self.shared_state, self.monitor_wallet, True)
