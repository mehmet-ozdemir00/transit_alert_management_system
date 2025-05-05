#!/bin/bash

# Navigate to the server root
cd "$(dirname "$0")/.." || exit 1

STACK_NAME="DynamoDB-Stack"
TEMPLATE_PATH="cloudformation/dynamodb_table.yaml"

echo "📦 Creating CloudFormation stack: $STACK_NAME ..."
aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body "file://$TEMPLATE_PATH"

echo "Stack creation initiated. Check AWS CloudFormation Console for status... ⏳"