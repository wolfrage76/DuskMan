from datetime import datetime
from typing import Dict, Any, Optional, List, Callable

from utilities.utils import write_to_log

class Logger:
    """
    Handles logging functionality for the application.
    Logs messages to files and maintains a log history in memory.
    """
    
    def __init__(
        self, 
        shared_state: Dict[str, Any],
        config: Dict[str, Any],
        notifier=None
    ):
        """
        Initialize the logger.
        
        Args:
            shared_state: Shared state dictionary
            config: Configuration dictionary
            notifier: Notification service instance
        """
        self.shared_state = shared_state
        self.config = config
        self.notifier = notifier
        
        # Extract configuration values
        self.enable_logging = config.get('enable_logging', False)
        self.is_debug = config.get('isDebug', False)
        self.info_log_file = config.get('INFO_LOG_FILE', 'duskman_actions.log')
        self.error_log_file = config.get('ERROR_LOG_FILE', 'duskman_errors.log')
        self.debug_log_file = config.get('DEBUG_LOG_FILE', 'duskman_tmp_debug.log')
        self.password = config.get('password', '')
        
        # Log format
        self.log_format = "{timestamp} - {message}"
        
    def log_action(self, action: str = "Action", details: str = "No Details", type: str = 'info') -> None:
        """
        Write log messages to specific files based on type.
        
        Args:
            action: Action being logged
            details: Details of the action
            type: Type of log message (info, error, debug)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        formatted_message = self.log_format.format(timestamp=timestamp, message=f"{action}: {details}")
        
        # Mask password
        formatted_message = formatted_message.replace(self.password, '#####')
        
        # Manage log entries in shared state - deque handles maxlen automatically
        # log_entries = self.shared_state.get("log_entries", [])
        # if len(log_entries) > self.config.get('max_log_entries', 15): # Check against config value
        #     log_entries.pop(0) # This check is redundant with deque
        
        # Get the deque
        log_entries = self.shared_state.get("log_entries")

        # Write to the appropriate log file
        if type == 'debug' and self.enable_logging:
            if self.is_debug:
                write_to_log(self.debug_log_file, formatted_message)
                # Optionally add debug messages to deque if needed
                # if log_entries is not None: 
                #     log_entries.append(f"[DEBUG] {formatted_message}")
                return # Usually don't return debug messages elsewhere
        elif type == 'error' and self.enable_logging:
            if self.is_debug:
                write_to_log(self.debug_log_file, formatted_message)
            if log_entries is not None: log_entries.append(formatted_message)    
            write_to_log(self.error_log_file, formatted_message)
            # Send notification only for errors
            if self.notifier:
                self.notifier.notify(formatted_message, self.shared_state)
        elif self.enable_logging: # Handle 'info' and other types
            write_to_log(self.info_log_file, formatted_message)
            if log_entries is not None: log_entries.append(formatted_message)
            
        # No need to update shared state here as deque is modified directly
        # Update shared state (log_entries updated within type blocks now)
        # self.shared_state["log_entries"] = log_entries # No longer needed here
