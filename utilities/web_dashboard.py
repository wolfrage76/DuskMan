import utilities.conf as c
import waitress
import logging
import threading
import asyncio
from flask import Flask, jsonify, render_template_string

# ------------------------------------------------------------------------------
# DARK MODE CSS
# ------------------------------------------------------------------------------
DARK_MODE_CSS = """
html, body {
  margin: 0;
  padding: 0;
  font-family: sans-serif;
  background-color: #2b2b2b; /* Dark background */
  color: #f0f0f0;           /* Light text */
}
.header {
  background: #191919;
  padding: 1em;
  text-align: center;
  font-size: 1.25em;
  border-bottom: 1px solid #444;
}
.footer {
  background: #191919;
  padding: 0.5em;
  text-align: center;
  font-size: 0.85em;
  border-top: 1px solid #444;
}
.container {
  display: flex;
  flex-direction: row;
  min-height: calc(100vh - 120px); /* minus header & footer */
}
.left-panel {
  flex: 2;
  padding: 1em;
  overflow-x: hidden; /* Hide horizontal scroll if needed */
  border-right: 1px solid #444;
}
.right-panel {
  flex: 1;
  padding: 1em;
  max-height: calc(100vh - 120px);
  overflow-y: auto; /* scrollable logs on the right */
}
.entry {
  margin-bottom: 1em;
  padding-bottom: 0.5em;
  border-bottom: 1px dashed #555;
}
"""

# ------------------------------------------------------------------------------
# HTML TEMPLATE WITH JS
# ------------------------------------------------------------------------------
DASHBOARD_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Dusk Staking Dashboard</title>
  <style>
    {{ dark_css }}
  </style>
</head>
<body>

<div class="header">
  <h3>Dusk Stake Management & Monitoring Dashboard</h3>
</div>

<div class="container">
  <!-- LEFT PANEL: Real-time stats -->
  <div class="left-panel" id="left-panel">
    <!-- This content will be updated dynamically by JS -->
    <h4>Loading real-time data...</h4>
  </div>

  <!-- RIGHT PANEL: Log entries -->
  <div class="right-panel" id="right-panel">
    <h4>Loading logs...</h4>
  </div>
</div>

<div class="footer">
  <p>© 2023 Wolfrage’s Dusk Dashboard</p>
</div>

<script>
  // Poll the /api/data endpoint every second to get fresh data/logs
  const updateIntervalMs = 1000;

  async function fetchDataAndUpdate() {
    try {
      const response = await fetch('/api/data');
      if (!response.ok) {
        console.error('Error fetching data:', response.statusText);
        return;
      }
      const jsonData = await response.json();
      const data = jsonData.data;
      const logs = jsonData.log_entries;

      // Update Left Panel (real-time stats)
      let leftPanelHTML = `
        <h4>Real-Time Stats</h4>
        <p><strong>Block:</strong> ${data.block_height}</p>
        <p><strong>Peers:</strong> ${data.peer_count}</p>
        <p><strong>Next Check:</strong> ${data.remain_time}s (${data.completion_time})</p>
        <hr>
        <h5>Balances</h5>
        <ul>
          <li>Public: ${data.balances_public} DUSK</li>
          <li>Shielded: ${data.balances_shielded} DUSK</li>
          <li>Total: ${data.balances_total} DUSK</li>
        </ul>
        <p><em>Price:</em> $${data.price} 
           (<em>24h change:</em> ${data.usd_24h_change}%)</p>
        <hr>
        <h5>Staking Info</h5>
        <ul>
          <li>Stake Amount: ${data.stake_amount} DUSK</li>
          <li>Rewards: ${data.rewards_amount} DUSK</li>
          <li>Reclaimable Slashed: ${data.reclaimable_slashed} DUSK</li>
        </ul>
        <p><strong>Last Action:</strong> ${data.last_action}</p>
      `;
      document.getElementById('left-panel').innerHTML = leftPanelHTML;

      // Update Right Panel (logs)
      let rightPanelHTML = `<h4>Recent Logs</h4>`;
      logs.forEach(entry => {
        rightPanelHTML += `<div class="entry">${entry}</div>`;
      });
      document.getElementById('right-panel').innerHTML = rightPanelHTML;

    } catch (error) {
      console.error('Fetch error:', error);
    }
  }

  // Repeatedly call fetchDataAndUpdate()
  setInterval(fetchDataAndUpdate, updateIntervalMs);

  // Fetch immediately on load
  fetchDataAndUpdate();
</script>

</body>
</html>
"""

def create_app(shared_state, log_entries):
    """
    Construct a Flask app and define routes:
      1) '/' => The main HTML page (with JavaScript)
      2) '/api/data' => JSON endpoint for dynamic data and logs
    """
    app = Flask(__name__)

    @app.route("/")
    def index():
        # Serve the main HTML with embedded JS
        return render_template_string(
            DASHBOARD_HTML,
            dark_css=DARK_MODE_CSS
        )

    @app.route("/api/data")
    def data_api():
        """
        Return JSON with real-time stake data plus log_entries.
        The front-end polls this endpoint and updates the dashboard.
        """
        data = {
            "block_height": shared_state["block_height"],
            "peer_count":   shared_state["peer_count"],
            "remain_time":  shared_state["remain_time"],
            "completion_time": shared_state["completion_time"],
            "balances_public": shared_state["balances"]["public"],
            "balances_shielded": shared_state["balances"]["shielded"],
            "balances_total": shared_state["balances"]["public"] + shared_state["balances"]["shielded"],
            "price": shared_state["price"],
            "usd_24h_change": shared_state["usd_24h_change"],
            "stake_amount": shared_state["stake_info"]["stake_amount"],
            "rewards_amount": shared_state["stake_info"]["rewards_amount"],
            "reclaimable_slashed": shared_state["stake_info"]["reclaimable_slashed_stake"],
            "last_action": shared_state["last_action_taken"],
        }

        return jsonify({
            "data": data,
            "log_entries": log_entries
        })

    return app


def _run_flask_in_thread(app, host, port):
    """
    Helper function that actually calls app.run(...). 
    This is invoked in a separate thread.
    """
    logging.debug(f"Starting Flask server on http://{host}:{port}")

    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.ERROR)
    
    waitress.serve(app, host=host, port=port)


async def start_dashboard(shared_state, log_entries, host="0.0.0.0", port=5000):

    # Construct the Flask app
    app = create_app(shared_state, c.log_entries)

    # Create and start the Flask server in a daemon thread
    flask_thread = threading.Thread(
        target=_run_flask_in_thread, 
        args=(app, host, port),
        daemon=True
    )
    flask_thread.start()

    await asyncio.sleep(0.1)
    logging.debug("Flask dashboard started in background thread (werkzeug logs set to ERROR).")

    return flask_thread
