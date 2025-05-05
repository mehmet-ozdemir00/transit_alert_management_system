import os
import logging
import requests, time
import re
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

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

        self.api_key = os.getenv("MTA_API_KEY")
        self.vehicle_monitoring_url = "https://bustime.mta.info/api/siri/vehicle-monitoring.json"
        self.stop_monitoring_url = "https://bustime.mta.info/api/siri/stop-monitoring.json"

        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

    # Validate email format
    def is_valid_email(self, email):
        return isinstance(email, str) and re.match(r"[^@]+@[^@]+\.[^@]+", email)

    # Check if the user has reached the maximum number of subscriptions
    def check_subscription_limit(self, user_id):
        return len(self.data_service.get_user_subscriptions(user_id)) < self.max_subscriptions

    # Subscribe user to SNS topic
    def subscribe_user_to_sns(self, email, user_id, bus_route, stop_id):
        if not self.is_valid_email(email):
            self.logger.warning("Invalid email format")
            return False
        try:
            existing_arn = self.data_service.get_user_subscription_arn(user_id, bus_route)
            if existing_arn:
                attributes = self.sns_client.get_subscription_attributes(
                    SubscriptionArn=existing_arn
                ).get('Attributes', {})
                # If the subscription is confirmed, return
                if attributes.get("SubscriptionStatus", "").lower() == "confirmed":
                    self.logger.info(f"User {user_id} already confirmed for route {bus_route}")
                    return True

            # Subscribe the user to the SNS topic
            response = self.sns_client.subscribe(
                TopicArn=self.sns_topic_arn,
                Protocol='email',
                Endpoint=email,
                ReturnSubscriptionArn=True
            )
            arn = response.get("SubscriptionArn")
            status = "pending" if arn and arn != "pending confirmation" else "pending"

            self.data_service.save_subscription_record(
                user_id=user_id,
                bus_route=bus_route,
                stop_id=stop_id,
                email=email,
                subscription_arn=arn,
                email_status=status
            )

            if status == "confirmed":
                self.send_notification("You're subscribed to Transit Alerts!", subject="Subscription Confirmed")
            return True
        except Exception as e:
            self.logger.error(f"Error subscribing to SNS: {e}")
            return False

    # Send notification to the user
    def send_notification(self, message, subject="Transit Alert"):
        try:
            return self.sns_client.publish(
                TopicArn=self.sns_topic_arn,
                Message=message,
                Subject=subject
            )
        except Exception as e:
            self.logger.error(f"Error sending notification: {e}")
            return None
        
    # Check if the user has a valid subscription
    def get_user_status(self, user_id):
        try:
            return self.data_service.get_user_subscriptions(user_id)
        except Exception as e:
            self.logger.error(f"Error retrieving status for {user_id}: {e}")
            return []
        
    # Check for vehicle delays
    def check_vehicle_delay(self, route):
        try:
            params = {
                "key": self.api_key,
                "VehicleMonitoringDetailLevel": "calls",
                "LineRef": route
            }

            # Send the request to the vehicle monitoring API
            response = requests.get(self.vehicle_monitoring_url, params=params)
            data = response.json()

            # Check if vehicle data exists in the response
            if not data.get("Siri", {}).get("ServiceDelivery", {}).get("VehicleMonitoringDelivery", []):
                self.logger.warning(f"No vehicle data found for route {route}")
                return
            
            # # 🔽 Testing the delay and trigger SNS email!!!
            # delay_minutes = self.delay_threshold_minutes + 5
            # self.send_notification(
            #     f"[TEST] Simulated Delay Alert: Route {route} is delayed by {delay_minutes:.2f} minutes.",
            #     subject=f"[TEST] Delay Alert: {route}"
            # )

            # Iterate over vehicle data and check delay for each stop
            for delivery in data["Siri"]["ServiceDelivery"]["VehicleMonitoringDelivery"]:
                for vehicle in delivery.get("VehicleActivity", []):
                    # Extract stop point details
                    stop_point = vehicle.get("MonitoredVehicleJourney", {}).get("MonitoredCall", {})
                    if stop_point:
                        stop_id = stop_point.get("StopPointRef")
                        expected_arrival_time = stop_point.get("ExpectedArrivalTime")
                        # Check if the expected arrival time is available
                        if expected_arrival_time:
                            arrival_time = datetime.fromisoformat(expected_arrival_time.replace("Z", "+00:00"))
                            delay_minutes = (arrival_time - datetime.now(timezone.utc)).total_seconds() / 60
                            # Check if the delay exceeds the threshold
                            if delay_minutes > self.delay_threshold_minutes:
                                self.send_notification(
                                    f"Delay Alert: Route {route} at Stop {stop_id} is delayed by {delay_minutes:.2f} minutes."
                                )
        except Exception as e:
            self.logger.error(f"Error checking vehicle delay: {e}")
            return None
        return True
    
    # Get prediction for a specific route and stop
    def get_prediction(self, route, stop_id):
        attempt = 0
        while attempt < self.max_retries:
            try:
                params = {
                    "key": self.api_key,
                    "MonitoringRef": stop_id,
                    "LineRef": route,
                    "MaximumStopVisits": 3
                }
                # Send the request to the stop monitoring API
                response = requests.get(self.stop_monitoring_url, params=params)
                data = response.json()

                stop_monitoring_delivery = data.get("Siri", {}).get("ServiceDelivery", {}).get("StopMonitoringDelivery", [])
                stop_data = stop_monitoring_delivery[0].get("MonitoredStopVisit", []) if stop_monitoring_delivery else []

                # Check if stop data exists in the response
                if not stop_data:
                    self.logger.warning(f"No prediction data found for route {route} at stop {stop_id}")
                    return {"message": "No prediction data available"}
                
                # Extract the relevant data from the response
                journey = stop_data[0].get("MonitoredVehicleJourney", {})
                monitored_call = journey.get("MonitoredCall", {})

                # Check if the monitored call data exists
                arrival_time_str = monitored_call.get("ExpectedArrivalTime")
                if not arrival_time_str:
                    return {"message": "No expected arrival time available"}
                
                # Parse arrival time and calculate difference
                arrival_time = datetime.fromisoformat(arrival_time_str.replace("Z", "+00:00"))
                arrival_time_local = arrival_time.astimezone(ZoneInfo("America/New_York"))
                current_time = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
                delta_seconds = (arrival_time_local - current_time).total_seconds()
                minutes_away = max(0, int(delta_seconds // 60))

                # Stops away
                distances = monitored_call.get("Extensions", {}).get("Distances", {})
                stops_raw = distances.get("StopsFromCall")
                stops_away = f"{stops_raw} stop{'s' if stops_raw != 1 else ''} away" if stops_raw is not None else "N/A"

                # Distance in miles
                meters = distances.get("DistanceFromCall")
                miles_away = f"{meters / 1609.34:.1f} miles away" if meters is not None else "N/A"

                return {
                    "route": route,
                    "minutes_away": f"{minutes_away} minutes",
                    "stops_away": stops_away,
                    "miles_away": miles_away,
                    "arrival_time": arrival_time_local.strftime('%H:%M:%S')
                }
            
            # Handle request exceptions and retry
            except requests.exceptions.RequestException as e:
                attempt += 1
                self.logger.error(f"Error getting prediction: {e}. Retrying {attempt}/{self.max_retries}")
                time.sleep(self.retry_delay)
            except Exception as e:
                self.logger.error(f"Error getting prediction: {e}")
                break
        return None
    
    # Updates the user's email in DynamoDB and sends a confirmation notification.
    def update_subscription_email(self, user_id, new_email):
        try:
            success = self.data_service.update_user_email(user_id, new_email)
            if success:
                self.send_notification(
                    f"Your email has been successfully updated to {new_email}",
                    subject="Email Update Confirmation"
                )
                return True
            else:
                self.logger.error(f"Failed to update email for {user_id}")
                return False
        except Exception as e:
            self.logger.error(f"Error updating email for {user_id}: {e}")
            return False
        

    # Unsubscribe the user from SNS topic
    def unsubscribe_email_from_sns(self, email):
        try:
            response = self.sns_client.list_subscriptions_by_topic(TopicArn=self.sns_topic_arn)
            subscriptions = response.get("Subscriptions", [])
            found = False

            for subscription in subscriptions:
                endpoint = subscription.get("Endpoint")
                arn = subscription.get("SubscriptionArn")
                protocol = subscription.get("Protocol")

                self.logger.info(f"Checking subscription: {endpoint} - ARN: {arn}")

                # Skip "PendingConfirmation" subscriptions
                if arn == "PendingConfirmation":
                    self.logger.warning(f"Subscription for {email} is pending confirmation. Cannot unsubscribe.")
                    return False
                
                # If ARN is not valid or has already been deleted in SNS, skip
                if arn == "Deleted" or arn is None:
                    self.logger.info(f"Subscription for {email} is marked as deleted or does not exist. Skipping.")
                    continue

                # Proceed with unsubscribe if active
                self.sns_client.unsubscribe(SubscriptionArn=arn)
                self.logger.info(f"Successfully unsubscribed email {email} from SNS: {arn}")
                found = True

            if not found:
                self.logger.info(f"No active confirmed subscription found for email {email}")
                return False

            return True
        except Exception as e:
            self.logger.error(f"Error unsubscribing {email} from SNS: {e}")
            return False
        
    # Unsubscribe the user from SNS topic and delete their record from DynamoDB
    def delete_dynamodb_only_subscription(self, user_id, route):
        try:
            # Delete the subscription record from DynamoDB
            self.data_service.delete_subscription_record(user_id, route)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting subscription for {user_id}, route {route}: {e}")
            return False

    # Check if the route is cancelled
    def check_if_route_cancelled(self, route):
        try:
            params = {
                "key": self.api_key,
                "VehicleMonitoringDetailLevel": "calls",
                "LineRef": route
            }

            response = requests.get(self.vehicle_monitoring_url, params=params)
            data = response.json()

            deliveries = data.get("Siri", {}).get("ServiceDelivery", {}).get("VehicleMonitoringDelivery", [])
            for delivery in deliveries:
                if delivery.get("VehicleActivity"):
                    self.logger.info(f"Route {route} is active.")
                    return False
                
            return True
        except Exception as e:
            self.logger.error(f"Error checking if route {route} is cancelled: {e}")
            return False
        
    
    # Get all cancelled routes
    def get_cancelled_routes(self):
        routes_to_check = self.data_service.get_all_unique_routes()
        cancelled = []
        active_routes = []

        for route in routes_to_check:
            is_cancelled = self.check_if_route_cancelled(route)
            if is_cancelled:
                cancelled.append(route)
                self.logger.info(f"Route {route} is cancelled.")
            else:
                active_routes.append(route)
                self.logger.info(f"Route {route} is active.")
        return cancelled, active_routes