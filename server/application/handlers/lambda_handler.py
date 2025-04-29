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

# This class handles the AWS Lambda function that serves as the entry point for the API.
# It processes incoming requests, validates input, and interacts with the TransitAlertSystem
# and TransportDataService classes to perform various operations such as subscribing users,
# updating email addresses, deleting subscriptions, and checking vehicle delays.
# It also handles error responses and returns appropriate HTTP status codes and messages.
# The class is designed to be reusable and can be easily extended
# to include additional functionality as needed.
# The class uses the boto3 library to interact with AWS services such as SNS and DynamoDB.
# The class also includes methods for validating user input,
# extracting user IDs from JWT tokens, and formatting responses for the API.
# The class is designed to be used in a serverless environment,
# where it can be triggered by AWS Lambda functions.

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

            valid_routes = {
                ("POST", "/subscribe"),
                ("PUT", "/email"),
                ("DELETE", "/subscription"),
                ("DELETE", "/unsubscribe"),
                ("GET", "/status"),
                ("GET", "/prediction"),
                ("GET", "/delay"),
            }

            if (http_method, path) not in valid_routes:
                return LambdaFunctionService.response(405, {"error": f"Method {http_method} with path {path} not allowed"})

            body = json.loads(event.get("body", "{}")) if event.get("body") else {}
            query_params = event.get("queryStringParameters", {}) or {}

            route = body.get("route") or query_params.get("route")
            stop_id = body.get("stop_id") or query_params.get("stop_id")
            new_email = body.get("email")

            if http_method == "POST" and path == "/subscribe":
                logger.info("Processing POST /subscribe")
                error = LambdaFunctionService.validate_user_route_stop(user_id, route, stop_id)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})

                if not alert_system.check_subscription_limit(user_id):
                    return LambdaFunctionService.response(403, {"error": "Subscription limit reached."})

                error = LambdaFunctionService.validate_email(new_email)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})

                alert_system.add_subscription(user_id, route, stop_id)
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
                return LambdaFunctionService.response(200, {"message": "Unsubscribed and goodbye email sent!"})

            elif http_method == "GET" and path == "/status":
                logger.info("Processing GET /status")
                error = LambdaFunctionService.validate_user_only(user_id)
                if error:
                    return LambdaFunctionService.response(400, {"error": error})

                subs = data_service.get_user_subscriptions(user_id)
                email = data_service.get_user_email(user_id)
                return LambdaFunctionService.response(200, {
                    "subscriptions": subs,
                    "email": email
                })

            elif http_method == "GET" and path == "/prediction":
                logger.info("Processing GET /prediction")
                route = query_params.get("route")
                stop_id = query_params.get("stop_id")

                if not route or not stop_id:
                    return LambdaFunctionService.response(400, {"error": "Missing route or stop_id in query parameters"})

                prediction = alert_system.get_prediction(route, stop_id)
                if prediction:
                    return LambdaFunctionService.response(200, prediction)
                else:
                    return LambdaFunctionService.response(404, {"message": "No prediction data available"})

            elif http_method == "GET" and path == "/delay":
                logger.info("Processing GET /delay")
                route = query_params.get("route")

                if not route:
                    return LambdaFunctionService.response(400, {"error": "Missing route in query parameters"})

                alert_system.check_vehicle_delay(route)
                return LambdaFunctionService.response(200, {"message": f"Checked vehicle delay for route {route}"})

        except ValueError as e:
            logger.error(f"Authorization error: {e}")
            return LambdaFunctionService.response(401, {"error": str(e)})

        except Exception as e:
            logger.exception("An unexpected error occurred")
            return LambdaFunctionService.response(500, {"message": "Internal server error", "error": str(e)})