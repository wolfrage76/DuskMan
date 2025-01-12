# DUSK Monitoring and Notification Script

This Python script automates the monitoring and management of **DUSK blockchain staking**, balances, and epochs. It efficiently handles claiming and restaking rewards, sends notifications via multiple services, and optionally updates the TMUX status bar with real-time information.

---

## Features

### 🚀 Automated Actions
- **Staking Management**:
  - Monitors staking rewards, reclaimable slashed stakes, and eligible stakes.
  - Automatically claims and stakes rewards when profitable.
  - Unstakes and restakes reclaimable slashed amounts when optimal.

- **Notification Support**:
  - Sends alerts via:
    - **Discord**
    - **Pushbullet**
    - **Telegram**
    - **Pushover**
  - Configurable per service using environment variables or script settings.

- **Efficient Execution**:
  - Calculates sleep times based on epochs to minimize unnecessary processing.
  - Prevents redundant or runaway actions.

- **TMUX Integration (Optional)**:
  - Updates the TMUX status bar with real-time staking and balance data.

---

## Installation

### Prerequisites
- **Python**: Version 3.7 or higher

---

### Steps

1. **Clone the Repository**:
```git clone https://github.com/<your-username>/<your-repo-name>.git
   cd <your-repo-name>```

2. Install Dependencies: Install the required Python libraries:
    ```pip install requests```

3. Set Wallet Password: Export your wallet password as an environment variable. For example:
    ```export MY_SUDO_PASSWORD="your_wallet_password"```

4. Configure Notifications: Open the script and edit the config dictionary to enable and set up the notification services you want to use:
    ```
    config = {
    "discord_webhook": "https://discord.com/api/webhooks/...",  # Replace with your webhook URL
    "pushbullet_token": "your_pushbullet_token",
    "telegram_bot_token": "your_telegram_bot_token",
    "telegram_chat_id": "your_telegram_chat_id",
    "pushover_user_key": "your_pushover_user_key",
    "pushover_app_token": "your_pushover_app_token"
    }


5. Run the Script: Start the monitoring script:
    ```python dusk_monitor.py```

    ## Notification Configuration

6. To enable notifications for specific services, provide the required credentials in the `config` dictionary. Notifications will only be sent for properly configured services. Setting value to `None` disables that notification.

| **Service**  | **Required Configuration Fields**                     |
|--------------|-------------------------------------------------------|
| Discord      | `discord_webhook`                                     |
| Pushbullet   | `pushbullet_token`                                    |
| Telegram     | `telegram_bot_token`, `telegram_chat_id`              |
| Pushover     | `pushover_user_key`, `pushover_app_token`             |

---

## Notes

- **Epoch Calculation**:  
  The script calculates sleep times based on the remaining blocks until the next epoch, ensuring efficient execution.

- **Minimum Rewards**:  
  The script only claims and stakes rewards if they exceed a configurable threshold (default: `1 DUSK`).

- **TMUX Integration**:  
  Displays real-time blockchain and balance data directly in the TMUX status bar if enabled.
