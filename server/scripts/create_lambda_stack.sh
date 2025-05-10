#!/bin/bash

# Navigate to the server root
cd "$(dirname "$0")/.." || exit 1

STACK_NAME="Lambda-Stack"
TEMPLATE_PATH="cloudformation/lambda_function.yaml"
S3_BUCKET="transit-alert-management-system-artifacts"
S3_KEY="lambda_deployment.zip"

echo "🚧 Cleaning and rebuilding deployment package..."
rm -rf deployment/lambda_build
mkdir -p deployment/lambda_build

python3 -m pip install --upgrade --no-cache-dir -r requirements.txt -t deployment/lambda_build/
cp application/lambda_handler.py deployment/lambda_build/
cp application/transit_alert_service.py deployment/lambda_build/
cp application/transport_data_stream.py deployment/lambda_build/

echo "🗜️  Creating ZIP file..."
rm -f deployment/lambda_deployment.zip
cd deployment/lambda_build || exit 1
zip -r ../lambda_deployment.zip .
cd ../..

echo " ☁️  Uploading lambda_deployment.zip to S3..."
aws s3 cp deployment/lambda_deployment.zip "s3://$S3_BUCKET/$S3_KEY"

echo " 📦 Creating CloudFormation stack: $STACK_NAME ..."
aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body "file://$TEMPLATE_PATH" \
    --capabilities CAPABILITY_IAM

echo " Stack creation initiated. Monitor progress in AWS CloudFormation Console... ⏳"