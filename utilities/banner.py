import asyncio
import aiohttp
from typing import Dict, Any, Callable, Optional

class BannerManager:
    """
    Manages fetching and updating a banner message from an external URL.
    """
    
    def __init__(self, log_action_func: Callable = None, session: Optional[aiohttp.ClientSession] = None):
        """
        Initialize the BannerManager.
        
        Args:
            log_action_func: Function to call for logging.
            session: Optional aiohttp.ClientSession for making HTTP requests.
        """
        self.log_action = log_action_func or (lambda *args, **kwargs: None)
        self.banner_url = "http://dusk.ifhya.com:8080/info"
        self.shared_info_key = "banner_message"
        # Use a passed-in session if available, otherwise create one per call (less efficient but ok for infrequent calls)
        self._session = session 

    async def fetch_banner_info(self, shared_state: Dict[str, Any]) -> None:
        """
        Fetch banner information from the configured URL and update shared_state.
        If fetching or parsing fails, the banner message in shared_state will be set to an empty string.
        """
        banner_text = ""
        try:
            session = self._session if self._session else aiohttp.ClientSession()
            async with session.get(self.banner_url, timeout=10) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        banner_text = data.get("info", "")
                        if banner_text:
                            # Clean up the banner text
                            # Remove surrounding quotes if present
                            if banner_text.startswith('"') and banner_text.endswith('"'):
                                banner_text = banner_text[1:-1]
                            
                            # Normalize line endings (convert \r\n to \n, remove standalone \r)
                            banner_text = banner_text.replace('\r\n', '\n').replace('\r', '')
                            
                            self.log_action("BannerManager", f"Successfully fetched banner: '{banner_text}'", "debug")
                        else:
                            self.log_action("BannerManager", "Fetched banner data, but 'info' field is missing or empty.", "debug")
                    except aiohttp.ContentTypeError:
                        # Handle cases where the response is not JSON
                        raw_text = await response.text()
                        self.log_action("BannerManager", f"Failed to parse banner JSON. Status: {response.status}. Response: {raw_text[:200]}...", "warning")
                    except Exception as e:
                        self.log_action("BannerManager", f"Error parsing banner JSON: {str(e)}", "error")
                else:
                    self.log_action("BannerManager", f"Failed to fetch banner info. HTTP Status: {response.status}", "warning")
        except aiohttp.ClientConnectorError as e:
            self.log_action("BannerManager", f"Connection error fetching banner: {str(e)}", "error")
        except asyncio.TimeoutError:
            self.log_action("BannerManager", f"Timeout fetching banner from {self.banner_url}", "error")
        except Exception as e:
            self.log_action("BannerManager", f"Unexpected error fetching banner: {str(e)}", "error")
        finally:
            shared_state[self.shared_info_key] = banner_text
            if not self._session and 'session' in locals() and not session.closed: # if session was created locally
                await session.close() 