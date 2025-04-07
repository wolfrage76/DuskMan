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
        
        # Extract configuration values
        self.min_peers = config.get('min_peers', 10)
        self.monitor_wallet = config.get('monitor_wallet', False)
        self.password = config.get('password', '')
        
    async def frequent_update_loop(self) -> None:
        """
        Update the block height and balances every 20 seconds.
        Checks if the block height changes to ensure node responsiveness.
        """
        stake_checking = False
        loopcnt = 0
        consecutive_no_change = 0  # Counter for consecutive no-change in block height
        last_known_block_height = None  # Track the last block height
        consecutive_low_peers = 0  # Track loops of low peer counts
        
        while True:
            try:
                # 1) Fetch block height
                block_height = await self.blockchain.get_block_height()
                if block_height is None:
                    self.log_action("Failed to fetch block height.", ' Retrying in 10s...', "error")
                    await asyncio.sleep(10)
                    continue
                
                # Compare with last known block height
                if last_known_block_height is not None:
                    if block_height == last_known_block_height:
                        consecutive_no_change += 1
                    else:
                        consecutive_no_change = 0  # Reset counter if block height changes
                else:
                    consecutive_no_change = 0  # Reset counter on first valid block height
                
                # Log and notify if block height hasn't changed for 10 loops (100 seconds)
                if consecutive_no_change >= 10:
                    message = f"WARNING! Block height has not changed for {consecutive_no_change * 10} seconds.\nLast height: {last_known_block_height}"
                    self.log_action("Block Height Error!", message, "error")
                    
                    consecutive_no_change = 0  # Reset after notifying to avoid spamming
                    await asyncio.sleep(1)
                    continue

                # Update last known block height and shared state
                last_known_block_height = block_height
                self.shared_state["block_height"] = block_height
                
                # Perform balance and stake-info updates every X loops (e.g., 30 is 5 minutes)
                if loopcnt >= 20 and not stake_checking:
                    self.log_action("Frequent Update (>=20 Loops)", f"Block height: {self.shared_state['block_height']}", "debug")
                    
                    # Update wallet balances
                    await self.blockchain.get_wallet_balances(self.shared_state, self.monitor_wallet)
                    
                    # Update stake info
                    e_stake, r_slashed, a_rewards = await self.blockchain.get_stake_info(self.shared_state)
                    if e_stake is not None and r_slashed is not None:
                        self.shared_state["stake_info"]["stake_amount"] = e_stake
                        self.shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed
                        self.shared_state["stake_info"]["rewards_amount"] = a_rewards or 0.0
                    
                    # Update market data
                    await self.market_data.fetch_dusk_data(self.shared_state)
                        
                    loopcnt = 0  # Reset loop count after update
                
                # Update peer count
                peer_count = await self.blockchain.get_peer_count()
                if peer_count is not None:
                    self.shared_state["peer_count"] = peer_count
                    
                    # Check peer count
                    if peer_count < self.min_peers or peer_count <= 0:
                        consecutive_low_peers += 1
                    else:
                        consecutive_low_peers = 0  # Reset counter if peer count is good
                
                    # Log and notify if low count for too long
                    if consecutive_low_peers >= 240:  # 240 loops * 10 seconds = 40 minutes
                        message = f"WARNING! Low peer count for {consecutive_low_peers * 10} seconds.\nCurrent Count: {peer_count}"
                        self.log_action("Low peer count!", message, "error")
                        
                        consecutive_low_peers = 0  # Reset after notifying to avoid spamming
                else:
                    self.log_action("Failed to fetch peers.", "Retrying in 10s...", "error")
                    await asyncio.sleep(10)
                    continue

                loopcnt += 1
                await asyncio.sleep(10)  # Wait 10 seconds before the next loop
                
            except Exception as e:
                stake_checking = False
                self.log_action("Error in Frequent Update Loop", str(e), "error")
                await asyncio.sleep(30)  # Wait longer after an error
                
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
