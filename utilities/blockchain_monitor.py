import asyncio
from typing import Dict, Any, Optional, Callable

from utilities.blockchain_client import BlockchainClient
from utilities.market_data import MarketDataClient

class BlockchainMonitor:
    """
    Monitors the blockchain for updates to block height, peer count, and other metrics.
    Periodically updates the shared state with the latest information.
    """
    
    def __init__(
        self, 
        blockchain_client: BlockchainClient,
        market_data_client: MarketDataClient,
        shared_state: Dict[str, Any],
        config: Dict[str, Any],
        log_action_func: Callable = None
    ):
        """
        Initialize the blockchain monitor.
        
        Args:
            blockchain_client: Client for blockchain interactions
            market_data_client: Client for market data
            shared_state: Shared state dictionary
            config: Configuration dictionary
            log_action_func: Function to call for logging
        """
        self.blockchain = blockchain_client
        self.market_data = market_data_client
        self.shared_state = shared_state
        self.config = config
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        self.state_lock = asyncio.Lock() # Add lock for shared state access
        
        # Extract configuration values
        self.min_peers = config.get('min_peers', 10)
        self.monitor_wallet = config.get('monitor_wallet', False)
        self.password = config.get('password', '')
        
    async def frequent_update_loop(self) -> None:
        """
        Update the block height and balances every 10 seconds (adjusted from 20).
        Checks if the block height changes to ensure node responsiveness.
        Uses locks for shared state access.
        """
        loopcnt = 0
        consecutive_no_change = 0
        last_known_block_height = None
        consecutive_low_peers = 0
        
        while True:
            try:
                # Fetch block height (no lock needed for read-only operation here)
                block_height = await self.blockchain.get_block_height()
                if block_height is None:
                    self.log_action("Failed to fetch block height.", ' Retrying in 10s...', "error")
                    await asyncio.sleep(10)
                    continue
                
                # Compare with last known block height (local variable)
                if last_known_block_height is not None:
                    if block_height == last_known_block_height:
                        consecutive_no_change += 1
                    else:
                        consecutive_no_change = 0
                else:
                    consecutive_no_change = 0
                
                # Log and notify if block height hasn't changed
                if consecutive_no_change >= 10: # Check every 10 loops (100 seconds)
                    message = f"WARNING! Block height has not changed for {consecutive_no_change * 10} seconds.\nLast height: {last_known_block_height}"
                    self.log_action("Block Height Error!", message, "error")
                    consecutive_no_change = 0
                    await asyncio.sleep(1) # Short pause before continuing
                    # Do not continue here, allow other checks to run

                # Update last known block height and shared state under lock
                last_known_block_height = block_height
                async with self.state_lock:
                    self.shared_state["block_height"] = block_height
                
                # Check stake_checking flag under lock
                async with self.state_lock:
                    stake_checking = self.shared_state.get("stake_checking", False)
                
                # Perform balance and stake-info updates every X loops
                # Adjusted to run every 20 loops (200 seconds = ~3.3 mins)
                if loopcnt >= 20 and not stake_checking:
                    self.log_action("Frequent Update Triggered", f"Block height: {block_height}", "debug")
                    
                    # Update wallet balances (already handles state internally with locks)
                    await self.blockchain.get_wallet_balances(self.shared_state, self.monitor_wallet)
                    
                    # Update stake info (already handles state internally with locks)
                    await self.blockchain.get_stake_info(self.shared_state)
                    
                    # Update market data (already handles state internally with locks)
                    await self.market_data.fetch_dusk_data(self.shared_state)
                        
                    loopcnt = 0 # Reset loop count
                
                # Update peer count
                peer_count = await self.blockchain.get_peer_count()
                if peer_count is not None:
                    async with self.state_lock: # Lock for writing peer count
                        self.shared_state["peer_count"] = peer_count
                    
                    # Check peer count (local logic, no lock needed for read)
                    if peer_count < self.min_peers or peer_count <= 0:
                        consecutive_low_peers += 1
                    else:
                        consecutive_low_peers = 0
                
                    # Log and notify if low count for too long
                    if consecutive_low_peers >= 240: # 240 loops * 10 seconds = 40 minutes
                        message = f"WARNING! Low peer count for {consecutive_low_peers * 10} seconds.\nCurrent Count: {peer_count}"
                        self.log_action("Low peer count!", message, "error")
                        consecutive_low_peers = 0
                else:
                    self.log_action("Failed to fetch peers.", "Retrying in 10s...", "error")
                    # No need to sleep here, loop will handle it

                loopcnt += 1
                await asyncio.sleep(10) # Wait 10 seconds before the next loop
                
            except asyncio.CancelledError: # Handle task cancellation
                self.log_action("Blockchain Monitor Loop", "Cancellation requested.", "info")
                break # Exit the loop cleanly
            except Exception as e:
                async with self.state_lock: # Reset stake checking flag on error
                    self.shared_state["stake_checking"] = False
                self.log_action("Error in Frequent Update Loop", str(e), "error")
                await asyncio.sleep(30) # Wait longer after an error
                
    async def init_balance(self) -> None:
        """
        Initialize display values by fetching initial blockchain and market data.
        Uses locks for shared state access where necessary.
        """
        try:
            # Fetch market data (updates state internally)
            await self.market_data.fetch_dusk_data(self.shared_state)

            # Fetch block height
            block_height = await self.blockchain.get_block_height()
            if block_height is not None:
                async with self.state_lock: # Lock for writing block height
                    self.shared_state["block_height"] = block_height
                
            # Fetch wallet balances (updates state internally)
            await self.blockchain.get_wallet_balances(self.shared_state, self.monitor_wallet, True)
        except Exception as e:
            self.log_action("Initialization Error", f"Failed during initial balance/data fetch: {str(e)}", "error")
