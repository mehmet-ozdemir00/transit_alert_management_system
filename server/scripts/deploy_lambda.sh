#!/bin/bash

# Navigate to the server root
cd "$(dirname "$0")/.." || exit 1

echo "🚧 Cleaning previous build..."
rm -rf deployment/lambda_build
mkdir -p deployment/lambda_build

echo "📦 Installing dependencies directly into lambda_build/..."
python3 -m pip install --upgrade --no-cache-dir -r requirements.txt -t deployment/lambda_build/

echo "📁 Copying source files into lambda_build/..."
cp application/lambda_handler.py deployment/lambda_build/
cp application/transit_alert_service.py deployment/lambda_build/
cp application/transport_data_stream.py deployment/lambda_build/

echo "🗜️  Creating deployment ZIP package..."
rm -f deployment/lambda_deployment.zip
cd deployment/lambda_build || exit 1
zip -r ../lambda_deployment.zip .

cd ../..

echo "🚀 Uploading to AWS Lambda..."
aws lambda update-function-code \
    --function-name LambdaHandlerFunction \
    --zip-file fileb://deployment/lambda_deployment.zip

echo "Deployment complete! Your Lambda function now includes all dependencies at root level.. 🎉"