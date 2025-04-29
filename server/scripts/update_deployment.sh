#!/bin/bash

# Correct paths
cp application/handlers/lambda_handler.py deployment/
cp application/services/transit_alert_service.py deployment/
cp application/data_services/transport_data_stream.py deployment/

# Step 2: Zip them inside deployment folder
cd deployment

# (Optional) Remove old zip first to avoid conflicts
rm -f lambda_deployment.zip

# Zip the updated .py files
zip -r lambda_deployment.zip lambda_handler.py transit_alert_service.py transport_data_stream.py

# Step 3: Update AWS Lambda function
aws lambda update-function-code \
    --function-name LambdaHandlerFunction \
    --zip-file fileb://lambda_deployment.zip

# Step 4: Return back to server folder
cd ..