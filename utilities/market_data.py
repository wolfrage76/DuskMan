import aiohttp
from typing import Dict, Any, Optional

class MarketDataClient:
    """
    Client for fetching cryptocurrency market data from external APIs.
    Currently supports CoinGecko for DUSK Network data.
    """
    
    def __init__(self, log_action_func=None):
        """
        Initialize the market data client.
        
        Args:
            log_action_func: Function to call for logging
        """
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        
    async def fetch_dusk_data(self, shared_state: Dict[str, Any]) -> bool:
        """
        Fetch DUSK token data from CoinGecko's /coins/markets endpoint and update shared_state.
        
        Args:
            shared_state: Shared state dictionary to update
            
        Returns:
            True if successful, False otherwise
        """
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",  # Convert price to USD
            "ids": "dusk-network",  # CoinGecko's ID for DUSK
            "order": "market_cap_desc",  # Sort by market cap
            "per_page": 1,
            "page": 1,
            "sparkline": "false",  # Do not include sparkline data
            "price_change_percentage": "1h,24h,7d,14d,30d,200d,1y",  # Include price change percentages
            "locale": "en",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        dusk_data = {}
                        if data:
                            dusk_data = data[0]  # Extract the first result for "dusk-network"
                            
                        # Update shared_state directly
                        self._update_shared_state(shared_state, dusk_data)
                        return True
                    else:
                        self.log_action("Failed to fetch DUSK data", f"HTTP Status: {response.status}", 'debug')
                        return False
        except Exception as e:
            self.log_action("Error while fetching DUSK data", str(e), 'debug')
            return False
            
    def _update_shared_state(self, shared_state: Dict[str, Any], dusk_data: Dict[str, Any]) -> None:
        """
        Update shared state with market data.
        
        Args:
            shared_state: Shared state dictionary to update
            dusk_data: Market data from CoinGecko
        """
        # Basic price and market data
        shared_state["price"] = dusk_data.get("current_price", 0.0)
        shared_state["market_cap"] = dusk_data.get("market_cap", 0.0)
        shared_state["volume"] = dusk_data.get("total_volume", 0.0)
        shared_state["usd_24h_change"] = dusk_data.get("price_change_percentage_24h", 0.0)
        
        # Market position data
        shared_state["market_cap_rank"] = dusk_data.get("market_cap_rank", None)
        shared_state["circulating_supply"] = dusk_data.get("circulating_supply", None)
        shared_state["total_supply"] = dusk_data.get("total_supply", None)
        
        # Historical price data
        shared_state["ath"] = dusk_data.get("ath", 0.0)
        shared_state["ath_change_percentage"] = dusk_data.get("ath_change_percentage", 0.0)
        shared_state["ath_date"] = dusk_data.get("ath_date", "N/A")
        shared_state["atl"] = dusk_data.get("atl", 0.0)
        shared_state["atl_date"] = dusk_data.get("atl_date", 0.0)
        
        # 24-hour data
        shared_state["high_24h"] = dusk_data.get("high_24h", 0.0)
        shared_state["low_24h"] = dusk_data.get("low_24h", 0.0)
        shared_state["price_change_24h"] = dusk_data.get("price_change_24h", 0.0)
        shared_state["market_cap_change_24h"] = dusk_data.get("market_cap_change_24h", 0.0)
        shared_state["market_cap_change_percentage_24h"] = dusk_data.get("market_cap_change_percentage_24h", 0.0)
        
        # Supply data
        shared_state["max_supply"] = dusk_data.get("max_supply", 0.0)
        shared_state["fully_diluted_valuation"] = dusk_data.get("fully_diluted_valuation", 0.0)
        
        # Price change percentages for different time periods
        shared_state["price_change_percentage_1h_in_currency"] = dusk_data.get("price_change_percentage_1h_in_currency", 0.0)
        shared_state["price_change_percentage_24h_in_currency"] = dusk_data.get("price_change_percentage_24h_in_currency", 0.0)
        shared_state["price_change_percentage_7d_in_currency"] = dusk_data.get("price_change_percentage_7d_in_currency", 0.0)
        shared_state["price_change_percentage_14d_in_currency"] = dusk_data.get("price_change_percentage_14d_in_currency", 0.0)
        shared_state["price_change_percentage_30d_in_currency"] = dusk_data.get("price_change_percentage_30d_in_currency", 0.0)
        shared_state["price_change_percentage_200d_in_currency"] = dusk_data.get("price_change_percentage_200d_in_currency", 0.0)
        shared_state["price_change_percentage_1y_in_currency"] = dusk_data.get("price_change_percentage_1y_in_currency", 0.0)
        
        # Last updated timestamp
        shared_state["last_updated"] = dusk_data.get("last_updated", "N/A")
