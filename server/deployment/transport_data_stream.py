import boto3
import logging
from datetime import datetime
from boto3.dynamodb.conditions import Key

# This class handles the interaction with DynamoDB for transport data
# It includes methods for logging predictions, managing user subscriptionsand handling user email updates.
# It also includes error handling and logging for each operation.
# The class is initialized with the table name and an event object,
# which is used to extract the user ID from the JWT token in the event headers.
# The user ID is used as a partition key for DynamoDB operations.
# The class uses the boto3 library to interact with DynamoDB.
# The class also includes methods for adding, deleting, and updating user subscriptions,
# as well as storing and retrieving user email addresses and subscription ARNs.
# The class is designed to be used in a serverless environment,
# where it can be triggered by AWS Lambda functions.
# The class is also designed to be reusable and can be easily extended
# to include additional functionality as needed.

class TransportDataService:
    def __init__(self, table_name):
        self.table = boto3.resource("dynamodb").Table(table_name)
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

    def log_prediction(self, user_id, bus_route, stop_id, prediction):
        try:
            self.table.put_item(Item={
                "user_id": user_id,
                "bus_route": bus_route,
                "stop_id": stop_id,
                "timestamp": datetime.utcnow().isoformat(),
                "minutes_away": prediction["minutes_away"],
                "stops_away": prediction["stops_away"],
                "arrival_time": prediction["arrival_time"]
            })
        except Exception as e:
            self.logger.error(f"Error logging prediction: {e}")

    def get_user_subscriptions(self, user_id):
        try:
            response = self.table.query(
                KeyConditionExpression=Key("user_id").eq(user_id)
            )
            return [
                item for item in response.get("Items", [])
                if item.get("bus_route") != "email"
            ]
        except Exception as e:
            self.logger.error(f"Error fetching subscriptions for user {user_id}: {e}")
            return []

    def add_subscription(self, user_id, bus_route, stop_id):
        try:
            self.table.put_item(Item={
                "user_id": user_id,
                "bus_route": bus_route,
                "stop_id": stop_id,
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            self.logger.error(f"Error adding subscription for user {user_id}: {e}")

    def update_user_email(self, user_id, new_email):
        try:
            self.table.put_item(Item={
                "user_id": user_id,
                "bus_route": "email",  # Special marker to store email
                "email": new_email,
                "updated_at": datetime.utcnow().isoformat()
            })
        except Exception as e:
            self.logger.error(f"Error updating email for user {user_id}: {e}")

    def delete_subscription(self, user_id, bus_route):
        try:
            self.table.delete_item(
                Key={
                    "user_id": user_id,
                    "bus_route": bus_route
                }
            )
        except Exception as e:
            self.logger.error(f"Error deleting subscription for user {user_id}: {e}")

    def store_subscription_arn(self, user_id, arn):
        try:
            self.table.update_item(
                Key={"user_id": user_id, "bus_route": "email"},
                UpdateExpression="SET subscription_arn = :arn",
                ExpressionAttributeValues={':arn': arn}
            )
        except Exception as e:
            self.logger.error(f"Error storing subscription ARN for user {user_id}: {e}")

    def get_user_subscription_arn(self, user_id):
        try:
            response = self.table.get_item(
                Key={"user_id": user_id, "bus_route": "email"}
            )
            return response.get("Item", {}).get("subscription_arn")
        except Exception as e:
            self.logger.error(f"Error getting subscription ARN for user {user_id}: {e}")
            return None

    def delete_subscription_arn(self, user_id):
        try:
            self.table.update_item(
                Key={"user_id": user_id, "bus_route": "email"},
                UpdateExpression="REMOVE subscription_arn"
            )
        except Exception as e:
            self.logger.error(f"Error deleting subscription ARN for user {user_id}: {e}")

    def get_user_email(self, user_id):
        try:
            response = self.table.get_item(
                Key={"user_id": user_id, "bus_route": "email"}
            )
            return response.get("Item", {}).get("email")
        except Exception as e:
            self.logger.error(f"Error getting email for user {user_id}: {e}")
            return None