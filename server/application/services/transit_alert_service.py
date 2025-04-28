import logging
import requests
from datetime import datetime

# This class handles the transit alert system, including sending notifications,
# checking vehicle delays, managing user subscriptions, and interacting with AWS services.
# It uses AWS SNS for notifications and DynamoDB for storing user subscriptions.
# The class is initialized with the necessary AWS clients, configuration settings,
# and a data service for interacting with DynamoDB.
# It includes methods for sending notifications, checking vehicle delays,
# getting predictions, managing subscriptions, and handling user email updates.
# The class also includes error handling and logging for each operation.
# The methods are designed to be used in a serverless environment, such as AWS Lambda,
# and are structured to handle incoming requests and responses in a consistent manner.

class TransitAlertSystem:
    def __init__(self, sns_client, sns_topic_arn, delay_threshold_minutes, vehicle_delay_threshold, data_service, max_subscriptions=10):
        self.sns_client = sns_client
        self.sns_topic_arn = sns_topic_arn
        self.delay_threshold_minutes = delay_threshold_minutes
        self.vehicle_delay_threshold = vehicle_delay_threshold
        self.data_service = data_service
        self.max_subscriptions = max_subscriptions

        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

    def send_notification(self, message, subject="Transit Alert"):
        try:
            self.logger.info(f"Sending SNS notification: {subject} - {message}")
            return self.sns_client.publish(
                TopicArn=self.sns_topic_arn,
                Message=message,
                Subject=subject
            )
        except Exception as e:
            self.logger.error(f"Error sending SNS notification: {e}")

    def check_vehicle_delay(self, route):
        try:
            url = f"https://api.transitagency.com/vehicles?route={route}"
            response = requests.get(url)
            response.raise_for_status()

            bus_data = response.json().get("data", [])
            delayed_buses = [
                bus["attributes"].get("delay", 0)
                for bus in bus_data
                if bus["attributes"].get("delay", 0) > self.vehicle_delay_threshold
            ]

            if delayed_buses:
                avg_delay = sum(delayed_buses) // len(delayed_buses)
                self.logger.warning(f"Vehicle delay detected: Avg {avg_delay} minutes")
                self.send_notification(
                    f"Bus {route} has delays. Avg delay: {avg_delay} minutes.",
                    subject="Vehicle Delay Alert"
                )
        except Exception as e:
            self.logger.error(f"Error checking vehicle delay: {e}")

    def get_prediction(self, route, stop_id):
        try:
            url = f"https://api.transitagency.com/predictions?route={route}&stop={stop_id}"
            response = requests.get(url)
            response.raise_for_status()

            prediction_data = response.json().get("data", [])
            if not prediction_data:
                return None

            attributes = prediction_data[0]["attributes"]
            arrival_time_str = attributes.get("arrival_time")
            if not arrival_time_str:
                return None

            arrival_time = datetime.fromisoformat(arrival_time_str)
            current_stop = attributes.get("current_stop", 0)
            stop_sequence = attributes.get("stop_sequence", 0)

            minutes_away = (arrival_time - datetime.now()).seconds // 60
            stops_away = abs(stop_sequence - current_stop)

            return {
                "arrival_time": arrival_time.isoformat(),
                "minutes_away": minutes_away,
                "stops_away": stops_away
            }
        except Exception as e:
            self.logger.error(f"Error getting prediction: {e}")
            return None

    def check_subscription_limit(self, user_id):
        subscriptions = self.data_service.get_user_subscriptions(user_id)
        return len(subscriptions) < self.max_subscriptions

    def add_subscription(self, user_id, route, stop_id):
        if not self.check_subscription_limit(user_id):
            return False
        try:
            self.data_service.add_subscription(user_id, route, stop_id)
            return True
        except Exception as e:
            self.logger.error(f"Error adding subscription for user {user_id}: {e}")
            return False

    def update_subscription_email(self, user_id, new_email):
        try:
            self.data_service.update_user_email(user_id, new_email)
        except Exception as e:
            self.logger.error(f"Error updating email for user {user_id}: {e}")

    def delete_subscription(self, user_id, route, stop_id):
        try:
            self.data_service.delete_subscription(user_id, route, stop_id)
        except Exception as e:
            self.logger.error(f"Error deleting subscription for user {user_id}: {e}")

    def subscribe_user_to_sns(self, email, user_id):
        try:
            self.logger.info(f"Subscribing user {email} to SNS topic")
            response = self.sns_client.subscribe(
                TopicArn=self.sns_topic_arn,
                Protocol='email',
                Endpoint=email,
                ReturnSubscriptionArn=True
            )
            subscription_arn = response.get("SubscriptionArn")
            if subscription_arn and subscription_arn != 'pending confirmation':
                self.data_service.store_subscription_arn(user_id, subscription_arn)
            return response
        except Exception as e:
            self.logger.error(f"Error subscribing user {email}: {e}")
            return None

    def unsubscribe_user_from_sns(self, user_id):
        try:
            arn = self.data_service.get_user_subscription_arn(user_id)
            if arn:
                self.sns_client.unsubscribe(SubscriptionArn=arn)
                self.data_service.delete_subscription_arn(user_id)
        except Exception as e:
            self.logger.error(f"Error unsubscribing user {user_id} from SNS: {e}")

    # The methods below should interact with Cognito user ID (sub) for proper data management

    def get_user_subscriptions(self, user_id):
        """ Fetch subscriptions associated with the user_id (extracted from Cognito JWT token) """
        try:
            return self.data_service.get_user_subscriptions(user_id)
        except Exception as e:
            self.logger.error(f"Error fetching subscriptions for user {user_id}: {e}")
            return []

    def add_subscription(self, user_id, route, stop_id):
        """ Add user subscription data to DynamoDB using user_id (Cognito JWT) as the partition key """
        try:
            return self.data_service.add_subscription(user_id, route, stop_id)
        except Exception as e:
            self.logger.error(f"Error adding subscription for user {user_id}: {e}")
            return None

    def update_subscription_email(self, user_id, new_email):
        """ Update user email in DynamoDB using user_id (Cognito JWT) """
        try:
            self.data_service.update_user_email(user_id, new_email)
        except Exception as e:
            self.logger.error(f"Error updating email for user {user_id}: {e}")

    def delete_subscription(self, user_id, route, stop_id):
        """ Remove user subscription from DynamoDB using user_id (Cognito JWT) """
        try:
            return self.data_service.delete_subscription(user_id, route, stop_id)
        except Exception as e:
            self.logger.error(f"Error removing subscription for user {user_id}: {e}")
            return None