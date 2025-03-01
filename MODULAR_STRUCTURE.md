# DuskMan Modular Structure

This document explains the modular structure of the DuskMan application. The codebase has been reorganized into smaller, focused modules to improve maintainability, readability, and extensibility.

## Overview

The application is now organized into the following modules:

```
duskman.py                  # Main application entry point
utilities/
  ├── blockchain_client.py  # Blockchain interaction
  ├── blockchain_monitor.py # Blockchain monitoring
  ├── colors.py             # ANSI color constants
  ├── config.py             # Configuration loading
  ├── display_manager.py    # Console display and TMUX
  ├── logger.py             # Logging functionality
  ├── market_data.py        # Market data fetching
  ├── notifications.py      # Notification services
  ├── stake_manager.py      # Stake management
  ├── utils.py              # Utility functions
  ├── web_dashboard.py      # Web dashboard (Flask)
  └── web_server.py         # Web server (aiohttp)
```

## Module Descriptions

### Main Application (`duskman.py`)

The main entry point for the application. It initializes all the components, creates the shared state, and starts the main loops.

### Blockchain Client (`blockchain_client.py`)

Handles direct interactions with the Dusk blockchain, including:
- Executing blockchain commands
- Fetching block height and peer count
- Getting wallet balances
- Parsing stake information
- Performing stake operations (withdraw, unstake, stake)

### Blockchain Monitor (`blockchain_monitor.py`)

Monitors the blockchain for updates and maintains the shared state:
- Periodically checks block height and peer count
- Updates wallet balances and stake information
- Detects and reports issues (e.g., block height not changing, low peer count)
- Initializes balance information on startup

### Colors (`colors.py`)

Defines ANSI color constants for terminal output.

### Configuration (`config.py`)

Handles loading and processing configuration from YAML files and environment variables.

### Display Manager (`display_manager.py`)

Manages the real-time display of blockchain and staking information:
- Updates the console display
- Updates the TMUX status bar
- Formats data for display

### Logger (`logger.py`)

Handles logging functionality:
- Writes log messages to files
- Maintains a log history in memory
- Sends notifications for important events

### Market Data (`market_data.py`)

Fetches and processes cryptocurrency market data:
- Gets price and market data from CoinGecko
- Updates the shared state with market information

### Notifications (`notifications.py`)

Sends notifications through various services:
- Discord
- Pushbullet
- Telegram
- Pushover
- Webhook
- Slack

### Stake Manager (`stake_manager.py`)

Manages staking operations:
- Monitors stake information
- Decides when to claim rewards and stake
- Decides when to unstake and restake
- Performs staking operations
- Logs staking actions

### Utils (`utils.py`)

Provides utility functions used across the application:

- Formatting functions
- Environment variable handling
- Wallet distribution visualization
- Time formatting
- Logging utilities
- Reward calculations

### Web Dashboard (`web_dashboard.py`)

Provides a web-based dashboard using Flask:

- Displays real-time blockchain and staking information
- Provides an API for accessing data

### Web Server (`web_server.py`)

Provides a web server using aiohttp:

- Serves the dashboard
- Handles WebSocket connections for real-time updates

## Shared State

The application uses a shared state dictionary to maintain the current state of the system. This state is accessed and updated by all modules. The shared state includes:

- Block height
- Wallet balances
- Stake information
- Market data
- Log entries
- Display settings

## Interaction Flow

1. The main application initializes all components and creates the shared state.
2. The blockchain monitor periodically checks the blockchain and updates the shared state.
3. The stake manager uses the shared state to make staking decisions and perform operations.
4. The display manager uses the shared state to update the console and TMUX displays.
5. The web dashboard and web server provide access to the shared state through a web interface.

## Benefits of Modular Structure

- **Improved Maintainability**: Each module has a clear responsibility, making it easier to understand and maintain.
- **Better Testability**: Modules can be tested independently.
- **Enhanced Extensibility**: New features can be added by creating new modules or extending existing ones.
- **Clearer Code Organization**: The codebase is organized logically, making it easier to navigate.
- **Reduced Complexity**: Each module is smaller and more focused, reducing complexity.
