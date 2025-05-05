import os
import json
import boto3
import logging
import re
import requests
from jose import jwt, JWTError, ExpiredSignatureError

from transit_alert_service import TransitAlertSystem
from transport_data_stream import TransportDataService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

class LambdaFunctionService:
    jwks = None

    @staticmethod
    def response(status_code, body):
        return {
            "statusCode": status_code,
            "body": json.dumps(body) if isinstance(body, dict) else body,
            "headers": {"Content-Type": "application/json"}
        }

    @staticmethod
    def decode_jwt(event):
        if os.getenv("ENV", "").lower() == "dev":
            return {"sub": "test-user-id", "email": "test@example.com"}

        auth_header = event.get("headers", {}).get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise ValueError("Invalid Authorization header format. Expected 'Bearer <token>'")

        token = auth_header.split("Bearer ")[-1].strip()
        if not token:
            raise ValueError("Authorization token is missing or empty")

        region = os.environ["COGNITO_REGION"]
        user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
        audience = os.environ.get("COGNITO_APP_CLIENT_ID")
        jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"

        if LambdaFunctionService.jwks is None:
            response = requests.get(jwks_url)
            if response.status_code != 200:
                raise ValueError("Unable to fetch JWKS from Cognito")
            LambdaFunctionService.jwks = response.json().get("keys", [])

        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            if not kid:
                raise ValueError("Invalid token header: missing 'kid'")

            key = next((k for k in LambdaFunctionService.jwks if k["kid"] == kid), None)
            if not key:
                raise ValueError("Public key not found in JWKS")

            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=audience,
                issuer=f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
            )
            return payload
        except ExpiredSignatureError:
            raise ValueError("Token is expired")
        except JWTError as e:
            raise ValueError(f"Invalid token: {str(e)}")
        except Exception as e:
            raise ValueError(f"Error decoding token: {str(e)}")

    @staticmethod
    def validate_user_route(user_id, route, stop_id):
        if not user_id or not isinstance(user_id, str):
            return "user_id is required and must be a string"
        if not route or not isinstance(route, str):
            return "route is required and must be a string"
        if not stop_id or not isinstance(stop_id, (str, int)):
            return "stop_id is required and must be a string or integer"
        return None

    @staticmethod
    def validate_email(email):
        if not email or not isinstance(email, str):
            return "email is required and must be a string"
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return "email is not valid"
        return None

@staticmethod
def lambda_handler(event, context):
    try:
        sns_topic_arn = os.environ["SNS_TOPIC_ARN"]
        delay_threshold_minutes = int(os.environ.get("DELAY_THRESHOLD_MINUTES", "4"))
        vehicle_delay_threshold = int(os.environ.get("VEHICLE_DELAY_THRESHOLD", "5"))
        dynamodb_table_name = os.environ["DYNAMODB_TABLE_NAME"]
        max_subscriptions = int(os.environ.get("MAX_SUBSCRIPTIONS", "5"))
        max_retries = int(os.environ.get("MAX_RETRIES", "3"))
        retry_delay = int(os.environ.get("RETRY_DELAY", "5"))

        data_service = TransportDataService(dynamodb_table_name)
        alert_system = TransitAlertSystem(
            sns_client=boto3.client("sns"),
            sns_topic_arn=sns_topic_arn,
            delay_threshold_minutes=delay_threshold_minutes,
            vehicle_delay_threshold=vehicle_delay_threshold,
            data_service=data_service,
            max_subscriptions=max_subscriptions,
            max_retries=max_retries,
            retry_delay=retry_delay
        )

        claims = LambdaFunctionService.decode_jwt(event)
        user_id = claims.get("sub")
        http_method = event.get("httpMethod", "").upper()
        path = event.get("path", "").lower()

        # POST /subscribe
        if http_method == "POST" and path == "/subscribe":
            body = json.loads(event.get("body", "{}")) if event.get("body") else {}
            route = body.get("route")
            stop_id = body.get("stop_id")
            email = body.get("email")

            error = LambdaFunctionService.validate_user_route(user_id, route, stop_id)
            if error:
                return LambdaFunctionService.response(400, {"error": error})

            error = LambdaFunctionService.validate_email(email)
            if error:
                return LambdaFunctionService.response(400, {"error": error})

            if not alert_system.check_subscription_limit(user_id):
                return LambdaFunctionService.response(403, {"error": "Subscription limit reached."})

            result = alert_system.subscribe_user_to_sns(email, user_id, route, stop_id)
            if result:
                return LambdaFunctionService.response(200, {"message": "Subscription request sent. Please confirm your email."})
            else:
                return LambdaFunctionService.response(500, {"error": "Failed to subscribe the user to SNS."})

        # GET /status
        elif http_method == "GET" and path == "/status":
            result = alert_system.get_user_status(user_id)
            return LambdaFunctionService.response(200, {"subscriptions": result})

        # GET /delay
        elif http_method == "GET" and path == "/delay":
            route = event.get("queryStringParameters", {}).get("route")
            if not route:
                return LambdaFunctionService.response(400, {"error": "Missing required query parameter: route"})
            
            alert_system.check_vehicle_delay(route)
            return LambdaFunctionService.response(200, {"message": f"Checked vehicle delay for route {route}. No significant delays detected at this time."})

        # GET /prediction
        elif http_method == "GET" and path == "/prediction":
            query_params = event.get("queryStringParameters") or {}
            route = query_params.get("route")
            stop_id = query_params.get("stop_id")

            error = LambdaFunctionService.validate_user_route(user_id, route, stop_id)
            if error:
                return LambdaFunctionService.response(400, {"error": error})
            
            prediction = alert_system.get_prediction(route, stop_id)

            # Handle missing or invalid prediction
            if prediction is None or "message" in prediction:
                return LambdaFunctionService.response(404, {"error": prediction.get("message", "No prediction data found")})
            
            # Log prediction to DynamoDB
            data_service.log_prediction(user_id, route, stop_id, prediction)
            return LambdaFunctionService.response(200, prediction)

        # Get /cancelled
        elif http_method == "GET" and path == "/cancelled":
            cancelled_routes, active_routes = alert_system.get_cancelled_routes()

            if cancelled_routes is None:
                return LambdaFunctionService.response(404, {"error": "No cancelled routes found."})
            
            # Creaating the response
            body = {
                "cancelled_routes": cancelled_routes,
                "active_routes": active_routes,
                "count_cancelled": len(cancelled_routes),
                "count_active": len(active_routes),
                "message": "Cancelled and active routes retrieved successfully."
            }
            return LambdaFunctionService.response(200, body)

        # PUT /email
        elif http_method == "PUT" and path == "/email":
            # Retrieve the new email from the request body
            body = json.loads(event.get("body", "{}")) if event.get("body") else {}
            new_email = body.get("new_email")

            # Validate the new email
            error = LambdaFunctionService.validate_email(new_email)
            if error:
                return LambdaFunctionService.response(400, {"error": error})
            
            try:
                # Update the user's email in the DynamoDB table
                result = alert_system.update_subscription_email(user_id, new_email)
                if result:
                    return LambdaFunctionService.response(200, {"message": "Email updated successfully."})
                else:
                    return LambdaFunctionService.response(500, {"error": "Failed to update email."})
            except Exception as e:
                logger.error(f"Error updating email for {user_id}: {e}")
                return LambdaFunctionService.response(500, {"error": "Internal server error"})

        # DELETE /unsubscribe
        elif http_method == "DELETE" and path == "/unsubscribe":
            body = json.loads(event.get("body", "{}")) if event.get("body") else {}
            email = body.get("email")

            if not email:
                return LambdaFunctionService.response(400, {"error": "Email is required"})
            
            try:
                success = alert_system.unsubscribe_email_from_sns(email)
                if success:
                    return LambdaFunctionService.response(200, {"message": f"{email} has been successfully unsubscribed from alerts."})
                else:
                    return LambdaFunctionService.response(404, {"error": f"No active subscription found for {email}."})

            except Exception as e:
                logger.error(f"Error unsubscribing {email}: {e}")
                return LambdaFunctionService.response(500, {"error": "Internal server error"})

        # DELETE /subscription
        elif http_method == "DELETE" and path == "/subscription":
            query_params = event.get("queryStringParameters", {})
            route = query_params.get("route")

            if not route:
                return LambdaFunctionService.response(400, {"error": "Missing required query parameter: route"})
            
            deleted = alert_system.delete_dynamodb_only_subscription(user_id, route)
            if deleted:
                return LambdaFunctionService.response(200, {"message": "Subscription removed successfully from DynamoDB."})
            else:
                return LambdaFunctionService.response(404, {"error": f"No subscription found for route {route}."})

    except Exception as e:
        logger.error(f"Error in lambda_handler: {e}")
        return LambdaFunctionService.response(500, {"error": str(e)})