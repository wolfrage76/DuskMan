## Displays data from remote ##
## Web Dashboard MUST be enabled on the system Viewer is connecting to

import asyncio
import logging
import subprocess
import re
from datetime import datetime
from rich.live import Live
from rich.text import Text
import aiohttp
import sys
from rich.console import Console
import yaml

console = Console()

# Shared state
shared_state = {
    "balances": {"public": 0, "shielded": 0, "total": 0},
    "block_height": 0,
    "completion_time": "--:--",
    "last_action_taken": "",
    "peer_count": "0",
    "price": 0.0,
    "remain_time": 0,
    "stake_info": {
        "reclaimable_slashed_stake": 0.0,
        "rewards_amount": 0.0,
        "stake_amount": 0.0,
    },
    "usd_24h_change": 0.0,
    "rendered":"",
}


# Logger setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Utility functions

BLACK = "\033[0;30m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
BROWN = "\033[0;33m"
BLUE = "\033[0;34m"
PURPLE = "\033[0;35m"
CYAN = "\033[0;36m"
LIGHT_GRAY = "\033[0;37m"
DARK_GRAY = "\033[1;30m"
LIGHT_RED = "\033[1;31m"
LIGHT_GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
LIGHT_BLUE = "\033[1;34m"
LIGHT_PURPLE = "\033[1;35m"
LIGHT_CYAN = "\033[1;36m"
LIGHT_WHITE = "\033[1;37m"
DEFAULT = "\033[1;39m"


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
        

status_bar = load_config('STATUSBAR')
viewer = load_config('VIEWER')
remote_port = viewer.get('viewer_port', '5000')
remote_ip = viewer.get('remote_ip', '127.0.0.1')

def remove_ansi(text):
    # Regular expression to match ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def format_float(value, decimals=2):
    return f"{value:.{decimals}f}"

def format_hms(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

async def fetch_data(remote_ip, remote_port):
    url = f"http://{remote_ip}:{remote_port}/api/data"
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        shared_data = data.get("data", {})

                        shared_state["balances"] = {
                            "public": shared_data.get("balances_public", 0),
                            "shielded": shared_data.get("balances_shielded", 0),
                            "total": shared_data.get("balances_total", 0),
                        }
                        shared_state["block_height"] = shared_data.get("block_height", 0)
                        shared_state["completion_time"] = shared_data.get("completion_time", "--:--")
                        shared_state["last_action_taken"] = shared_data.get("last_action", "")
                        shared_state["peer_count"] = shared_data.get("peer_count", "0")
                        shared_state["price"] = shared_data.get("price", 0.0)
                        shared_state["remain_time"] = shared_data.get("remain_time", 0)
                        shared_state["stake_info"] = shared_data.get("stake_info", {})
                        shared_state["usd_24h_change"] = shared_data.get("usd_24h_change", 0.0)

                    else:
                        logging.error(f"Failed to fetch data: HTTP {response.status}")
            except Exception as e:
                logging.error(f"Error fetching data: {e}")

            await asyncio.sleep(1)
            
def display_wallet_distribution_bar(public_amount, shielded_amount, width=30):
    """
    Displays a single horizontal bar (ASCII blocks) with two colored segments:

    :param public_amount: float, the public balance
    :param shielded_amount: float, the shielded balance
    :param width: int, total number of blocks in the bar
    """
    total = public_amount + shielded_amount
    if total <= 0:
        #console.print("[bold yellow]No funds found (total=0).[/bold yellow]")
        return 0.0

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

    
    bar_str = (
        f"{YELLOW}{'▅' * pub_blocks}"
        f"{BLUE}{'▅' * shd_blocks}"
    )

    # Display the percentages
    pub_pct = public_ratio * 100
    shd_pct = shielded_ratio * 100
    
    p_pct = f"{pub_pct:.2f}%"
    s_pct = f"{shd_pct:.2f}%"
    return f"{YELLOW}{p_pct} {bar_str} {s_pct}"

async def realtime_display(enable_tmux=False):
    first_run = True

    with Live(console=console, refresh_per_second=4, auto_refresh=False) as live:
        while True:
            try:
                blk = shared_state["block_height"]
                st_info = shared_state["stake_info"]
                b = shared_state["balances"]
                last_act = shared_state["last_action_taken"]
                remain_seconds = shared_state["remain_time"]
                disp_time = format_hms(remain_seconds) if remain_seconds > 0 else "0s"
                donetime = shared_state["completion_time"]
                if donetime == '--:--':
                    await asyncio.sleep(2)
                    continue
                tot_bal = b["public"] + b["shielded"]
                price = shared_state["price"]

                charclr =str()
                
                if remain_seconds <= 3600: # red <1hr
                    charclr = RED
                elif remain_seconds <= 7200: # yellow <2hr
                    charclr = YELLOW
                elif remain_seconds <= 10800: # green <3hr
                    charclr = GREEN
                else:
                    charclr = LIGHT_WHITE
                    
                timer = f"Next:{charclr} {disp_time} "
                chg24=""
                if shared_state["usd_24h_change"] > 0:
                    chg24 = f"({GREEN}+{shared_state["usd_24h_change"]:.2f}%{DEFAULT} 24h)"
                elif shared_state["usd_24h_change"] < 0:
                    chg24= f"({RED}{shared_state["usd_24h_change"]:.2f}%{DEFAULT} 24h)"
                else:
                    chg24= f"({DEFAULT}{shared_state["usd_24h_change"]:.2f}% 24h)"
                usd = f"$USD: {format_float(shared_state["price"],3)} {chg24} | "
                
                peercolor = RED
                if int(shared_state['peer_count']) > 40:
                    peercolor = LIGHT_GREEN
                elif int(shared_state['peer_count']) > 16:
                    peercolor = YELLOW    
                
                currenttime = datetime.now().strftime('%H:%M:%S')
                allocation_bar = display_wallet_distribution_bar(b['public'],b['shielded'],8)
                # Real-time display content (no surrounding panel)
                realtime_content = (
                    f" {LIGHT_WHITE}======={DEFAULT} {currenttime} Block: {LIGHT_BLUE}#{blk} {DEFAULT}Peers: {peercolor}{shared_state['peer_count']}{DEFAULT} {LIGHT_WHITE}=======\n"
                    f"    {CYAN}Last Action{DEFAULT}   | {CYAN}{last_act}{DEFAULT}\n"
                    f"    {LIGHT_GREEN}Next Check    {DEFAULT}| {charclr}{disp_time}{DEFAULT} ({donetime}){DEFAULT}\n"
                    f"                  |\n"
                    f"    {LIGHT_WHITE}Price USD{DEFAULT}     | {LIGHT_WHITE}${format_float(price,3)}{DEFAULT} {chg24}\n"
                    f"                  |\n"
                    f"    {LIGHT_WHITE}Balance{DEFAULT}       | {LIGHT_WHITE}{allocation_bar}\n"
                    
                    f"      {LIGHT_WHITE}├─ {YELLOW}Public   {DEFAULT}| {YELLOW}{format_float(b['public'])} (${format_float(b['public'] * price, 2)}){DEFAULT}\n"
                    f"      {LIGHT_WHITE}└─ {BLUE}Shielded {DEFAULT}| {BLUE}{format_float(b['shielded'])} (${format_float(b['shielded'] * price, 2)}){DEFAULT}\n"
                    f"         {LIGHT_WHITE}   Total {DEFAULT}| {LIGHT_WHITE}{format_float(tot_bal)} DUSK (${format_float((tot_bal) * price, 2)}){DEFAULT}\n"
                    f"     \n"
                    f"    {LIGHT_WHITE}Staked{DEFAULT}        | {LIGHT_WHITE}{format_float(st_info['stake_amount'])} (${format_float(st_info['stake_amount'] * price, 2)}){DEFAULT}\n"
                    f"    {YELLOW}Rewards{DEFAULT}       | {YELLOW}{format_float(st_info['rewards_amount'])} (${format_float(st_info['rewards_amount'] * price, 2)}){DEFAULT}\n"
                    f"    {LIGHT_RED}Reclaimable{DEFAULT}   | {LIGHT_RED}{format_float(st_info['reclaimable_slashed_stake'])} (${format_float(st_info['reclaimable_slashed_stake'] * price, 2)}){DEFAULT}\n"
                    f" ===============================================\n"
                )
                if True:
                    shared_state["rendered"] = realtime_content
                    
                # Update the Live display
                live.update(Text(realtime_content), refresh=True)

                # Update TMUX status bar
                
                error_txt = str()
                last_txt = str()
                
                donetime = f"{DEFAULT}({shared_state["completion_time"]}) "

                peercnt = f"Peers: {shared_state["peer_count"]}"
                splitter= " | "
                

                if enable_tmux:
                    try:
                        curblk = f"\r> Blk: #{blk} | "
                        stk = f"Stk: {format_float(st_info['stake_amount'])} | "
                        rcl = f"Rcl: {format_float(st_info['reclaimable_slashed_stake'])} | "
                        rwd = f"Rwd: {format_float(st_info['rewards_amount'])} | "
                        bal = "Bal: "
                        p = f"P:{format_float(b['public'])}"
                        s = f"S:{format_float(b['shielded'])}"
                        
                        if not status_bar.get('show_current_block', True):
                            curblk = str()
                        if not status_bar.get('show_staked', True):
                            stk = str()
                        if not status_bar.get('show_public', True):
                            p = str()
                        if not status_bar.get('show_shielded', True):
                            s = str()
                        if not status_bar.get('show_total', True):
                            bal = str()
                        if not status_bar.get('show_rewards', True):
                            rwd = str()
                        if not status_bar.get('show_reclaimable', True):
                            rcl = str()
                        if not status_bar.get('show_price', True):
                            usd = str()
                        if not status_bar.get('show_timer', True):
                            timer = str()
                        if not status_bar.get('show_trigger_time', True):
                            donetime = str()
                        if not status_bar.get('show_peer_count', True):
                            peercnt = str()
                        if not status_bar.get('show_public', True) and not status_bar.get('show_shielded', True):
                            bal = str()
                            splitter = str()
                        if status_bar.get('show_public', True) and status_bar.get('show_shielded', True):
                            spacer = "  "

                        tmux_status = f"\r> {curblk}{stk}{rcl}{rwd}{bal}{p}{spacer}{s}{splitter}{usd}{last_txt}{timer}{donetime}{peercnt} {error_txt}"

                        subprocess.check_call(["tmux", "set-option", "-g", "status-left", remove_ansi(tmux_status)])
                    except subprocess.CalledProcessError:
                        #logging.error("Failed to update tmux status bar. Is tmux running?")
                        enable_tmux = False

                await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"Error in real-time display: {e}")
                await asyncio.sleep(5)


async def main():
    await asyncio.gather(fetch_data(remote_ip,remote_port), realtime_display())

if __name__ == "__main__":
    asyncio.run(main())
