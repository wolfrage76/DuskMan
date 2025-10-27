import asyncio
import subprocess
import textwrap
from rich.console import Console

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable

from rich.live import Live
from rich.text import Text
from rich.console import Console

from utilities.utils import format_float, format_hms, remove_ansi, convert_timestamp, display_wallet_distribution_bar, format_number
from utilities.colors import *


class DisplayManager:
    """
    Manages the real-time display of blockchain and staking information.
    Handles console output and TMUX status bar updates.
    """
    
    def __init__(
        self, 
        shared_state: Dict[str, Any],
        status_bar_config: Dict[str, Any],
        display_gui: bool = True,
        enable_tmux: bool = False,
        log_action_func: Callable = None
    ):
        """
        Initialize the display manager.
        
        Args:
            shared_state: Shared state dictionary
            status_bar_config: TMUX status bar configuration
            display_gui: Whether to display the GUI
            enable_tmux: Whether to enable TMUX integration
            log_action_func: Function to call for logging
        """
        self.shared_state = shared_state
        self.status_bar_config = status_bar_config
        self.display_gui = display_gui
        self.enable_tmux = enable_tmux
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        self.console = Console(
            force_terminal=True, 
            force_interactive=True,
            width=None,  # Let the terminal determine width
            height=None,  # Let the terminal determine height
            legacy_windows=False  # Use modern Windows terminal features
        )
        
    async def realtime_display_loop(self) -> None:
        """
        Continuously display real-time info in the console.
        Initially shows configuration and byline, then switches to real-time stats.
        Uses raw ANSI escape sequences for reliable terminal control.
        """
        while True:
                try:
                    # Get current state
                    blk = self.shared_state["block_height"]
                    st_info = self.shared_state["stake_info"]
                    b = self.shared_state["balances"]
                    last_act = self.shared_state["last_action_taken"]
                    remain_seconds = self.shared_state["remain_time"]
                    
                    disp_time = format_hms(remain_seconds) if remain_seconds > 0 else "Processing..."
                    donetime = self.shared_state["completion_time"] if remain_seconds > 0 else " "
                    
                    if donetime == '--:--':
                        await asyncio.sleep(2)
                        continue
                        
                    tot_bal = b["public"] + b["shielded"]
                    price = self.shared_state["price"]
                    
                    # Determine color for timer based on remaining time
                    charclr = (
                        RED if remain_seconds <= 3600 else
                        YELLOW if remain_seconds <= 7200 else
                        GREEN if remain_seconds <= 10800 else
                        LIGHT_WHITE
                    )
                        
                    timer = f"Next:{charclr} {disp_time} "
                    chg24 = f"{GREEN if self.shared_state['usd_24h_change'] > 0 else RED if self.shared_state['usd_24h_change'] < 0 else DEFAULT}{self.shared_state['usd_24h_change']:.2f}% 24h"
                    usd = f"$USD: {format_float(self.shared_state['price'],3)} {chg24} | "
                    
                    # Determine color for peer count based on number of peers
                    peercolor = next(
                        color for color, condition in {
                            RED: lambda x: x <= 16,
                            YELLOW: lambda x: 16 < x <= 40,
                            LIGHT_GREEN: lambda x: x > 40
                        }.items() if condition(int(self.shared_state['peer_count']))
                    )

                    currenttime = datetime.now().strftime('%H:%M:%S')
                    epoch_num = int(blk / 2160)
                    # Remove trailing newline from top_bar definition
                    top_bar = f" {LIGHT_WHITE}======={DEFAULT} {currenttime} Block: {LIGHT_BLUE}#{blk} {DEFAULT}(E: {LIGHT_BLUE}{epoch_num}{DEFAULT}) Peers: {peercolor}{self.shared_state['peer_count']}{DEFAULT} {LIGHT_WHITE}======={DEFAULT}"

                    allocation_bar = display_wallet_distribution_bar(b['public'], b['shielded'], 8)
                    
                    # Calculate rewards per epoch
                    per_epoch = str()
                    rpe = self.shared_state.get('rewards_per_epoch', 0.0)
                    if rpe > 0.0:
                        if int(self.shared_state.get("last_claim_block", 0)) > 0:
                            per_epoch = f"@ Epoch/claim: {format_float(rpe)}"
                    
                    # Calculate reward percentage
                    reward_percent = 0.0
                    if st_info.get('rewards_amount', 0.0) > 0.0 and st_info.get('stake_amount', 0.0) > 0.0:
                        reward_percent = (st_info.get('rewards_amount', 0.0) / st_info.get('stake_amount', 0.0)) * 100
                    
                    # Check if stake is active
                    active_block = self.shared_state.get("active_blk", 2160)
                    if int(blk) - active_block >= 0:
                        is_active = str() 
                    else:
                        active_secs = (active_block - blk) * 10
                        when_active = (datetime.now() + timedelta(seconds=active_secs)).strftime('%H:%M')
                        is_active = f"{LIGHT_RED}\n\tActive @ {when_active} - #{active_block} (E: {int(active_block/2160)}){DEFAULT}\n"               
                    
                    # Get price change percentages
                    chg7d = self.shared_state["price_change_percentage_7d_in_currency"] or 0.0
                    chg30d = self.shared_state["price_change_percentage_30d_in_currency"] or 0.0
                    chg1y = self.shared_state["price_change_percentage_1y_in_currency"] or 0.0
                    
                    # Market data
                    volume = self.shared_state["volume"] or 0.0
                    mkt_cap = self.shared_state["market_cap"] or 0.0
                    mkt_cap_change = self.shared_state["market_cap_change_percentage_24h"] or 0.0
                    
                    ath = self.shared_state["ath"] or 0.0
                    ath_change = self.shared_state["ath_change_percentage"] or 0.0
                    ath_date = self.shared_state["ath_date"]
                    
                    if self.shared_state['market_cap_change_percentage_24h'] > 0:
                        mcap_color = GREEN
                    else:
                        mcap_color = RED
                    
                    atl = self.shared_state["atl"] or 0.0
                    atl_date = self.shared_state["atl_date"]
                    mcap = f'{LIGHT_WHITE}24hr Volume: ${format_number(volume)}  Market Cap: ${format_number(mkt_cap)} ({mcap_color}{mkt_cap_change:.2f}%{LIGHT_WHITE})\n'
                    athl = f' {LIGHT_WHITE}ATH: ${format_float(ath)} ({ath_change:.2f}%) {convert_timestamp(ath_date)} | ATL: ${format_float(atl)} {convert_timestamp(atl_date)}\n'
                    
                    # Banner processing
                    banner_message_raw = self.shared_state.get("banner_message", "")
                    final_banner_string = "" # This will hold the fully formatted multi-line banner

                    if banner_message_raw:
                        top_bar_plain_width = len(remove_ansi(top_bar))
                        wrap_width = max(1, top_bar_plain_width - 4)
                        raw_lines = banner_message_raw.split('\n')
                        all_processed_segments = []

                        for raw_line in raw_lines:
                            wrapped_segments = textwrap.wrap(
                                raw_line,
                                width=wrap_width,
                                break_long_words=True,
                                replace_whitespace=False, # Do not replace existing whitespace in raw_line more than necessary
                                expand_tabs=False
                            )
                            if wrapped_segments:  # Only add non-empty segments
                                all_processed_segments.extend(wrapped_segments)
                            else:
                                # If textwrap.wrap returns empty (e.g., for empty lines), preserve the empty line
                                all_processed_segments.append("")

                        # Now center each segment and build the final banner string
                        for segment in all_processed_segments:
                            segment_plain_width = len(remove_ansi(segment))
                            if top_bar_plain_width > segment_plain_width:
                                padding_width = (top_bar_plain_width - segment_plain_width) // 2
                                padding = ' ' * padding_width
                            else:
                                padding = ""
                            final_banner_string += f" {LIGHT_CYAN}{padding}{segment}{DEFAULT}\n"

                        # Add separator line
                        separator_line = f" {LIGHT_WHITE}{'-' * (top_bar_plain_width - 2)}{DEFAULT}\n"
                        final_banner_string = separator_line + final_banner_string

                    # Determine color for last action text
                    if "Insufficient balance" in last_act or "Operation skipped" in last_act:
                        last_act_color = LIGHT_RED
                    else:
                        last_act_color = CYAN
                    
                    # Process byline text to center it based on top bar width
                    top_bar_plain_width = len(remove_ansi(top_bar))
                    options_text = self.shared_state.get("options", "")
                    
                    
                    # Split options into lines and process the byline (first line)
                    options_lines = options_text.split('\n')
                    if options_lines:
                        byline_text = options_lines[0]
                        byline_plain_width = len(remove_ansi(byline_text))
                        
                        # Center the byline based on top bar width
                        if top_bar_plain_width > byline_plain_width:
                            padding_width = (top_bar_plain_width - byline_plain_width) // 2
                            padding = ' ' * padding_width
                        else:
                            padding = ""
                        
                        # Replace the first line with centered byline
                        options_lines[0] = f"{padding}{byline_text}"
                        
                        # Reconstruct the options text
                        processed_options = '\n'.join(options_lines)
                    else:
                        processed_options = options_text
                    
                    # Build the complete content string with correct newline placement
                    realtime_content = (
                        f"{processed_options}"  # Display processed options with centered byline
                        f"{top_bar}\n"       # Line 2: Top bar, add newline after
                        f"    {CYAN}Last Action{DEFAULT}   | {last_act_color}{last_act}{DEFAULT}\n"
                        f"    {LIGHT_GREEN}Next Check    {DEFAULT}| {charclr}{disp_time}{DEFAULT} ({donetime}){DEFAULT}\n"
                        f"                  |\n"
                        f"    {LIGHT_WHITE}Price USD{DEFAULT}     | {LIGHT_WHITE}${format_float(price,3)}{DEFAULT} {chg24}\n"
                        f"                  {DEFAULT}| 7d: {chg7d:.2f}% 30d: {chg30d:.2f}% 1y: {chg1y:.2f}%\n"
                        f"                  |\n"
                        f"    {LIGHT_WHITE}Balance{DEFAULT}       | {LIGHT_WHITE}{allocation_bar}\n"
                        f"      {LIGHT_WHITE}├─ {YELLOW}Public   {DEFAULT}| {YELLOW}{format_float(b['public'])} (${format_float(b['public'] * price, 2)}){DEFAULT}\n"
                        f"      {LIGHT_WHITE}└─ {BLUE}Shielded {DEFAULT}| {BLUE}{format_float(b['shielded'])} (${format_float(b['shielded'] * price, 2)}){DEFAULT}\n"
                        f"         {LIGHT_WHITE}   Total {DEFAULT}| {LIGHT_WHITE}{format_float(tot_bal)} DUSK (${format_float((tot_bal) * price, 2)}){DEFAULT}\n"
                        f"                  |\n"
                        f"    {LIGHT_WHITE}Staked{DEFAULT}        | {LIGHT_WHITE}{format_float(st_info['stake_amount'])} (${format_float(st_info['stake_amount'] * price, 2)}){DEFAULT}{is_active}\n"
                        f"    {YELLOW}Rewards{DEFAULT}       | {YELLOW}{format_float(st_info['rewards_amount'])} ({LIGHT_BLUE}{reward_percent:.4f}%{DEFAULT}) (${format_float(st_info['rewards_amount'] * price, 2)}) {LIGHT_WHITE}{per_epoch}{DEFAULT}\n"
                        f"    {LIGHT_RED}Reclaimable{DEFAULT}   | {LIGHT_RED}{format_float(st_info['reclaimable_slashed_stake'])} (${format_float(st_info['reclaimable_slashed_stake'] * price, 2)}){DEFAULT}\n"
                        f" {LIGHT_WHITE}{('=' * (len(remove_ansi(top_bar)) - 2))}{DEFAULT}\n"
                        f"  {mcap} {athl}"
                        f"{final_banner_string}"
                    )


                    # Update rendered content in shared state if needed
                    include_rendered = self.shared_state.get("include_rendered", False)
                    if include_rendered:
                        self.shared_state["rendered"] = realtime_content
                    else:
                        self.shared_state["rendered"] = None
                    
                    # Update the display using manual clearing for reliability
                    if self.display_gui:
                        # Use ANSI escape codes for more reliable clearing across all terminals
                        import sys
                        # Clear screen and move cursor to home position
                        sys.stdout.write("\033[2J\033[H")
                        sys.stdout.flush()
                        # Print the content directly without Rich processing
                        sys.stdout.write(realtime_content)
                        sys.stdout.flush()

                    # Update TMUX status bar
                    if self.enable_tmux:
                        self._update_tmux_status_bar()

                    await asyncio.sleep(0.5)  # Sleep for 0.5 seconds to match 2 FPS refresh rate

                except Exception as e:
                    self.log_action(f"Error in real-time display", str(e), "error")
                    await asyncio.sleep(5)
                    
    def _update_tmux_status_bar(self) -> None:
        """Update the TMUX status bar with current information."""
        try:
            # Get current state
            blk = self.shared_state["block_height"]
            st_info = self.shared_state["stake_info"]
            b = self.shared_state["balances"]
            
            # Prepare status bar components
            curblk = f"\r> Blk: #{blk} | "
            stk = f"Stk: {format_float(st_info['stake_amount'])} | "
            rcl = f"Rcl: {format_float(st_info['reclaimable_slashed_stake'])} | "
            rwd = f"Rwd: {format_float(st_info['rewards_amount'])} | "
            bal = "Bal: "
            p = f"P:{format_float(b['public'])}"
            s = f"S:{format_float(b['shielded'])}"
            
            # Determine which fields to show based on config
            fields = {
                'curblk': self.status_bar_config.get('show_current_block', True),
                'stk': self.status_bar_config.get('show_staked', True),
                'p': self.status_bar_config.get('show_public', True),
                's': self.status_bar_config.get('show_shielded', True),
                'bal': self.status_bar_config.get('show_total', True),
                'rwd': self.status_bar_config.get('show_rewards', True),
                'rcl': self.status_bar_config.get('show_reclaimable', True),
                'usd': self.status_bar_config.get('show_price', True),
                'timer': self.status_bar_config.get('show_timer', True),
                'donetime': self.status_bar_config.get('show_trigger_time', True),
                'peercnt': self.status_bar_config.get('show_peer_count', True)
            }

            # Clear fields that shouldn't be shown
            for key, show in fields.items():
                if not show:
                    locals()[key] = str()

            # Handle special cases
            if not fields['p'] and not fields['s']:
                bal = splitter = str()
            if fields['p'] and fields['s']:
                spacer = "  "
            else:
                spacer = ""

            # Additional components
            error_txt = "- !ERROR DETECTED!" if self.shared_state.get("errored", False) else str()
            last_txt = str()  # last_act
            donetime = f"{DEFAULT}({self.shared_state['completion_time']}) "
            peercnt = f"Peers: {self.shared_state['peer_count']}"
            splitter = " | "
            usd = f"$USD: {format_float(self.shared_state['price'],3)} | "
            timer = f"Next: {format_hms(self.shared_state['remain_time'])} "
            
            # Build the complete status bar
            tmux_status = (
                f"\r> {curblk}{stk}{rcl}{rwd}{bal}{p}{spacer}{s}{splitter}"
                f"{usd}{last_txt}{timer}{donetime}{peercnt} {error_txt}"
            )

            # Update TMUX status bar
            subprocess.check_call(["tmux", "set-option", "-g", "status-left", remove_ansi(tmux_status)])
        except subprocess.CalledProcessError:
            self.log_action("tmux Error", "Failed to update tmux status bar. Is tmux running?", "debug")
            self.enable_tmux = False
        except Exception as e:
            self.log_action("tmux Error", f"Error updating tmux status bar: {str(e)}", "debug")
            self.enable_tmux = False

    async def _cleanup_old_state(self):
        """Periodically clean up old state to prevent memory leaks."""
        # Clean up old log entries if they exceed limits
        log_entries = self.shared_state.get("log_entries", [])
        max_entries = self.config.get('max_log_entries', 50)
        
        if len(log_entries) > max_entries:
            self.shared_state["log_entries"] = log_entries[-max_entries:]