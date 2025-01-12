import requests
import logging

class NotificationService:
    def __init__(self, config):
        """
        Initialize the notification service with configuration.

        Args:
            config (dict): Configuration dictionary with optional keys:
                - discord_webhook (str): Discord webhook URL.
                - pushbullet_token (str): Pushbullet API token.
                - telegram_bot_token (str): Telegram bot token.
                - telegram_chat_id (str): Telegram chat ID.
                - pushover_user_key (str): Pushover user key.
                - pushover_app_token (str): Pushover app token.
        """
        self.discord_webhook = config.get('discord_webhook')
        self.pushbullet_token = config.get('pushbullet_token')
        self.telegram_bot_token = config.get('telegram_bot_token')
        self.telegram_chat_id = config.get('telegram_chat_id')
        self.pushover_user_key = config.get('pushover_user_key')
        self.pushover_app_token = config.get('pushover_app_token')

    def notify(self, message):
        """
        Send notifications to all enabled services.
        """
        if self.discord_webhook:
            self.send_discord_notification(message)
            
        if self.pushbullet_token:
            self.send_pushbullet_notification(message)
            
        if self.telegram_bot_token and self.telegram_chat_id:
            self.send_telegram_notification(message)
            
        if self.pushover_user_key and self.pushover_app_token:
            self.send_pushover_notification(message)

    def send_discord_notification(self, message):
        """
        Send a notification to Discord using a webhook.
        """
        try:
            payload = {"content": message}
            response = requests.post(self.discord_webhook, json=payload)
            response.raise_for_status()
            logging.debug("Discord notification sent successfully.")
        except Exception as e:
            logging.error(f"Error sending Discord notification: {e}")

    def send_pushbullet_notification(self, message):
        """
        Send a notification to Pushbullet.
        """
        try:
            headers = {
                'Access-Token': self.pushbullet_token,
                'Content-Type': 'application/json'
            }
            message = message.replace('Dusk (', 'Dusk\n\t(')
            payload = {"type": "note", "title": "Dusk Alert", "body": message}
            response = requests.post("https://api.pushbullet.com/v2/pushes", json=payload, headers=headers)
            response.raise_for_status()
            logging.debug("Pushbullet notification sent successfully.")
        except Exception as e:
            logging.error(f"Error sending Pushbullet notification: {e}")

    def send_telegram_notification(self, message):
        """
        Send a notification to Telegram.
        """
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {"chat_id": self.telegram_chat_id, "text": message}
            response = requests.post(url, json=payload)
            response.raise_for_status()
            logging.debug("Telegram notification sent successfully.")
        except Exception as e:
            logging.error(f"Error sending Telegram notification: {e}")

    def send_pushover_notification(self, message):
        """
        Send a notification to Pushover.
        """
        try:
            payload = {
                "token": self.pushover_app_token,
                "user": self.pushover_user_key,
                "message": message
            }
            response = requests.post("https://api.pushover.net/1/messages.json", data=payload)
            response.raise_for_status()
            logging.debug("Pushover notification sent successfully.")
        except Exception as e:
            logging.error(f"Error sending Pushover notification: {e}")
