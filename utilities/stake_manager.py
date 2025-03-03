import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Callable

from utilities.utils import format_float, calculate_rewards_per_epoch, calculate_downtime_loss
from utilities.blockchain_client import BlockchainClient

class StakeManager:
    """
    Manages staking operations for the Dusk Network.
    Handles stake monitoring, claiming rewards, and restaking.
    """
    
    def __init__(
        self, 
        blockchain_client: BlockchainClient,
        shared_state: Dict[str, Any],
        config: Dict[str, Any],
        log_action_func: Callable = None
    ):
        """
        Initialize the stake manager.
        
        Args:
            blockchain_client: Client for blockchain interactions
            shared_state: Shared state dictionary
            config: Configuration dictionary
            log_action_func: Function to call for logging
        """
        self.blockchain = blockchain_client
        self.shared_state = shared_state
        self.config = config
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        
        # Extract configuration values
        self.min_rewards = config.get('min_rewards', 1)
        self.min_slashed = config.get('min_slashed', 1)
        self.buffer_blocks = config.get('buffer_blocks', 60)
        self.min_stake_amount = config.get('min_stake_amount', 1000)
        self.auto_stake_rewards = config.get('auto_stake_rewards', False)
        self.auto_reclaim_full_restakes = config.get('auto_reclaim_full_restakes', False)
        
    def should_unstake_and_restake(self, reclaimable_slashed_stake: float, downtime_loss: float) -> bool:
        """
        Determine if unstaking/restaking is worthwhile.
        
        Args:
            reclaimable_slashed_stake: Amount of reclaimable slashed stake
            downtime_loss: Estimated loss during downtime
            
        Returns:
            True if unstaking and restaking is worthwhile, False otherwise
        """
        return (self.auto_reclaim_full_restakes and 
                (reclaimable_slashed_stake >= self.min_slashed and 
                    reclaimable_slashed_stake >= downtime_loss))

    def should_claim_and_stake(self, rewards: float, incremental_threshold: float) -> bool:
        """
        Determine if claiming and staking rewards is worthwhile.
        
        Args:
            rewards: Current rewards amount
            incremental_threshold: Minimum threshold for claiming
            
        Returns:
            True if claiming and staking is worthwhile, False otherwise
        """
        return (self.auto_stake_rewards and 
                (rewards >= self.min_rewards and 
                    rewards >= incremental_threshold))
        
    async def sleep_with_feedback(self, seconds: int, message: str = "") -> None:
        """
        Sleep for the specified number of seconds, updating the shared state with remaining time.
        
        Args:
            seconds: Number of seconds to sleep
            message: Message to log
        """
        # Validate the input seconds
        if seconds <= 0:
            self.log_action("Sleep Countdown", "Invalid sleep duration provided. Must be greater than 0.", "error")
            return  # Exit the function early

        # Calculate the completion time as a timestamp
        from datetime import datetime, timedelta
        now = datetime.now()
        completion_time = now + timedelta(seconds=seconds)
        
        # Store both the formatted time and the timestamp
        self.shared_state["completion_time"] = completion_time.strftime("%H:%M:%S")
        self.shared_state["completion_timestamp"] = int(completion_time.timestamp() * 1000)  # Milliseconds since epoch
        self.shared_state["remain_time"] = seconds  # Initialize the countdown
        
        if message:
            self.log_action("Sleep Countdown", f"{message} ({seconds}s)", "debug")
        
        try:
            # Sleep in 1-second increments, updating the remain_time each second
            while self.shared_state["remain_time"] > 0:
                await asyncio.sleep(1)
                self.shared_state["remain_time"] -= 1
        except Exception as e:
            self.log_action("Sleep Countdown", f"Error during sleep: {str(e)}", "error")
        finally:
            self.log_action("Sleep Countdown", "Sleep Finished", "debug")

    async def sleep_until_next_epoch(self, block_height: int, buffer_blocks: int = 60, msg: Optional[str] = None) -> None:
        """
        Sleep until near the end of the current epoch.
        Each epoch is 2160 blocks, 10s each. Subtract buffer_blocks from remainder.
        If result <= 0, do a minimal sleep of buffer blocks * 11.
        
        Args:
            block_height: Current block height
            buffer_blocks: Number of blocks to use as buffer
            msg: Message to log
        """
        if not msg:
            msg = "until closer to next epoch..."

        blocks_left = 2160 - (block_height % 2160) - buffer_blocks
        sleep_time = blocks_left * 10  # 10s per block

        if sleep_time <= 0:
            sleep_time = buffer_blocks * 11
            msg = "Epoch boundary reached; forcing minimal sleep."

        # Validate the sleep time
        if sleep_time <= 0:
            self.log_action("Sleep Countdown", "Invalid sleep duration calculated. Must be greater than 0.", "error")
            return  # Exit the function early

        try:
            await self.sleep_with_feedback(sleep_time, msg)
        except Exception as e:
            self.log_action("Sleep Countdown", f"Error during sleep until next epoch: {str(e)}", "error")
        
    async def perform_unstake_restake(self, block_height: int, stake_amount: float, rewards_amount: float, reclaimable_slashed_stake: float, downtime_loss: float) -> bool:
        """
        Perform unstake and restake operation.
        
        Args:
            block_height: Current block height
            stake_amount: Current stake amount
            rewards_amount: Current rewards amount
            reclaimable_slashed_stake: Amount of reclaimable slashed stake
            downtime_loss: Estimated loss during downtime
            
        Returns:
            True if successful, False otherwise
        """
        total_restake = stake_amount + rewards_amount + reclaimable_slashed_stake
        
        if total_restake < self.min_stake_amount:
            self.shared_state["last_action_taken"] = "Unstake/Restake Skipped (Below Min)"
            self.log_action(
                f"Unstake/Restake Skipped (Block #{block_height})",
                f"Total restake ({format_float(total_restake)} DUSK) < {self.min_stake_amount} DUSK.\n"
                f"Rwd: {format_float(rewards_amount)}, Stk: {format_float(stake_amount)}, "
                f"Rcl: {format_float(reclaimable_slashed_stake)}"
            )
            return False
            
        # Unstake & Restake
        act_msg = f"Start Unstake/Restake @ Block #{block_height}"
        self.shared_state["last_action_taken"] = act_msg
        
        self.log_action(
            act_msg,
            f"Rwd: {format_float(rewards_amount)}, Stake: {format_float(stake_amount)}, "
            f"Rcl: {format_float(reclaimable_slashed_stake)}\n"
            f"Reclaimable: {format_float(reclaimable_slashed_stake)}, Downtime Loss: {format_float(downtime_loss)}"
        )
        
        # 1) Withdraw
        if not await self.blockchain.withdraw_rewards():
            return False
        
        # 2) Unstake
        if not await self.blockchain.unstake():
            return False
        
        # 3) Stake
        total_restake = stake_amount + rewards_amount + reclaimable_slashed_stake
        if not await self.blockchain.stake(total_restake):
            return False

        self.log_action("Full Restake Completed", f"New Stake: {format_float(float(total_restake))}")
        self.shared_state["last_claim_block"] = block_height
        
        return True
        
    async def perform_claim_stake(self, block_height: int, stake_amount: float, rewards_amount: float, reclaimable_slashed_stake: float) -> bool:
        """
        Perform claim and stake operation.
        
        Args:
            block_height: Current block height
            stake_amount: Current stake amount
            rewards_amount: Current rewards amount
            reclaimable_slashed_stake: Amount of reclaimable slashed stake
            
        Returns:
            True if successful, False otherwise
        """
        self.shared_state["last_action_taken"] = f"Claim/Stake @ Block {block_height}"
        self.log_action(
            self.shared_state["last_action_taken"],
            f"Rwd: {format_float(rewards_amount)}, Stk: {format_float(stake_amount)}, "
            f"Rcl: {format_float(reclaimable_slashed_stake)}"
        )

        # 1) Withdraw
        if not await self.blockchain.withdraw_rewards():
            return False
        
        # 2) Stake
        if not await self.blockchain.stake(rewards_amount):
            return False
        
        new_stake = stake_amount + rewards_amount

        self.log_action("Stake Completed", f"New Stake: {format_float(new_stake)}")
        self.shared_state["last_claim_block"] = block_height
        
        return True
        
    async def log_status(self, block_height: int, action: str) -> None:
        """
        Log current status.
        
        Args:
            block_height: Current block height
            action: Current action
        """
        b = self.shared_state["balances"]
        now_ts = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        log_info = (
            f"\t==== Activity @{now_ts}====\n"
            f"  Action              :  {action}\n\n"
            f"  Balance           :  {format_float(b['public'] + b['shielded'],)}\n"
            f"    ├─ Public      :    {format_float(b['public'])} "
            f"(${format_float(b['public'] * float(self.shared_state['price']))})\n"
            f"    └─ Shielded  :    {format_float(b['shielded'])} "
            f"(${format_float(b['shielded'] * float(self.shared_state['price']))})\n\n"
            f"  Staked              :  {format_float(self.shared_state.get('stake_info',{}).get('stake_amount','0.0'))} "
            f"(${format_float(self.shared_state.get('stake_info',{}).get('stake_amount','0.0') * float(self.shared_state['price']))})\n"
            f"  Rewards           :  {format_float(self.shared_state.get('stake_info',{}).get('rewards_amount','0.0'))} "
            f"(${format_float(self.shared_state.get('stake_info',{}).get('rewards_amount',{}) * float(self.shared_state['price']))})\n"
            f"  Reclaimable    :  {format_float(self.shared_state.get('stake_info',{}).get('reclaimable_slashed_stake','0.0'))} "
            f"(${format_float(self.shared_state.get('stake_info',{}).get('reclaimable_slashed_stake') * float(self.shared_state['price']))})\n"
        )
        
        # Add to log entries
        log_entries = self.shared_state.get("log_entries", [])
        if len(log_entries) > 15:  # TODO: Make configurable
            log_entries.pop(0)
        log_entries.append(log_info)
        self.shared_state["log_entries"] = log_entries
        
        # Notify
        from utilities.notifications import NotificationService
        notifier = self.shared_state.get("notifier")
        if notifier and isinstance(notifier, NotificationService):
            notifier.notify(log_info, self.shared_state)
        
    async def stake_management_loop(self) -> None:
        """
        Main staking logic. Sleeps until the next epoch after each action/no-action.
        Meanwhile, frequent_update_loop updates block height & balances for display.
        """
        first_run = True
        stake_checking = False

        while True:
            try:
                # For logic, we may want a fresh block height right before we do anything:
                block_height = await self.blockchain.get_block_height()
                if block_height is None:
                    self.log_action("Failed to fetch block height", "Retrying in 30s...", "error")
                    stake_checking = False
                    await self.sleep_with_feedback(30, "retry block height fetch")
                    continue

                self.shared_state["block_height"] = block_height

                # If we already saw 'No Action' for this block, wait a bit
                if self.shared_state["last_no_action_block"] == block_height:
                    msg = f"Already did 'No Action' at block {block_height}; sleeping 30s."
                    stake_checking = False
                    await self.sleep_with_feedback(30, msg)
                    continue

                # Fetch stake-info
                stake_checking = True 
                e_stake, r_slashed, a_rewards = await self.blockchain.get_stake_info(self.shared_state)
                if e_stake is None or r_slashed is None or a_rewards is None:
                    self.log_action("Skipping Cycle", "Parsing stake info incomplete. Sleeping 60s...", 'debug')
                    stake_checking = False
                    await self.sleep_with_feedback(60, "skipping cycle")
                    continue
                
                # Update in shared state
                self.shared_state["stake_info"]["stake_amount"] = e_stake
                self.shared_state["stake_info"]["reclaimable_slashed_stake"] = r_slashed
                self.shared_state["stake_info"]["rewards_amount"] = a_rewards

                stake_checking = False
                # For logic thresholds
                last_claim_block = self.shared_state["last_claim_block"]
                stake_amount = e_stake or 0.0
                reclaimable_slashed_stake = r_slashed or 0.0
                rewards_amount = a_rewards or 0.0

                rewards_per_epoch = calculate_rewards_per_epoch(rewards_amount, last_claim_block, block_height)
                self.shared_state["rewards_per_epoch"] = rewards_per_epoch
                downtime_loss = calculate_downtime_loss(rewards_per_epoch, downtime_epochs=2)
                incremental_threshold = rewards_per_epoch
                
                # Should this check first run and wait till first epoch? need to test
                if (self.should_unstake_and_restake(reclaimable_slashed_stake, downtime_loss) and 
                    not first_run and reclaimable_slashed_stake and e_stake > 0):
                    
                    success = await self.perform_unstake_restake(
                        block_height, stake_amount, rewards_amount, 
                        reclaimable_slashed_stake, downtime_loss
                    )
                    
                    if success:
                        stake_checking = False
                        rewards_per_epoch = 0
                        self.shared_state["rewards_per_epoch"] = rewards_per_epoch
                        # Sleep 2 epochs
                        await self.sleep_until_next_epoch(block_height + 2160, msg="2-epoch wait after restaking...")
                        continue
                    else:
                        stake_checking = False
                        # If failed, wait a bit and try again
                        await self.sleep_with_feedback(300, "waiting after failed unstake/restake")
                        continue

                elif self.should_claim_and_stake(rewards_amount, incremental_threshold) and not first_run:
                    # Claim & Stake
                    success = await self.perform_claim_stake(
                        block_height, stake_amount, rewards_amount, reclaimable_slashed_stake
                    )
                    
                    if success:
                        stake_checking = False
                        self.log_action("Stake Loop", "Finished staking, now sleeping.", "debug")
                        await self.sleep_with_feedback(2160 * 10, "1 epoch wait after claiming")
                        self.log_action("Stake Loop", "Woke up from sleep.", "debug")
                        rewards_per_epoch = 0
                        self.shared_state["rewards_per_epoch"] = rewards_per_epoch
                        continue
                    else:
                        stake_checking = False
                        # If failed, wait a bit and try again
                        await self.sleep_with_feedback(300, "waiting after failed claim/stake")
                        continue
                else:
                    # No action
                    self.shared_state["last_no_action_block"] = block_height
                    self.shared_state["last_action_taken"] = f"No Action @ Block {block_height}"
                    
                    if first_run:
                        self.shared_state["last_action_taken"] = f"Startup @ Block #{block_height}"
                        await self.log_status(block_height, self.shared_state["last_action_taken"])
                        first_run = False
                        stake_checking = False
                    else:
                        stake_checking = False
                        # If no action, just wait and don't log since it's no longer first run
                        await self.sleep_until_next_epoch(block_height, buffer_blocks=self.buffer_blocks)
                        continue
                
            except Exception as e:
                stake_checking = False
                self.log_action("Error in stake management loop", str(e), "error")
                await self.sleep_with_feedback(60, "error recovery")
                
            # Sleep until near the next epoch
            stake_checking = False
            await self.sleep_until_next_epoch(block_height, buffer_blocks=self.buffer_blocks)
