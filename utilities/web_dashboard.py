"""
web_dashboard.py

- Only the logs column (on the right) scrolls; the rest is pinned.
- Light/Dark theme toggle in top-right, stored in localStorage.
- Label/value pairs left-aligned.
- Log headers: "Activity @ Block #XXXX - MM-DD HH:MM".
- Displays "No log entries yet." card if logs are empty.
- Shows a scrollbar on the logs column even before hover.
"""

import utilities.conf as c
import waitress
import logging
import threading
import asyncio
import datetime
from flask import Flask, jsonify, render_template_string

# ------------------------------------------------------------------------------
# DARK & LIGHT CSS
# ------------------------------------------------------------------------------
DARK_MODE_CSS = r"""
/* Make the entire page fill the viewport, no global scroll */
html, body {
  margin: 0; padding: 0; 
  width: 100%; height: 100%;
  overflow: hidden; /* no global scroll */
  font-family: "Fira Code", "Consolas", "Courier New", monospace;
  display: flex; 
  flex-direction: column;
  box-sizing: border-box;
  background: #1e1e1e;
  color: #e0e0e0;
}

/* Header & Footer pinned */
.header {
  background: linear-gradient(135deg, #191919 0%, #2a2a2a 100%);
  padding: 1.2em 1em;
  border-bottom: 1px solid #3d3d3d;
  text-align: center;
  flex: 0 0 auto; 
}
.header h1 {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 600;
  color: #fafafa;
}
.footer {
  background: linear-gradient(135deg, #191919 0%, #2a2a2a 100%);
  padding: 0.7em 1em;
  border-top: 1px solid #3d3d3d;
  text-align: center;
  flex: 0 0 auto;
  font-size: 0.85em;
}

/* Container fills leftover vertical space */
.container-wrapper {
  flex: 1 1 auto;
  width: 100%;
  display: flex;
  flex-direction: row;
  height: 100%; 
}

/* Left & right sidebars (5% each) */
.sidebar-left,
.sidebar-right {
  flex: 0 0 5%;
  background-color: #1e1e1e;
}

/* Main container (20% about, 35% left stats, 45% logs) */
.main-container {
  flex: 1 1 auto; 
  display: flex;
  flex-direction: row;
  height: 100%;
  overflow: hidden;
}

.about-panel {
  flex: 0 0 20%;
  padding: 1em;
  height: 100%;
  overflow-y: auto;
  background: #1e1e1e;
}
.left-panel {
  flex: 0 0 35%;
  padding: 1em;
  border-left: 1px solid #3d3d3d; 
  border-right: 1px solid #3d3d3d;
  height: 100%;
  overflow-y: auto;
}
/* Right panel: flex column, logs fill leftover, scroll if needed. */
.right-panel {
  flex: 0 0 45%;
  display: flex;
  flex-direction: column;
  padding: 1em;
  height:100%;
  overflow: hidden; 
}
#logs-card {
  flex: 1;
  overflow-y: scroll; /* always show scrollbar */
  /* Visible scrollbar styling: (WebKit-based & Firefox) */
  scrollbar-width: thin;         /* For Firefox */
  scrollbar-color: #666 #2a2a2a; /* thumb color, track color (FF) */
}
#logs-card::-webkit-scrollbar {
  width: 8px; /* always visible scrollbar for Chrome/Safari/Edge */
}
#logs-card::-webkit-scrollbar-track {
  background: #2a2a2a; 
}
#logs-card::-webkit-scrollbar-thumb {
  background-color: #666; 
  border-radius: 4px;
}
#logs-card::-webkit-scrollbar-thumb:hover {
  background-color: #888;
}

/* Cards, headings, etc. */
.card {
  background: #2a2a2a;
  border-radius: 8px;
  box-shadow: 0 0 10px rgba(0,0,0,0.2);
  margin-bottom: 1.2em;
  padding: 1em;
}
.card h4 {
  margin-top: 0; 
  margin-bottom: 0.5em; 
  color: #42a5f5; 
  font-size: 1.15rem;
}
.card h5 {
  margin-top: 0.6em; 
  margin-bottom: 0.2em; 
  color: #ffe082; 
  font-size: 1rem;
}
hr {
  border: none;
  border-top: 1px dashed #555;
  margin: 1em 0;
}
ul {
  list-style: none;
  margin: 0.5em 0 1em 0;
  padding: 0;
}
li {
  display: flex;
  flex-direction: row;
  align-items: baseline;
  margin-bottom: 0.3em;
}
.label-col {
  width: 11em; 
  text-align: left; 
  margin-right: 1em;
  font-weight: 600;
}
.value-col {
  flex: 1; 
  text-align: left;
}
li.total-balance {
  margin-top: 0.8em;
  font-weight: bold;
}
strong { color: #cddc39; }

.about-card {
  background: #2e2e2e;
  border-radius: 8px;
  box-shadow: 0 0 10px rgba(0,0,0,0.2);
  padding: 1em;
  margin-bottom: 1.2em;
  font-size: 0.95rem;
  line-height: 1.4;
}
.about-card h3 {
  margin-top: 0; 
  margin-bottom: 0.4em; 
  color: #ffcc80; 
  font-weight: 600;
}
.log-entry-card {
  background: #2f2f2f;
  border-radius: 8px;
  padding: 0.6em 0.8em;
  margin-bottom: 1em;
  box-shadow: 0 2px 5px rgba(0,0,0,0.3);
}
.log-entry-card h5 {
  margin-top: 0; 
  margin-bottom: 0.4em; 
  font-size: 1rem;
  color: #ffa726;
  font-weight: 600;
}
.log-entry-card ul {
  margin: 0.2em 0 0.2em 0; 
  padding: 0;
}
.log-entry-card ul li {
  display: flex;
  align-items: baseline;
  margin-bottom: 0.2em;
}
/* THEME TOGGLE BUTTON in top-right */
#theme-toggle {
  position: absolute;
  top: 10px;
  right: 10px;
  background: #444;
  color: #eee;
  border: 1px solid #666;
  padding: 0.4em 0.8em;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3em;
}
"""

LIGHT_MODE_CSS = r"""
/* ============== LIGHT THEME ============== */
html, body {
  margin: 0; padding: 0; 
  width:100%; height:100%;
  overflow: hidden; /* no global scroll */
  font-family: "Fira Code", "Consolas", "Courier New", monospace;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  background: #f7f7f7;
  color: #222;
}
.header {
  background: linear-gradient(135deg, #efefef 0%, #dcdcdc 100%);
  padding: 1.2em 1em;
  border-bottom: 1px solid #ccc;
  text-align: center;
  flex: 0 0 auto;
}
.header h1 {
  margin: 0; 
  font-size: 1.6rem; 
  font-weight: 600; 
  color: #111;
}
.footer {
  background: linear-gradient(135deg, #efefef 0%, #dcdcdc 100%);
  padding: 0.7em 1em;
  border-top: 1px solid #ccc;
  text-align: center;
  flex: 0 0 auto;
  font-size: 0.85em;
  color: #444;
}
.container-wrapper {
  flex: 1 1 auto;
  width:100%;
  display: flex;
  flex-direction: row;
  height:100%;
}
.sidebar-left, .sidebar-right {
  flex: 0 0 5%; 
  background-color: #f7f7f7;
}
.main-container {
  flex: 1 1 auto;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  height:100%;
}
.about-panel {
  flex: 0 0 20%;
  padding: 1em;
  overflow-y: auto; 
  background: #fafafa;
  height:100%;
}
.left-panel {
  flex: 0 0 35%;
  padding: 1em;
  border-left: 1px solid #ccc; 
  border-right: 1px solid #ccc;
  overflow-y: auto;
  background: #fafafa;
  height:100%;
}
.right-panel {
  flex: 0 0 45%;
  display: flex; 
  flex-direction: column;
  padding: 1em;
  overflow: hidden;
  height:100%;
}
#logs-card {
  flex:1; 
  overflow-y: scroll; 
  /* Always visible scrollbar styling */
  scrollbar-width: thin; 
  scrollbar-color: #999 #fff; /* for Firefox: thumb color, track color */
}
#logs-card::-webkit-scrollbar {
  width: 8px;
}
#logs-card::-webkit-scrollbar-track {
  background: #fff;
}
#logs-card::-webkit-scrollbar-thumb {
  background-color: #999;
  border-radius: 4px;
}
#logs-card::-webkit-scrollbar-thumb:hover {
  background-color: #777;
}

.card {
  background: #ffffff; 
  border-radius: 8px; 
  box-shadow: 0 0 6px rgba(0,0,0,0.1);
  margin-bottom: 1.2em; 
  padding: 1em;
}
.card h4 {
  margin-top: 0; 
  margin-bottom: 0.5em; 
  color: #3077c9;
  font-size: 1.15rem;
}
.card h5 {
  margin-top: 0.6em; 
  margin-bottom: 0.2em; 
  color: #e69b00; 
  font-size: 1rem;
}
hr {
  border: none;
  border-top: 1px dashed #aaa;
  margin: 1em 0;
}
ul {
  list-style: none;
  margin: 0.5em 0 1em 0; 
  padding: 0; 
  color: #333;
}
li {
  display: flex;
  flex-direction: row;
  align-items: baseline;
  margin-bottom: 0.3em;
}
.label-col {
  width: 11em; 
  text-align: left; 
  margin-right: 1em; 
  font-weight: 600;
}
.value-col {
  flex: 1; 
  text-align: left;
}
li.total-balance {
  margin-top: 0.8em;
  font-weight: bold;
}
strong { color: #576710; }

.about-card {
  background: #fefefe;
  border-radius: 8px;
  box-shadow: 0 0 6px rgba(0,0,0,0.1);
  padding: 1em;
  margin-bottom: 1.2em;
  font-size: 0.95rem;
  line-height: 1.4;
}
.about-card h3 {
  margin-top: 0; 
  margin-bottom: 0.4em; 
  color: #c78100; 
  font-weight: 600;
}
.log-entry-card {
  background: #fff; 
  border-radius: 8px; 
  padding: 0.6em 0.8em;
  margin-bottom: 1em; 
  box-shadow: 0 2px 5px rgba(0,0,0,0.1);
}
.log-entry-card h5 {
  margin-top: 0; 
  margin-bottom: 0.4em; 
  font-size: 1rem; 
  color: #f57c00; 
  font-weight: 600;
}
.log-entry-card ul {
  margin: 0.2em 0 0.2em 0; 
  padding: 0; 
  color: #333;
}
.log-entry-card ul li {
  display: flex; 
  align-items: baseline; 
  margin-bottom: 0.2em;
}
/* THEME TOGGLE BUTTON, same size & position in light mode */
#theme-toggle {
  position: absolute;
  top: 10px;
  right: 10px;
  background: #ccc;
  color: #333;
  border: 1px solid #999;
  padding: 0.4em 0.8em;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3em;
}
"""

# ------------------------------------------------------------------------------
# MAIN HTML
# ------------------------------------------------------------------------------
DASHBOARD_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>DuskMan: The Dusk Network Stake Manager</title>
  <style id="theme-style"></style>
</head>
<body>

<!-- THEME TOGGLE BUTTON with text/icon -->
<button id="theme-toggle"></button>

<!-- HEADER -->
<div class="header">
  <h1>DuskMan: The Dusk Network Stake Manager</h1>
</div>

<div class="container-wrapper">
  <div class="sidebar-left"></div>
  <div class="main-container">

    <!-- ABOUT (20%) -->
    <div class="about-panel">
      <div class="about-card">
        <h3>About DuskMan</h3>
        <p>DuskMan is a stake management dashboard for the <strong>Dusk Network</strong>.
           It monitors your node status, balances, and staking rewards in near real time.
           
           </p>

        <p>Author: <strong>Wolfrage</strong><br>
           Source:
           <a href="https://github.com/wolfrage76" target="_blank"
              style="color: #42a5f5; text-decoration: none;">
              GitHub
           </a>
        </p>

        <p>Official Dusk Network Site:
          <a href="https://dusk.network" target="_blank"
             style="color: #42a5f5; text-decoration: none;">
             https://dusk.network     
          </a>
        </p>
        <p>Dusk Discord:
          <a href="https://discord.gg/dusk-official" target="_blank"
             style="color: #42a5f5; text-decoration: none;">
             https://discord.gg/dusk-official     
          </a>
        </p>
        <p>Dusk Explorer:
          <a href="https://explorer.dusk.network/" target="_blank"
             style="color: #42a5f5; text-decoration: none;">
             https://explorer.dusk.network/
          </a>
        </p>
      </div>
    </div>

    <!-- Real-time Stats (35%) -->
    <div class="left-panel">
      <div class="card" id="stats-card">
        <h4>Loading real-time data...</h4>
      </div>
    </div>

    <!-- Logs (45%) with #logs-card filling & scrolling -->
    <div class="right-panel">
      <div class="card" id="logs-card">
        <h4>Loading logs...</h4>
      </div>
    </div>

  </div>
  <div class="sidebar-right"></div>
</div>

<!-- FOOTER -->
<div class="footer">
  <p>© {{year}} Wolfrage’s Dusk Dashboard. All rights reserved.
    <a href="https://github.com/wolfrage76" target="_blank" style="margin-left: 8px;">
      <img src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png" 
           alt="GitHub" 
           style="width:20px; height:20px; vertical-align:middle;" />
    </a>
  </p>
</div>

<script>
  const DARK_MODE_CSS = `{{ dark_css }}`;
  const LIGHT_MODE_CSS = `{{ light_css }}`;

  function applyTheme(isDark) {
    document.getElementById('theme-style').innerHTML = isDark ? DARK_MODE_CSS : LIGHT_MODE_CSS;
    localStorage.setItem('duskmanIsDark', isDark);
    updateThemeButton(isDark);
  }
  function updateThemeButton(isDark) {
    const btn = document.getElementById("theme-toggle");
    btn.innerHTML = isDark ? "☀️ Light Mode" : "🌙 Dark Mode";
  }
  function toggleTheme() {
    let isDark = (localStorage.getItem('duskmanIsDark') === 'true');
    applyTheme(!isDark);
  }

  (function initTheme() {
    let stored = localStorage.getItem('duskmanIsDark');
    if (stored === null) {
      stored = 'true'; // default dark
      localStorage.setItem('duskmanIsDark', stored);
    }
    applyTheme(stored === 'true');
  })();
  document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

  // Helper fns
  function truncateNumber(num, decimals) {
    if (!num || isNaN(num)) return num;
    let str = String(num);
    const [integer, fraction = ''] = str.split('.');
    if (fraction.length > decimals) {
      return integer + '.' + fraction.substring(0, decimals);
    }
    return str;
  }
  function roundTo(num, decimals) {
    if (!num || isNaN(num)) return num;
    const factor = Math.pow(10, decimals);
    return Math.round(num*factor)/factor;
  }
  function formatHMS(seconds){
    if(!seconds||isNaN(seconds))return seconds;
    const h=Math.floor(seconds/3600);
    const r=seconds%3600;
    const m=Math.floor(r/60);
    const s=r%60;
    const parts=[];
    if(h>0)parts.push(h+"h");
    if(m>0)parts.push(m+"m");
    parts.push(s+"s");
    return parts.join(" ");
  }
  function parseTruncated(strVal){
    const val=parseFloat(strVal);
    return isNaN(val)?0:val;
  }
  function formatUsd(duskVal,priceVal){
    const total=parseTruncated(duskVal)*parseTruncated(priceVal);
    return total.toFixed(2);
  }

  function parseLogEntry(rawText) {
    let lines=rawText.split(/\r?\n/).map(l=>l.trim());
    lines=lines.filter(l=>l&&!/^=+$/.test(l));
    if(!lines.length){
      return `<div class="log-entry-card"><h5>Empty Log</h5></div>`;
    }
    let activityLine=lines.shift();
    let activityTitle=activityLine
      .replace(/^====\s*Activity\s*@/i,"")
      .replace(/====$/,"")
      .trim();
    activityTitle=activityTitle.replace(/^\d{4}-/,"");

    let blockNumber=null;
    let filtered=[];
    lines.forEach(l=>{
      if(l.toLowerCase().startsWith("current block")){
        const parts=l.split(":",2);
        if(parts.length===2){
          blockNumber=parts[1].trim();
        }
      }else{
        filtered.push(l);
      }
    });
    filtered=filtered.filter(l=>l.includes(":"));

    let itemsHtml="";
    filtered.forEach(line=>{
      const [label,val]=line.split(":",2);
      if(val!==undefined){
        itemsHtml+=`
          <li>
            <span class="label-col">${label.trim()}:</span>
            <span class="value-col">${val.trim()}</span>
          </li>`;
      }
    });
    if(!itemsHtml) itemsHtml="<li>[No valid lines in this entry]</li>";

    let heading=blockNumber
      ? `Activity @ Block ${blockNumber} - ${activityTitle}`
      : `Activity @ ${activityTitle}`;

    return `
      <div class="log-entry-card">
        <h5>${heading}</h5>
        <ul>${itemsHtml}</ul>
      </div>
    `;
  }

  async function fetchDataAndUpdate(){
    try{
      const response=await fetch('/api/data');
      if(!response.ok){
        console.error("Error fetching data:",response.statusText);
        return;
      }
      const jsonData=await response.json();
      const data=jsonData.data;
      const logs=jsonData.log_entries;

      // Basic fields
      const blockHeight='#'+data.block_height;
      const peerCount=data.peer_count;
      const remainTimeFormatted=formatHMS(data.remain_time);
      const completionTime=data.completion_time;

      // Balances
      const balPublic=truncateNumber(data.balances_public,4);
      const balShielded=truncateNumber(data.balances_shielded,4);
      const balTotal=truncateNumber(data.balances_total,4);

      // Price & 24h
      const price=truncateNumber(data.price,3);
      const change24h=roundTo(data.usd_24h_change,2);

      // Staking
      const stakeAmount=truncateNumber(data.stake_info?.stake_amount||0,4);
      const rewardsAmount=truncateNumber(data.stake_info?.rewards_amount||0,4);
      const reclaimableSlashed=truncateNumber(data.stake_info?.reclaimable_slashed_stake||0,4);

      // Approx USD
      const balPublicUsd=formatUsd(balPublic,price);
      const balShieldedUsd=formatUsd(balShielded,price);
      const balTotalUsd=formatUsd(balTotal,price);

      let changeColor="white";
      if(change24h>0){changeColor="green";}
      else if(change24h<0){changeColor="red";}

      const priceLine=`
        <p style="text-align:center; color:white;">
          Price: $${price} (
            <span style="color:${changeColor};">${change24h}%</span> 24h
          )
        </p>
      `;

      // build alignment lists
      const lastActionLine=`
        <li>
          <span class="label-col">Last Action:</span>
          <span class="value-col">${data.last_action}</span>
        </li>`;
      const stakeList=`
        <li><span class="label-col">Stake Amount:</span><span class="value-col">${stakeAmount} DUSK</span></li>
        <li><span class="label-col">Rewards:</span><span class="value-col">${rewardsAmount} DUSK</span></li>
        <li><span class="label-col">Reclaimable:</span><span class="value-col">${reclaimableSlashed} DUSK</span></li>
      `;
      const balanceList=`
        <li><span class="label-col">Public:</span><span class="value-col">${balPublic} DUSK ($${balPublicUsd})</span></li>
        <li><span class="label-col">Shielded:</span><span class="value-col">${balShielded} DUSK ($${balShieldedUsd})</span></li>
        <li class="total-balance"><span class="label-col">Total:</span><span class="value-col">${balTotal} DUSK ($${balTotalUsd})</span></li>
      `;

      const statsHtml=`
        <h4>Real-Time Stats</h4>
        <p>
          <span class="label-col" style="width:auto;">Block:</span> 
          ${blockHeight} 
          &nbsp; 
          <span class="label-col" style="width:auto;">Peers:</span>
          ${peerCount}
        </p>
        <p>
          <span class="label-col" style="width:auto;">Next Check:</span>
          ${remainTimeFormatted} (${completionTime})
        </p>
        <hr>
        <h5>Balances</h5>
        <ul>${balanceList}</ul>
        ${priceLine}
        <hr>
        <h5>Staking Info</h5>
        <ul>${stakeList}</ul>
      `;
      document.getElementById('stats-card').innerHTML=statsHtml;

      let logsHtml=`<h4>Recent Logs</h4>`;
      if(logs.length===0){
        // show a single card "No log entries yet."
        logsHtml+=`
          <div class="log-entry-card">
            <h5>No log entries yet</h5>
          </div>
        `;
      } else {
        logs.forEach(rawEntry=>{
          logsHtml += parseLogEntry(rawEntry);
        });
      }
      document.getElementById('logs-card').innerHTML=logsHtml;
    }
    catch(e){
      console.error("Fetch error:",e);
    }
  }

  setInterval(fetchDataAndUpdate, 1000);
  fetchDataAndUpdate();
</script>
"""

def create_app(shared_state, log_entries):
    """
    Build the Flask app with routes:
      - / => Main HTML + JS
      - /api/data => returns JSON for real-time stats + logs
    """
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(
            DASHBOARD_HTML,
            dark_css=DARK_MODE_CSS,
            light_css=LIGHT_MODE_CSS,
            year=datetime.datetime.now().year,
        )

    @app.route("/api/data")
    def data_api():
        # Build data
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
            "stake_info": {
                "stake_amount": shared_state["stake_info"]["stake_amount"],
                "rewards_amount": shared_state["stake_info"]["rewards_amount"],
                "reclaimable_slashed_stake": shared_state["stake_info"]["reclaimable_slashed_stake"],
            },
            "last_action": shared_state["last_action_taken"],
        }
        tmpLogs = log_entries
        tmpLogs.reverse()
        datajson = jsonify({
            "data": data,
            # If no logs yet, logs[] is empty => we show "No log entries yet."
            "log_entries": tmpLogs
        })
        
        tmpLogs.reverse()
        return datajson

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
