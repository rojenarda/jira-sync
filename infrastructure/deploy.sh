#!/bin/bash

# Deployment script for JIRA Sync System
set -e

# Configuration
ENVIRONMENT=${1:-prod}
STACK_NAME="jira-sync-${ENVIRONMENT}"
REGION=${AWS_DEFAULT_REGION:-us-east-1}

echo "Deploying JIRA Sync System to environment: ${ENVIRONMENT}"
echo "Stack name: ${STACK_NAME}"
echo "Region: ${REGION}"

# Check if required parameters are set
if [ -z "$JIRA_1_BASE_URL" ] || [ -z "$JIRA_1_USERNAME" ] || [ -z "$JIRA_1_API_TOKEN" ] || [ -z "$JIRA_1_PROJECT_KEY" ]; then
    echo "Error: JIRA instance 1 configuration is incomplete"
    echo "Required environment variables:"
    echo "  JIRA_1_BASE_URL"
    echo "  JIRA_1_USERNAME"
    echo "  JIRA_1_API_TOKEN"
    echo "  JIRA_1_PROJECT_KEY"
    exit 1
fi

if [ -z "$JIRA_2_BASE_URL" ] || [ -z "$JIRA_2_USERNAME" ] || [ -z "$JIRA_2_API_TOKEN" ] || [ -z "$JIRA_2_PROJECT_KEY" ]; then
    echo "Error: JIRA instance 2 configuration is incomplete"
    echo "Required environment variables:"
    echo "  JIRA_2_BASE_URL"
    echo "  JIRA_2_USERNAME"
    echo "  JIRA_2_API_TOKEN"
    echo "  JIRA_2_PROJECT_KEY"
    exit 1
fi

if [ -z "$WEBHOOK_SECRET" ]; then
    echo "Error: WEBHOOK_SECRET environment variable is required"
    exit 1
fi

# Create deployment package
echo "Creating deployment package..."
cd ..
pip install -r requirements.txt -t package/
cp -r src/ package/
cp main.py package/

# Package for Lambda
cd package
zip -r ../jira-sync-deployment.zip .
cd ..

# Deploy CloudFormation stack
echo "Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file infrastructure/cloudformation.yaml \
    --stack-name ${STACK_NAME} \
    --parameter-overrides \
        Environment=${ENVIRONMENT} \
        Jira1BaseUrl="${JIRA_1_BASE_URL}" \
        Jira1Username="${JIRA_1_USERNAME}" \
        Jira1ApiToken="${JIRA_1_API_TOKEN}" \
        Jira1ProjectKey="${JIRA_1_PROJECT_KEY}" \
        Jira2BaseUrl="${JIRA_2_BASE_URL}" \
        Jira2Username="${JIRA_2_USERNAME}" \
        Jira2ApiToken="${JIRA_2_API_TOKEN}" \
        Jira2ProjectKey="${JIRA_2_PROJECT_KEY}" \
        WebhookSecret="${WEBHOOK_SECRET}" \
    --capabilities CAPABILITY_IAM \
    --region ${REGION}

# Get outputs
echo "Getting deployment outputs..."
WEBHOOK_API_URL=$(aws cloudformation describe-stacks \
    --stack-name ${STACK_NAME} \
    --region ${REGION} \
    --query 'Stacks[0].Outputs[?OutputKey==`WebhookApiUrl`].OutputValue' \
    --output text)

MANAGEMENT_API_URL=$(aws cloudformation describe-stacks \
    --stack-name ${STACK_NAME} \
    --region ${REGION} \
    --query 'Stacks[0].Outputs[?OutputKey==`ManagementApiUrl`].OutputValue' \
    --output text)

JIRA_1_WEBHOOK_URL=$(aws cloudformation describe-stacks \
    --stack-name ${STACK_NAME} \
    --region ${REGION} \
    --query 'Stacks[0].Outputs[?OutputKey==`Jira1WebhookUrl`].OutputValue' \
    --output text)

JIRA_2_WEBHOOK_URL=$(aws cloudformation describe-stacks \
    --stack-name ${STACK_NAME} \
    --region ${REGION} \
    --query 'Stacks[0].Outputs[?OutputKey==`Jira2WebhookUrl`].OutputValue' \
    --output text)

API_KEY_ID=$(aws cloudformation describe-stacks \
    --stack-name ${STACK_NAME} \
    --region ${REGION} \
    --query 'Stacks[0].Outputs[?OutputKey==`ManagementApiKeyId`].OutputValue' \
    --output text)

# Get the actual API key value
API_KEY_VALUE=$(aws apigateway get-api-key \
    --api-key ${API_KEY_ID} \
    --include-value \
    --region ${REGION} \
    --query 'value' \
    --output text)

# Clean up
rm -rf package/
rm jira-sync-deployment.zip

echo ""
echo "======================================"
echo "Deployment completed successfully!"
echo "======================================"
echo ""
echo "Webhook URLs (configure these in your JIRA instances):"
echo "  JIRA Instance 1: ${JIRA_1_WEBHOOK_URL}"
echo "  JIRA Instance 2: ${JIRA_2_WEBHOOK_URL}"
echo ""
echo "Management API:"
echo "  URL: ${MANAGEMENT_API_URL}"
echo "  API Key: ${API_KEY_VALUE}"
echo ""
echo "Health Check:"
echo "  ${MANAGEMENT_API_URL}/health"
echo ""
echo "Next steps:"
echo "1. Configure webhooks in both JIRA instances using the URLs above"
echo "2. Set the webhook secret to: ${WEBHOOK_SECRET}"
echo "3. Configure webhook events: issue created, updated, deleted"
echo "4. Test the system using the health check endpoint"
echo ""
