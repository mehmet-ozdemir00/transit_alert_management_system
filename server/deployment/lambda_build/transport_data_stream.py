import boto3
import logging
from datetime import datetime
from boto3.dynamodb.conditions import Key

class TransportDataService:
    def __init__(self, table_name):
        self.table = boto3.resource("dynamodb").Table(table_name)
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)
        self.sns_client = boto3.client("sns")
        self.sns_topic_arn = "arn:aws:sns:us-east-1:851725323729:TransitAlertTopic"

    # Logs the prediction data for a user
    def log_prediction(self, user_id, bus_route, stop_id, prediction):
        try:
            required_keys = {"minutes_away", "stops_away", "arrival_time", "miles_away"}
            if not required_keys.issubset(prediction.keys()):
                self.logger.error(f"Prediction data missing required keys: {required_keys}")
                return
            
            self.logger.info(f"Updating prediction for user {user_id} on route {bus_route} with stop_id {stop_id}")
            
            response = self.table.update_item(
                Key={
                    "user_id": user_id,
                    "bus_route": bus_route
                },
                UpdateExpression="""
                    SET
                        stop_id = :stop_id,
                        minutes_away = :minutes,
                        stops_away = :stops,
                        miles_away = :miles,
                        arrival_time = :arrival,
                        #ts = :timestamp
                """,
                ExpressionAttributeNames={
                    "#ts": "timestamp"
                },
                ExpressionAttributeValues={
                    ":stop_id": stop_id,
                    ":minutes": prediction["minutes_away"],
                    ":stops": prediction["stops_away"],
                    ":miles": prediction["miles_away"],
                    ":arrival": prediction["arrival_time"],
                    ":timestamp": datetime.utcnow().isoformat()
                }
            )
            self.logger.info(f"Successfully updated prediction for {user_id}: {response}")
        except Exception as e:
            self.logger.error(f"Error logging prediction for {user_id}: {e}")

    # Get the user's status
    def get_user_subscriptions(self, user_id):
        try:
            response = self.table.query(
                KeyConditionExpression=Key("user_id").eq(user_id)
            )
            return [
                item for item in response.get("Items", [])
                if "bus_route" in item and item["bus_route"] != "email"
            ]
        except Exception as e:
            self.logger.error(f"Error getting subscriptions for {user_id}: {e}")
            return []

    # Get the user's subscription ARN for a specific bus route
    def get_user_subscription_arn(self, user_id, bus_route):
        try:
            response = self.table.query(
                KeyConditionExpression=Key("user_id").eq(user_id)
            )
            for item in response.get("Items", []):
                if item.get("bus_route") == bus_route and "subscription_arn" in item:
                    return item["subscription_arn"]
            return None
        except Exception as e:
            self.logger.error(f"Error fetching ARN for {user_id}: {e}")
            return None

    # Fetches SNS subscriptions by email and logs the matching ones
    def get_sns_subscriptions_by_email(self, email):
        try:
            response = self.sns_client.list_subscriptions_by_topic(TopicArn=self.sns_topic_arn)
            subscriptions = response.get("Subscriptions", [])
            
            for subscription in subscriptions:
                self.logger.info(f"Found subscription: {subscription.get('Endpoint')} - ARN: {subscription.get('SubscriptionArn')}")

            matched_subs = [
                sub for sub in subscriptions
                if sub.get("Endpoint") == email and sub.get("SubscriptionArn") != "PendingConfirmation"
            ]
            self.logger.info(f"Matched subscriptions for {email}: {matched_subs}")
            return matched_subs

        except Exception as e:
            self.logger.error(f"Error fetching SNS subscriptions for email {email}: {e}")
            return []

    # Fetches all unique bus routes for a user
    def get_all_unique_routes(self):
        try:
            response = self.table.scan(ProjectionExpression="bus_route")
            items = response.get("Items", [])
            unique_routes = list(set(item["bus_route"] for item in items if "bus_route" in item))
            return unique_routes
        except Exception as e:
            self.logger.error(f"Error fetching unique routes: {e}")
            return []

    # Unsubscribes the user from an SNS topic using their subscription ARN
    def unsubscribe_from_sns(self, subscription_arn):
        try:
            self.sns_client.unsubscribe(SubscriptionArn=subscription_arn)
            self.logger.info(f"Unsubscribed from SNS: {subscription_arn}")
        except Exception as e:
            self.logger.error(f"Failed to unsubscribe ARN {subscription_arn}: {e}")


    # Get the user's email address
    def update_user_email(self, user_id, new_email):
        try:
            # Fetch all items for this user
            response = self.table.query(
                KeyConditionExpression=Key("user_id").eq(user_id)
            )
            items = response.get("Items", [])

            # Update each item with the new email and email_status
            for item in items:
                old_arn = item.get("subscription_arn")

                # Unsubscribe old SNS ARN if it exists
                if old_arn:
                    try:
                        self.sns_client.unsubscribe(SubscriptionArn=old_arn)
                        self.logger.info(f"Unsubscribed old ARN: {old_arn}")
                    except Exception as e:
                        self.logger.warning(f"Failed to unsubscribe old ARN {old_arn}: {e}")

                # Subscribe new email
                try:
                    sns_response = self.sns_client.subscribe(
                        TopicArn=self.sns_topic_arn,
                        Protocol="email",
                        Endpoint=new_email,
                        ReturnSubscriptionArn=True
                    )
                    new_arn = sns_response.get("SubscriptionArn", "pending_confirmation")
                    self.logger.info(f"Subscribed new email {new_email} with ARN {new_arn}")
                except Exception as e:
                    self.logger.error(f"Failed to subscribe new email {new_email}: {e}")
                    new_arn = None

                # Update DynamoDB with new email, status and ARN
                update_expression = "SET email = :email, email_status = :status"
                expression_values = {
                    ":email": new_email,
                    ":status": "pending_confirmation"
                }

                if new_arn:
                    update_expression += ", subscription_arn = :arn"
                    expression_values[":arn"] = new_arn

                self.table.update_item(
                    Key={
                        "user_id": user_id,
                        "bus_route": item["bus_route"]
                    },
                    UpdateExpression=update_expression,
                    ExpressionAttributeValues=expression_values
                )
            return True
        except Exception as e:
            self.logger.error(f"Error updating email and re-subscribing for {user_id}: {e}")
            return False

    # Deletes a subscription record from DynamoDB
    def delete_subscription_record(self, user_id, route):
        try:
            self.table.delete_item(
                Key={
                    "user_id": user_id,
                    "bus_route": route
                }
            )
            self.logger.info(f"Deleted subscription for user {user_id}, route {route}")
        except Exception as e:
            self.logger.error(f"Error deleting subscription for user {user_id}, route {route}: {e}")
            raise

    # Saves a new subscription record in DynamoDB for the user
    def save_subscription_record(self, user_id, bus_route, stop_id, email, subscription_arn, email_status):
        try:
            self.table.put_item(Item={
                "user_id": user_id,
                "bus_route": bus_route,
                "stop_id": stop_id,
                "email": email,
                "subscription_arn": subscription_arn,
                "email_status": email_status,
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            self.logger.error(f"Error saving subscription for {user_id}: {e}")