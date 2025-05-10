#!/bin/bash

# Navigate to the server root
cd "$(dirname "$0")/.." || exit 1

STACK_NAME="Lambda-Stack"

echo "⚠️  Deleting CloudFormation stack: $STACK_NAME ..."
aws cloudformation delete-stack \
    --stack-name "$STACK_NAME"

echo " Deletion initiated. Monitor AWS CloudFormation Console for progress... ⏳"