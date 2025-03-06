import asyncio
from aiohttp import web
import aiohttp


# Add these imports for WebSockets
from aiohttp import WSCloseCode
import weakref

# Store active WebSocket connections
active_ws_connections = weakref.WeakSet()

# Function to broadcast updates to all connected clients
async def broadcast_updates(shared_state, log_entries):
    if not active_ws_connections:
        return
    
    # Prepare the data to send
    data = await get_dashboard_data()
    
    # Send to all connected clients
    for ws in active_ws_connections:
        try:
            await ws.send_json(data)
        except Exception as e:
            print(f"Error sending to WebSocket: {e}")

# WebSocket handler
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    # Add this connection to our set of active connections
    active_ws_connections.add(ws)
    
    try:
        # Send initial data
        shared_state = request.app['shared_state']
        log_entries = request.app['log_entries']
        data = await get_dashboard_data()
        await ws.send_json(data)
        
        # Keep the connection open and handle messages
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                if msg.data == 'close':
                    await ws.close()
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f'WebSocket connection closed with exception {ws.exception()}')
    finally:
        # Remove from active connections when done
        active_ws_connections.discard(ws)
    
    return ws

# Start a background task to send updates every 5 seconds
async def start_update_broadcaster(app):
    while True:
        await broadcast_updates(app['shared_state'], app['log_entries'])
        await asyncio.sleep(5)  # Send updates every 5 seconds

# Add the WebSocket route and start the broadcaster
async def start_dashboard(shared_state, log_entries, host='0.0.0.0', port=8080):
    app = web.Application()
    
    # Store shared state and log entries in the app
    app['shared_state'] = shared_state
    app['log_entries'] = log_entries
    
    app.router.add_get('/ws', websocket_handler)  # Add WebSocket endpoint
    
    # Start the update broadcaster
    asyncio.create_task(start_update_broadcaster(app))
    
    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Dashboard running at http://{host}:{port}")

async def get_dashboard_data():
    """
    Get the current dashboard data from the shared state.
    
    Returns:
        dict: The current dashboard data
    """
    # Import shared_state directly from the main module to ensure we get the latest data
    from duskman import shared_state
    
    # Create a deep copy to avoid modifying the original data
    data = {
        "block_height": shared_state.get("block_height", 0),
        "current_epoch": shared_state.get("block_height", 0) // 2160,
        "peer_count": shared_state.get("peer_count", 0),
        "last_action": shared_state.get("last_action_taken", "Starting Up"),
        "remain_time": shared_state.get("remain_time", 0),  # Keep for backward compatibility
        "completion_time": shared_state.get("completion_time", "--:--"),  # Keep for backward compatibility
        "completion_timestamp": shared_state.get("completion_timestamp", 0),  # New field with millisecond timestamp
        "balances_public": shared_state.get("balances", {}).get("public", 0),
        "balances_shielded": shared_state.get("balances", {}).get("shielded", 0),
        "balances_total": shared_state.get("balances", {}).get("public", 0) + shared_state.get("balances", {}).get("shielded", 0),
        "stake_info": shared_state.get("stake_info", {"stake_amount": 0, "reclaimable_slashed_stake": 0, "rewards_amount": 0}),
        "price": shared_state.get("price", 0),
        "active_block": shared_state.get("stake_active_blk", 0),
        "rewards_per_epoch": shared_state.get("rewards_per_epoch", 0),
        # Add market data fields
        "usd_24h_change": shared_state.get("usd_24h_change", 0),
        "price_change_7d": shared_state.get("price_change_7d", 0),
        "price_change_30d": shared_state.get("price_change_30d", 0),
        "price_change_1y": shared_state.get("price_change_1y", 0),
        "volume": shared_state.get("volume", 0),
        "market_cap": shared_state.get("market_cap", 0),
        "market_cap_change_24h": shared_state.get("market_cap_change_24h", 0),
        "ath": shared_state.get("ath", 0),
        "ath_change": shared_state.get("ath_change", 0),
        "atl": shared_state.get("atl", 0),
    }
    
    # Calculate reward percentage
    if data["stake_info"]["stake_amount"] > 0:
        data["reward_percent"] = (data["stake_info"]["rewards_amount"] / data["stake_info"]["stake_amount"]) * 100
    else:
        data["reward_percent"] = 0
    
    return {
        "data": data,
        "log_entries": shared_state.get("log_entries", [])
    } 