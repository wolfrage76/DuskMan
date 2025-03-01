import os
import datetime
import logging
import threading
import asyncio

from flask import Flask, jsonify, render_template
import waitress

def create_app(shared_state, log_entries):
    """
    Creates the Flask app:
        - / => main HTML/JS page (dashboard)
        - /api/data => JSON with real-time stats + logs
    """
    # Set up Flask with appropriate template & static folders
    this_dir = os.path.dirname(__file__)
    template_dir = os.path.join(this_dir, 'templates')
    static_dir = os.path.join(this_dir, 'static')

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

    # Read CSS files once at startup and store in memory
    with open(os.path.join(static_dir, 'dark.css'), 'r', encoding='utf-8') as f:
        dark_css = f.read()
    with open(os.path.join(static_dir, 'light.css'), 'r', encoding='utf-8') as f:
        light_css = f.read()

    @app.route("/")
    def index():
        # Pass current year and the loaded CSS strings to the template
        return render_template(
            'dashboard.html',
            year=datetime.datetime.now().year,
            dark_css=dark_css,
            light_css=light_css
        )

    @app.route("/api/data")
    def data_api():
        # Build data from shared_state
        data = {
            "block_height": shared_state["block_height"],
            "peer_count": shared_state["peer_count"],
            "remain_time": shared_state["remain_time"],
            "completion_time": shared_state["completion_time"],
            "balances_public":   shared_state["balances"]["public"],
            "balances_shielded": shared_state["balances"]["shielded"],
            "balances_total": (shared_state["balances"]["public"] 
                + shared_state["balances"]["shielded"]),
            "price": shared_state["price"],
            "usd_24h_change": shared_state["usd_24h_change"],
            "stake_info": {
                "stake_amount": shared_state["stake_info"]["stake_amount"],
                "rewards_amount": shared_state["stake_info"]["rewards_amount"],
                "reclaimable_slashed_stake": shared_state["stake_info"]["reclaimable_slashed_stake"]
            },
            "last_action": shared_state["last_action_taken"],
            "rendered": shared_state["rendered"],
            
            # Add additional market data
            "price_change_7d": shared_state.get("price_change_percentage_7d_in_currency", 0),
            "price_change_30d": shared_state.get("price_change_percentage_30d_in_currency", 0),
            "price_change_1y": shared_state.get("price_change_percentage_1y_in_currency", 0),
            "volume": shared_state.get("volume", 0),
            "market_cap": shared_state.get("market_cap", 0),
            "market_cap_change_24h": shared_state.get("market_cap_change_percentage_24h", 0),
            "ath": shared_state.get("ath", 0),
            "ath_change": shared_state.get("ath_change_percentage", 0),
            "ath_date": shared_state.get("ath_date", ""),
            "atl": shared_state.get("atl", 0),
            "atl_date": shared_state.get("atl_date", ""),
            
            # Add reward percentage and per epoch data
            "rewards_per_epoch": shared_state.get("rewards_per_epoch", 0),
            "reward_percent": calculate_reward_percent(shared_state),
            
            # Add epoch information
            "current_epoch": int(shared_state["block_height"] / 2160),
            "active_block": shared_state.get("active_blk", 0),
        }

        # Reverse the logs so newest appear first
        reversed_logs = list(reversed(log_entries))

        return jsonify({"data": data, "log_entries": reversed_logs})

    return app


def _run_flask_in_thread(app, host, port):
    logging.debug(f"Starting DuskMan server on http://{host}:{port}")
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.ERROR)
    waitress.serve(app, host=host, port=port)


async def start_dashboard(shared_state, log_entries, host="0.0.0.0", port=5000):
    """
    Launch Waitress in a daemon thread so it doesn't block asyncio.
    """
    app = create_app(shared_state, log_entries)
    flask_thread = threading.Thread(
        target=_run_flask_in_thread, 
        args=(app, host, port),
        daemon=True
    )
    flask_thread.start()

    await asyncio.sleep(0.1)
    logging.debug("DuskMan dashboard started in background thread.")
    return flask_thread

def calculate_reward_percent(shared_state):
    """Calculate reward percentage relative to stake amount"""
    rewards = shared_state["stake_info"]["rewards_amount"]
    stake = shared_state["stake_info"]["stake_amount"]
    if stake > 0:
        return (rewards / stake) * 100
    return 0
