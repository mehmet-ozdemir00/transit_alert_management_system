import logging
import os
import requests
import time
from datetime import datetime

# Transit Alert System
# Use the real MTA BusTime API
# Use the real AWS SNS for notifications
# Use the real DynamoDB for data storage
# This class handles the interaction with the MTA API for transit alerts
# It includes methods for checking vehicle delays, getting predictions,
# managing user subscriptions, and sending notifications via AWS SNS.
# It also includes error handling and logging for each operation.
# The class is initialized with the SNS client, SNS topic ARN, delay threshold,
# vehicle delay threshold, and a data service for managing user subscriptions.
# The class uses the requests library to interact with the MTA API
# and the boto3 library to interact with AWS SNS and DynamoDB.
# The class also includes methods for adding, deleting, and updating user subscriptions,
# as well as storing and retrieving user email addresses and subscription ARNs.

class TransitAlertSystem:
    def __init__(self, sns_client, sns_topic_arn, delay_threshold_minutes, vehicle_delay_threshold, data_service, max_subscriptions=10, max_retries=3, retry_delay=5):
        self.sns_client = sns_client
        self.sns_topic_arn = sns_topic_arn
        self.delay_threshold_minutes = delay_threshold_minutes
        self.vehicle_delay_threshold = vehicle_delay_threshold
        self.data_service = data_service
        self.max_subscriptions = max_subscriptions
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Load MTA API key securely from environment variable
        self.api_key = os.getenv("MTA_API_KEY")
        self.vehicle_monitoring_url = "https://bustime.mta.info/api/siri/vehicle-monitoring.json"
        self.stop_monitoring_url = "https://bustime.mta.info/api/siri/stop-monitoring.json"

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
        attempt = 0
        while attempt < self.max_retries:
            try:
                params = {
                    "key": self.api_key,
                    "LineRef": route
                }
                self.logger.info(f"Checking vehicle delay for route {route}")
                response = requests.get(self.vehicle_monitoring_url, params=params, timeout=5)
                response.raise_for_status()

                vehicle_data = response.json().get("Siri", {}).get("ServiceDelivery", {}).get("VehicleMonitoringDelivery", [])[0].get("VehicleActivity", [])
                delayed_buses = []

                for activity in vehicle_data:
                    progress_status = activity.get("MonitoredVehicleJourney", {}).get("ProgressStatus", "")
                    delay_minutes = activity.get("MonitoredVehicleJourney", {}).get("Delay", 0) // 60  # delay in minutes
                    if "delayed" in progress_status.lower() and delay_minutes >= self.vehicle_delay_threshold:
                        delayed_buses.append(progress_status)

                if delayed_buses:
                    self.logger.warning(f"Vehicle delay detected on route {route}")
                    self.send_notification(
                        f"Bus route {route} has vehicles experiencing delays of more than {self.vehicle_delay_threshold} minutes.",
                        subject="Vehicle Delay Alert"
                    )
                else:
                    self.logger.info(f"No significant delays detected for route {route}.")
                return
            except requests.exceptions.RequestException as e:
                attempt += 1
                self.logger.error(f"Error checking vehicle delay: {e}. Retrying {attempt}/{self.max_retries}")
                if attempt >= self.max_retries:
                    self.logger.error(f"Failed to check vehicle delay for route {route} after {self.max_retries} attempts")
                    break
                time.sleep(self.retry_delay)

    def get_prediction(self, route, stop_id):
        attempt = 0
        while attempt < self.max_retries:
            try:
                params = {
                    "key": self.api_key,
                    "MonitoringRef": stop_id,
                    "LineRef": route
                }
                self.logger.info(f"Getting prediction for route {route}, stop {stop_id}")
                response = requests.get(self.stop_monitoring_url, params=params, timeout=5)
                response.raise_for_status()

                stop_data = response.json().get("Siri", {}).get("ServiceDelivery", {}).get("StopMonitoringDelivery", [])[0].get("MonitoredStopVisit", [])
                if not stop_data:
                    self.logger.info(f"No upcoming buses found for route {route} at stop {stop_id}")
                    return None

                journey = stop_data[0]["MonitoredVehicleJourney"]
                arrival_time_str = journey.get("MonitoredCall", {}).get("ExpectedArrivalTime")

                if not arrival_time_str:
                    self.logger.info(f"No arrival time found for route {route} at stop {stop_id}")
                    return None

                arrival_time = datetime.fromisoformat(arrival_time_str.replace("Z", "+00:00"))
                current_time = datetime.now(datetime.utcnow().astimezone().tzinfo)
                minutes_away = (arrival_time - current_time).seconds // 60

                stops_away = journey.get("MonitoredCall", {}).get("StopPointDistanceToStop")

                return {
                    "arrival_time": arrival_time.isoformat(),
                    "minutes_away": minutes_away,
                    "stops_away": stops_away
                }
            except requests.exceptions.RequestException as e:
                attempt += 1
                self.logger.error(f"Error getting prediction: {e}. Retrying {attempt}/{self.max_retries}")
                if attempt >= self.max_retries:
                    self.logger.error(f"Failed to get prediction for route {route} and stop {stop_id} after {self.max_retries} attempts")
                    break
                time.sleep(self.retry_delay)
            except Exception as e:
                self.logger.error(f"Unexpected error getting prediction: {e}")
                break

        return None

    def check_subscription_limit(self, user_id):
        subscriptions = self.data_service.get_user_subscriptions(user_id)
        return len(subscriptions) < self.max_subscriptions

    def add_subscription(self, user_id, route, stop_id):
        if not self.check_subscription_limit(user_id):
            self.logger.warning(f"User {user_id} has reached subscription limit")
            return False
        try:
            self.data_service.add_subscription(user_id, route, stop_id)
            self.logger.info(f"Added subscription for user {user_id} to route {route} and stop {stop_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error adding subscription for user {user_id}: {e}")
            return False

    def update_subscription_email(self, user_id, new_email):
        try:
            self.data_service.update_user_email(user_id, new_email)
            self.logger.info(f"Updated email for user {user_id} to {new_email}")
        except Exception as e:
            self.logger.error(f"Error updating email for user {user_id}: {e}")

    def delete_subscription(self, user_id, route, stop_id):
        try:
            self.data_service.delete_subscription(user_id, route, stop_id)
            self.logger.info(f"Deleted subscription for user {user_id} from route {route} and stop {stop_id}")
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
                self.send_notification(
                    "Thank you for subscribing to Transit Alerts! Please confirm your email subscription to start receiving alerts.",
                    subject="Subscription Confirmation"
                )
            else:
                self.logger.info(f"User {email} subscription pending confirmation")
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
            self.send_notification(
                "You have been unsubscribed. Thanks for riding with us!",
                subject="Goodbye from Transit Alerts"
            )
        except Exception as e:
            self.logger.error(f"Error unsubscribing user {user_id}: {e}")