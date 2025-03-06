import yaml
import sys
import os
import argparse
from dotenv import load_dotenv

def log_action(action="Action", details="No Details", type='info'):
    """Placeholder for log_action to avoid circular imports"""
    # This will be replaced by the actual log_action function
    print(f"{action}: {details}")

def load_config(section="GENERAL", file_path="config.yaml"):
    """Load configuration from a YAML file."""
    try:
        with open(file_path, "r") as file:
            config = yaml.safe_load(file)
            return config.get(section, {})
    except FileNotFoundError:
        log_action("Config File error", f"Configuration file {file_path} not found. Exiting.", "error")
        sys.exit(1)
    except yaml.YAMLError as e:
        log_action("Config File Error", f"Error parsing YAML file {file_path}: {e}", "error")
        sys.exit(1)

def initialize_config():
    """Initialize and return all configuration settings"""
    load_dotenv()
    
    # Load configuration sections
    general_config = load_config('GENERAL')
    notification_config = load_config('NOTIFICATIONS')
    status_bar_config = load_config('STATUSBAR')
    web_dashboard_config = load_config('WEB_DASHBOARD')
    logs_config = load_config('LOG_FILES')
    
    # Initialize parser for command line arguments
    parser = argparse.ArgumentParser(description="Process command line arguments")
    
    # Add boolean flag for `-d`
    parser.add_argument('-d', action='store_true', help="Run without GUI display, for background usage")
    
    # Parse arguments
    args = parser.parse_args() or {}
    
    # Extract common settings
    config = {
        # General settings
        'min_rewards': general_config.get('min_rewards', 1),
        'min_slashed': general_config.get('min_slashed', 1),
        'buffer_blocks': general_config.get('buffer_blocks', 60),
        'min_stake_amount': general_config.get('min_stake_amount', 1000),
        'min_peers': general_config.get('min_peers', 10),
        'auto_stake_rewards': general_config.get('auto_stake_rewards', False),
        'auto_reclaim_full_restakes': general_config.get('auto_reclaim_full_restakes', False),
        'pwd_var': general_config.get('pwd_var_name', 'MY_WALLET_VARIABLE'),
        'display_options': general_config.get('display_options', True),
        'use_sudo': 'sudo' if general_config.get('use_sudo', False) else '',
        
        # Web dashboard settings
        'enable_dashboard': web_dashboard_config.get('enable_dashboard', True),
        'dash_port': web_dashboard_config.get('dash_port', '5000'),
        'dash_ip': web_dashboard_config.get('dash_ip', '0.0.0.0'),
        'include_rendered': web_dashboard_config.get('include_rendered', False),
        
        # Logs settings
        'isDebug': logs_config.get('debug', False),
        'enable_logging': logs_config.get('enable_logging', False),
        'INFO_LOG_FILE': logs_config.get("action_log", "duskman_actions.log"),
        'ERROR_LOG_FILE': logs_config.get("error_log", "duskman_errors.log"),
        'DEBUG_LOG_FILE': logs_config.get("debug_log", "duskman_tmp_debug.log"),
        
        # Notification settings
        'monitor_wallet': notification_config.get('monitor_balance', False),
        
        # Command line arguments
        'display_gui': not args.d,
        
        # TMUX settings
        'enable_tmux': general_config.get('enable_tmux', False) or (len(sys.argv) > 1 and sys.argv[1].lower() == 'tmux'),
    }
    
    # Store the original config sections for reference
    config['general_config'] = general_config
    config['notification_config'] = notification_config
    config['status_bar_config'] = status_bar_config
    config['web_dashboard_config'] = web_dashboard_config
    config['logs_config'] = logs_config
    
    # Get wallet password from environment
    config['password'] = get_env_variable(
        general_config.get('pwd_var_name', 'WALLET_PASSWORD'), 
        dotenv_key="WALLET_PASSWORD"
    )
    
    return config

def get_env_variable(var_name='WALLET_PASSWORD', dotenv_key='WALLET_PASSWORD'):
    """
    Retrieve an environment variable or a fallback value from .env file.
    """
    value = os.getenv(var_name)
    if not value:
        value = os.getenv(dotenv_key)
        if not value:
            log_action("Wallet Password Variable Error", 
                        f"Neither environment variable '{var_name}' nor .env key '{dotenv_key}' found for wallet password.", 
                        "error")
            sys.exit(1)
            
    return value 