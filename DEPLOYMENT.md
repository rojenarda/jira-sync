# Deployment Guide

This guide provides step-by-step instructions for deploying the JIRA Automation system to AWS.

## Prerequisites

### AWS Setup
1. **AWS CLI installed and configured**:
   ```bash
   aws configure
   ```

2. **Required AWS permissions**:
   - CloudFormation: Full access
   - Lambda: Full access
   - DynamoDB: Full access
   - API Gateway: Full access
   - IAM: Role creation and policy attachment
   - CloudWatch: Logs and alarms

3. **AWS SAM CLI (optional but recommended)**:
   ```bash
   pip install aws-sam-cli
   ```

### JIRA Setup
1. **API tokens** for both JIRA instances
2. **Admin access** to configure webhooks
3. **Project keys** for the projects to sync

## Deployment Steps

### 1. Environment Configuration

Copy and configure the environment file:
```bash
cp .env.example .env
```

Edit `.env` with your specific values:
```env
# JIRA Instance 1
JIRA_1_BASE_URL=https://yourcompany.atlassian.net
JIRA_1_USERNAME=automation@yourcompany.com
JIRA_1_API_TOKEN=ATATT3xFfGF0wXX...
JIRA_1_PROJECT_KEY=PROJ1

# JIRA Instance 2
JIRA_2_BASE_URL=https://partner.atlassian.net
JIRA_2_USERNAME=sync@partner.com
JIRA_2_API_TOKEN=ATATT3xFfGF0wYY...
JIRA_2_PROJECT_KEY=PROJ2

# Security
WEBHOOK_SECRET=your-super-secure-secret-here-32-chars
```

### 2. Deploy Infrastructure

Load environment variables and deploy:
```bash
source .env
cd infrastructure
./deploy.sh prod
```

The deployment will:
- Create DynamoDB table for sync state
- Deploy Lambda functions
- Set up API Gateway endpoints
- Configure CloudWatch logging and alarms
- Output webhook URLs and API keys

### 3. Configure JIRA Webhooks

After deployment, you'll receive webhook URLs. Configure them in both JIRA instances.

#### For each JIRA instance:

1. **Go to System Settings**:
   - JIRA Cloud: Settings → System → Webhooks
   - JIRA Server: Administration → System → Webhooks

2. **Create webhook**:
   - **Name**: `JIRA Sync Webhook`
   - **URL**: Use the appropriate URL from deployment output
     - JIRA 1: `https://api-id.execute-api.region.amazonaws.com/prod/webhook/jira1`
     - JIRA 2: `https://api-id.execute-api.region.amazonaws.com/prod/webhook/jira2`
   - **Secret**: Use the same `WEBHOOK_SECRET` from your `.env`

3. **Configure events**:
   - ✅ Issue created
   - ✅ Issue updated
   - ✅ Issue deleted (optional)

4. **JQL Filter** (optional):
   ```
   project = "YOUR_PROJECT_KEY"
   ```

### 4. Test the Deployment

#### Test webhook connectivity:
```bash
python scripts/test-webhook.py \
  "https://your-webhook-url/webhook/jira1" \
  "your-webhook-secret"
```

#### Test health endpoint:
```bash
curl https://your-management-api-url/health
```

#### Check sync status:
```bash
python scripts/check-sync-status.py summary
```

## Environment-Specific Deployments

### Development Environment
```bash
./deploy.sh dev
```

### Staging Environment
```bash
./deploy.sh staging
```

### Production Environment
```bash
./deploy.sh prod
```

## Post-Deployment Configuration

### 1. Initial Sync

Trigger a full sync to synchronize existing issues:
```bash
curl -X POST https://your-management-api-url/manual-sync \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"sync_type": "full_sync"}'
```

### 2. Monitor Deployment

#### Check CloudWatch logs:
```bash
aws logs tail /aws/lambda/prod-jira-webhook-handler --follow
```

#### Monitor DynamoDB:
```bash
aws dynamodb scan --table-name prod-jira-sync-state
```

### 3. Set Up Monitoring

#### CloudWatch Dashboard (optional):
Create a custom dashboard to monitor:
- Lambda invocation counts
- Error rates
- DynamoDB read/write capacity
- Sync success/failure rates

#### SNS Alerts (optional):
Configure SNS topics for CloudWatch alarms to get notifications for:
- High error rates
- Sync failures
- Long execution times

## Troubleshooting Deployment

### Common Issues

#### 1. CloudFormation Stack Creation Failed
```bash
# Check stack events
aws cloudformation describe-stack-events --stack-name jira-sync-prod

# Common fixes:
# - Verify AWS permissions
# - Check parameter values
# - Ensure unique stack names
```

#### 2. Lambda Function Timeout
```bash
# Increase timeout in cloudformation.yaml:
Globals:
  Function:
    Timeout: 900  # 15 minutes
```

#### 3. DynamoDB Permission Errors
```bash
# Verify IAM role has DynamoDB permissions
aws iam list-attached-role-policies --role-name jira-sync-lambda-role
```

#### 4. API Gateway Throttling
```bash
# Check usage plans and increase limits if needed
aws apigateway get-usage-plans
```

### Deployment Logs

Check deployment logs:
```bash
# CloudFormation events
aws cloudformation describe-stack-events --stack-name jira-sync-prod

# Lambda logs
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/prod-jira
```

## Rollback Procedure

### Quick Rollback
```bash
# Delete the CloudFormation stack
aws cloudformation delete-stack --stack-name jira-sync-prod

# Wait for completion
aws cloudformation wait stack-delete-complete --stack-name jira-sync-prod
```

### Rollback to Previous Version
```bash
# If using versioned deployments
aws cloudformation deploy \
  --template-file infrastructure/cloudformation.yaml \
  --stack-name jira-sync-prod \
  --parameter-overrides Version=previous-version
```

## Security Considerations

### 1. Secrets Management
For production, consider using AWS Secrets Manager:
```yaml
# In CloudFormation template
JiraApiTokenSecret:
  Type: AWS::SecretsManager::Secret
  Properties:
    SecretString: !Sub |
      {
        "jira1_token": "${Jira1ApiToken}",
        "jira2_token": "${Jira2ApiToken}"
      }
```

### 2. Network Security
- API Gateway endpoints are public but secured with signature verification
- Consider VPC endpoints for DynamoDB access
- Use WAF for additional API protection

### 3. IAM Roles
- Lambda roles follow least privilege principle
- Regular audit of permissions
- Use AWS Config for compliance monitoring

## Maintenance

### Regular Tasks

#### Weekly:
- Check CloudWatch alarms
- Review error logs
- Monitor sync success rates

#### Monthly:
- Review DynamoDB metrics and costs
- Update dependencies if needed
- Audit IAM permissions

#### Quarterly:
- Review and update documentation
- Performance optimization
- Security audit

### Updates

#### Code Updates:
```bash
# Update code and redeploy
git pull
source .env
cd infrastructure
./deploy.sh prod
```

#### Infrastructure Updates:
```bash
# Update CloudFormation template
aws cloudformation deploy \
  --template-file infrastructure/cloudformation.yaml \
  --stack-name jira-sync-prod \
  --capabilities CAPABILITY_IAM
```

## Cost Optimization

### Monitoring Costs
- Use AWS Cost Explorer to track expenses
- Set up billing alerts
- Monitor DynamoDB and Lambda usage

### Optimization Tips
- Tune Lambda memory allocation
- Optimize DynamoDB queries
- Set appropriate log retention periods
- Use reserved capacity for predictable workloads

## Support and Maintenance

### Getting Help
1. Check CloudWatch logs for detailed error information
2. Use the diagnostic scripts in the `scripts/` directory
3. Review DynamoDB sync state records
4. Monitor CloudWatch alarms

### Emergency Contacts
- Document emergency escalation procedures
- Maintain runbook for common issues
- Keep backup contacts for JIRA administration
