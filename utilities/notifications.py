import requests
import logging
import json

class NotificationService:
    def __init__(self, config, sharedinfo=None):
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
                - slack_webhook (str): Slack webhook URL.
        """
        self.discord_webhook = config.get('discord_webhook')
        self.pushbullet_token = config.get('pushbullet_token')
        self.telegram_bot_token = config.get('telegram_bot_token')
        self.telegram_chat_id = config.get('telegram_chat_id')
        self.pushover_user_key = config.get('pushover_user_key')
        self.pushover_app_token = config.get('pushover_app_token')
        self.webhook_url = config.get('webhook_url')
        self.slack_webhook = config.get('slack_webhook')

    def notify(self, message, shared_state=None):
        """
        Send notifications to all enabled services.
        """
        separator = "=" * 44
        if self.discord_webhook:
            self.send_discord_notification(message)
            
        if self.pushbullet_token:
            self.send_pushbullet_notification(message.replace(separator, ''))
            
        if self.telegram_bot_token and self.telegram_chat_id:
            self.send_telegram_notification(message.replace(separator, ''))
            
        if self.pushover_user_key and self.pushover_app_token:
            self.send_pushover_notification(message.replace(separator, ''))
        
        if self.webhook_url:
            self.send_shared_state_webhook(shared_state)
        
        if self.slack_webhook:
            self.send_slack_notification(message.replace(separator, ''))

    def send_shared_state_webhook(self, shared_state):
        """
        Sends the shared_state object as a JSON payload to the specified webhook URL.

        Args:
            shared_state (dict): The shared state object to send.

        Returns:
            bool: True if the webhook was sent successfully, False otherwise.
        """
        try:
            headers = {'Content-Type': 'application/json'}
            payload = json.dumps(shared_state, indent=2)
            
            logging.debug(f"Sending shared state to webhook URL: {self.webhook_url}")
            response = requests.post(self.webhook_url, headers=headers, data=payload)
            
            if response.status_code == 200:
                logging.debug("Webhook sent successfully.")
                return True
            else:
                logging.error(f"Failed to send webhook. Status Code: {response.status_code}, Response: {response.text}")
                return False
        except Exception as e:
            logging.error(f"Error sending webhook: {e}")
            return False


    def send_shared_state_webhook(self,shared_state):
        """
        Sends the shared_state object as a JSON payload to the specified webhook URL.

        Args:
            shared_state (dict): The shared state object to send.
            webhook_url (str): The destination webhook URL.

        Returns:
            bool: True if the webhook was sent successfully, False otherwise.
        """
        webhook_url = self.webhook_url
        try:
            headers = {'Content-Type': 'application/json'}
            payload = json.dumps(shared_state, indent=2)
            
            logging.debug(f"Sending shared state to webhook URL: {webhook_url}")
            response = requests.post(webhook_url, headers=headers, data=payload)
            
            if response.status_code == 200:
                logging.debug("Webhook sent successfully.")
                return True
            else:
                logging.error(f"Failed to send webhook. Status Code: {response.status_code}, Response: {response.text}")
                return False
        except Exception as e:
            logging.error(f"Error sending webhook: {e}")
            return False

        
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

    def send_slack_notification(self, message):
        """
        Send a notification to Slack using a webhook.
        """
        try:
            payload = {"text": message}
            response = requests.post(self.slack_webhook, json=payload)
            response.raise_for_status()
            logging.debug("Slack notification sent successfully.")
        except Exception as e:
            logging.error(f"Error sending Slack notification: {e}")
