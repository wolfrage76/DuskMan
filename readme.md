# DuskMan: The Dusk Network stake manager

![image](https://github.com/user-attachments/assets/b56a80ec-122d-440a-a8d8-0c1fcaeee3bc)

![image](https://github.com/user-attachments/assets/a780feed-e0fe-46f2-9713-44bcbed0eb5c)

DuskMan automates the monitoring, and management, of **DUSK Network** staking, balances, compounding, and monitoring system health. It efficiently handles claiming and restaking rewards, notifications via multiple services, and optionally updates the TMUX status bar with real-time information.

**NOTE:** The Auto Staking of rewards and/or Auto Restakes for reclaiming slashes CAN be disabled via the config.

---

**Dusk wallet for Tips:**

`eox326D2m1ohpBUFVgiF885yV7aN4sg4caA6UkAg7UUhB6JWystDE7t2bdvstBHKTGYrF1oEhYZEd4Bqh4Uhoer`

## 🚀 Features

- **Staking Management**:

  - Monitors staking rewards, reclaimable slashed stakes, and eligible stakes.
  - Automatically claims and stakes rewards when profitable.
  - Unstakes and restakes reclaimable slashed amounts when optimal.

- **Web Dashboard**:

  - View analytics through your favorite browser. Defaults to `http://localhost:5000`
  - Enables API access to pull data via deafult of `http://localhost:5000/api/data`

- **Notification Support**:

  - Sends alerts via:
    - **Discord**, **Pushbullet**, **Telegram**, **Pushover**, **Webhook**

- **Efficient Execution**:

  - Calculates sleep times based on epochs to minimize unnecessary processing.
  - Prevents redundant or runaway actions.

- **TMUX Integration**:
  - Can update the TMUX status bar with real-time staking and balance data.

---

## Installation

### Prerequisites

- **Python**: Version 3.7 or higher

---

### Steps (For Linux but Windows is similar)

1.  **Clone the Repository**:

    ```bash
    git clone https://github.com/wolfrage76/DuskMan.git
    cd DuskMan
    ```

2.  **Install Dependencies**: Install the required Python libraries:

    ```bash
    pip install -r requirements.txt
    ```

3.  **Set Wallet Password**:
    In the same directory as the script:

    ```bash
    touch .env
    chmod 600 .env
    ```

This will allow only the file owner to view the file.

4. **Edit the file with your editor of choice**:
   For example using nano:

   ```bash
   nano .env
   ```

5. **Add the following line**: Replace WALLETPASSWORD with your password:

   `WALLET_PASSWORD=WALLETPASSWORD`

6. **Configure Settings**: Rename config.yaml.example to config.yaml

   ```bash
   mv config.yaml.example config.yaml
   ```

7. **Edit config.yaml**: Using nano as an example, edit then save your changes:

   ```bash
   nano config.yaml
   ```

8. **Run the Script in Foreground**:

   ```bash
   python duskman.py
   ```

9. **Or Run script in the background (-d disables the display)**:

   ```bash
   screen -dmS dusk_manager python duskman.py -d
   ```

10. **Or run as a service**:
    Instructions coming later but `python duskman.py -d` will run with no interface

---

## Notification Configuration

To enable notifications for specific services, provide the required credentials in the `config` dictionary. Notifications will only be sent for properly configured services. Setting a value to `None` disables that notification.

| **Service** | **Required Configuration Fields**         |
| ----------- | ----------------------------------------- |
| Discord     | `discord_webhook`                         |
| Pushbullet  | `pushbullet_token`                        |
| Telegram    | `telegram_bot_token`, `telegram_chat_id`  |
| Pushover    | `pushover_user_key`, `pushover_app_token` |
| Webhook     | `webhook_url`                             |
| Slack       | `slack_webhook`                           |

---

## Notes

- **Epoch Calculation**:  
  The script calculates sleep times based on the remaining blocks until the next epoch, ensuring efficient execution.

- **Minimum Rewards**:  
  The script only claims and stakes rewards if they exceed a configurable threshold (default: `1 DUSK`).

- **TMUX Integration**:  
  Displays real-time blockchain and balance data directly in the TMUX status bar if enabled.

- **VIEWER ONLY SCRIPT**
  Allows you to run the viewer from a separate machine than the main script is running on for a display.
