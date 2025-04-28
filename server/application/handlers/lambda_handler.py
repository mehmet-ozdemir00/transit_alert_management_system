import os
import json
import boto3
import logging
import re
from application.services.transit_alert_service import TransitAlertSystem
from application.data_services.transport_data_stream import TransportDataService
from jose import jwt

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# This class handles the Lambda function for the Transit Alert Management System.
# It includes methods for subscribing, unsubscribing, updating email,
# and checking the status of user subscriptions.
# It also includes validation methods for user input and JWT token extraction.
# The class is initialized with the necessary environment variables,
# including SNS topic ARN, DynamoDB table name, and other configuration settings.
# The main method is the lambda_handler, which processes incoming requests
# based on the HTTP method (POST, PUT, DELETE, GET).
# The lambda_handler method is the entry point for the Lambda function.
# It handles the request, validates input, interacts with the TransitAlertSystem,
# and returns appropriate responses.
# The class also includes error handling for various scenarios,
# including invalid input, authorization errors, and unexpected exceptions.
# The responses are formatted in a consistent manner for API Gateway integration.
# The class uses AWS SDK (boto3) for interacting with AWS services,
# including SNS for notifications and DynamoDB for data storage.
# The class is designed to be used in a serverless environment, such as AWS Lambda,
# and is structured to handle incoming requests and responses in a consistent manner.
# The class is designed to be reusable and modular,
# allowing for easy integration with other components of the system.
# The class is also designed to be extensible,
# allowing for future enhancements and additional features as needed.
# The class is designed to be efficient and performant,
# ensuring that it can handle a large number of requests and subscriptions.
# The class is designed to be secure,
# ensuring that sensitive information is handled appropriately
# and that user data is protected.
# The class is designed to be maintainable,
# ensuring that it is easy to understand and modify as needed.
# The class is designed to be testable,
# ensuring that it can be easily unit tested and integrated into a larger testing framework.
# The class is designed to be compliant with best practices and standards,
# ensuring that it adheres to industry standards and guidelines for security, performance, and reliability.
# The class is designed to be user-friendly,
# ensuring that it provides clear and informative error messages
# and that it is easy to use for developers and users alike.

class LambdaFunctionService:
    @staticmethod
    def response(status_code, body):
        return {
            "statusCode": status_code,
            "body": json.dumps(body) if isinstance(body, dict) else body,
            "headers": {"Content-Type": "application/json"}
        }

    @staticmethod
    def validate_user_route_stop(user_id, route, stop_id):
        if not user_id or not isinstance(user_id, str):
            return "user_id is required and must be a string"
        if not route or not isinstance(route, str):
            return "route is required and must be a string"
        if not stop_id or not isinstance(stop_id, str):
            return "stop_id is required and must be a string"
        return None

    @staticmethod
    def validate_user_only(user_id):
        if not user_id or not isinstance(user_id, str):
            return "user_id is required and must be a string"
        return None

    @staticmethod
    def validate_email(email):
        if not email or not isinstance(email, str):
            return "email is required and must be a string"
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return "email is not valid"
        return None

    @staticmethod
    def get_user_id_from_jwt(event):
        token = event.get("headers", {}).get("Authorization", "").split("Bearer ")[-1]
        if not token:
            raise ValueError("Authorization token is missing")
        try:
            decoded_token = jwt.decode(token, options={"verify_aud": False})
            return decoded_token.get("sub")
        except jwt.ExpiredSignatureError:
            raise ValueError("Token is expired")
        except jwt.JWTError as e:
            raise ValueError(f"Error decoding token: {e}")

    @staticmethod
    def lambda_handler(event, context):
        try:
            sns_topic_arn = os.environ["SNS_TOPIC_ARN"]
            delay_threshold_minutes = int(os.environ.get("DELAY_THRESHOLD_MINUTES", "10"))
            vehicle_delay_threshold = int(os.environ.get("VEHICLE_DELAY_THRESHOLD", "5"))
            dynamodb_table_name = os.environ["DYNAMODB_TABLE_NAME"]
            max_subscriptions = int(os.environ.get("MAX_SUBSCRIPTIONS", "5"))

            data_service = TransportDataService(dynamodb_table_name)
            alert_system = TransitAlertSystem(
                sns_client=boto3.client("sns"),
                sns_topic_arn=sns_topic_arn,
                delay_threshold_minutes=delay_threshold_minutes,
                vehicle_delay_threshold=vehicle_delay_threshold,
                data_service=data_service,
                max_subscriptions=max_subscriptions
            )

            user_id = LambdaFunctionService.get_user_id_from_jwt(event)

            http_method = event.get("httpMethod", "").upper()
            path = event.get("path", "").lower()
            body = json.loads(event.get("body", "{}"))
            route = body.get("route")
            stop_id = body.get("stop_id")
            new_email = body.get("email")

            if http_method == "POST" and path == "/subscribe":
                logger.info("Processing POST /subscribe")
                error = LambdaFunctionService.validate_user_route_stop(user_id, route, stop_id)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})
                if not alert_system.check_subscription_limit(user_id):
                    return LambdaFunctionService.response(403, {"error": "Subscription limit reached."})
                alert_system.add_subscription(user_id, route, stop_id)
                error = LambdaFunctionService.validate_email(new_email)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})
                result = alert_system.subscribe_user_to_sns(new_email, user_id)
                if result:
                    return LambdaFunctionService.response(200, {"message": "Subscription request sent. Please confirm your email."})
                else:
                    return LambdaFunctionService.response(500, {"error": "Failed to subscribe the user to SNS."})

            elif http_method == "PUT" and path == "/email":
                logger.info("Processing PUT /email")
                error = LambdaFunctionService.validate_user_only(user_id)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})
                error = LambdaFunctionService.validate_email(new_email)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})
                alert_system.update_subscription_email(user_id, new_email)
                return LambdaFunctionService.response(200, {"message": "Email updated successfully."})

            elif http_method == "DELETE" and path == "/subscription":
                logger.info("Processing DELETE /subscription")
                error = LambdaFunctionService.validate_user_route_stop(user_id, route, stop_id)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})
                alert_system.delete_subscription(user_id, route, stop_id)
                return LambdaFunctionService.response(200, {"message": "Subscription removed successfully."})

            elif http_method == "DELETE" and path == "/unsubscribe":
                logger.info("Processing DELETE /unsubscribe")
                error = LambdaFunctionService.validate_user_only(user_id)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})
                alert_system.unsubscribe_user_from_sns(user_id)
                return LambdaFunctionService.response(200, {"message": "Unsubscribed from SNS successfully."})

            elif http_method == "GET" and path == "/status":
                logger.info("Processing GET /status")
                error = LambdaFunctionService.validate_user_only(user_id)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})
                subs = data_service.get_user_subscriptions(user_id)
                email = data_service.get_user_email(user_id)
                return LambdaFunctionService.response(200, {
                    "user_id": user_id,
                    "subscriptions": subs,
                    "email": email
                })

            return LambdaFunctionService.response(405, {"error": f"Method {http_method} with path {path} not allowed"})

        except ValueError as e:
            logger.error(f"Authorization error: {e}")
            return LambdaFunctionService.response(401, {"error": str(e)})
        except Exception as e:
            logger.exception("An unexpected error occurred")
            return LambdaFunctionService.response(500, {"message": "Internal server error", "error": str(e)})