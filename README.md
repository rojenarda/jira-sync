# JIRA Automation - Bidirectional Sync System

A production-grade system for bidirectional synchronization between two JIRA instances, deployed on AWS Lambda with DynamoDB for state management.

## Features

- **Bidirectional Sync**: Automatically syncs issues between two JIRA instances
- **Real-time Updates**: Webhook-driven sync for immediate updates
- **Conflict Resolution**: Detects and handles conflicts when both instances are updated simultaneously
- **Serverless Architecture**: AWS Lambda and DynamoDB for scalability and cost-efficiency
- **Type Safe**: Full type annotations and validation using Pydantic

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   JIRA Instance │         │   AWS Lambda     │         │   JIRA Instance │
│        1        │◄────────┤   Sync Engine    ├────────►│        2        │
│                 │         │                  │         │                 │
└─────────────────┘         └──────────────────┘         └─────────────────┘
         │                           │                           │
         │                           │                           │
         ▼                           ▼                           ▼
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Webhooks      │         │   DynamoDB       │         │   Webhooks      │
│                 │         │   (Sync State)   │         │                 │
└─────────────────┘         └──────────────────┘         └─────────────────┘
```

## Components

- **Sync Engine**: Core logic for bidirectional synchronization
- **JIRA Client**: API wrapper for JIRA REST operations
- **Storage Layer**: DynamoDB integration for sync state tracking
- **Lambda Handlers**: AWS Lambda functions for webhooks and scheduled tasks
- **Infrastructure**: CloudFormation templates for AWS deployment

## Quick Start

### 1. Environment Setup

Copy the environment template:
```bash
cp .env.example .env
```

Configure your JIRA instances and credentials in `.env`:
```env
JIRA_1_BASE_URL=https://your-first-jira-instance.atlassian.net
JIRA_1_USERNAME=your-username@company.com
JIRA_1_API_TOKEN=your-api-token-here
JIRA_1_PROJECT_KEY=PROJ1

JIRA_2_BASE_URL=https://your-second-jira-instance.atlassian.net
JIRA_2_USERNAME=your-username@company.com
JIRA_2_API_TOKEN=your-api-token-here
JIRA_2_PROJECT_KEY=PROJ2

WEBHOOK_SECRET=your-secure-webhook-secret-here

# Optional: Status transition configuration
SYNC_STATUS_TRANSITIONS=true
SYNC_ASSIGNEE=false
```

### 2. Deploy to AWS

```bash
# Load environment variables
source .env

# Deploy the infrastructure
cd infrastructure
./deploy.sh prod
```

### 3. Configure JIRA Webhooks

After deployment, configure webhooks in both JIRA instances:

1. Go to **System Settings** > **Webhooks**
2. Create a new webhook with:
   - **URL**: Use the webhook URLs from deployment output
   - **Events**: `Issue Created`, `Issue Updated`, `Issue Deleted`
   - **Secret**: Use the same `WEBHOOK_SECRET` from your `.env`

### 4. Test the System

Test the health endpoint:
```bash
curl https://your-management-api-url/health
```

## JIRA Configuration

### API Token Generation

1. Go to **Account Settings** > **Security** > **API tokens**
2. Create a new token
3. Use this token in your environment configuration

### Required Permissions

The JIRA user needs:
- **Browse Projects** permission
- **Create Issues** permission
- **Edit Issues** permission
- **Transition Issues** permission (if syncing status changes)

### Webhook Events

Configure these webhook events:
- `jira:issue_created`
- `jira:issue_updated`
- `jira:issue_deleted` (optional)

## Sync Behavior

### New Issues
When a new issue is created in either instance, it's automatically replicated to the other instance with:
- All standard fields (summary, description, priority, etc.)
- Labels and components
- Custom fields (where possible)
- Assignee (if user exists in target instance)

### Updated Issues
When an issue is updated, changes are synchronized including:
- Field modifications
- **Status transitions** (using JIRA transition API)
- Priority, labels, components, fix versions
- Custom fields
- Assignee (optional, configurable)
- Comment additions (optional)

### Conflict Resolution
When both instances have updates since the last sync:
1. The sync is marked as **conflicted**
2. Manual resolution is required via the management API
3. You can choose which direction to apply the changes

## API Endpoints

### Webhook Endpoints
- `POST /webhook/jira1` - Webhook for JIRA instance 1
- `POST /webhook/jira2` - Webhook for JIRA instance 2

### Management Endpoints (require API key)
- `GET /health` - System health check
- `POST /manual-sync` - Trigger manual sync

### Manual Sync Example
```bash
curl -X POST https://your-management-api-url/manual-sync \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "issue_key": "PROJ1-123",
    "source_instance": 1
  }'
```

### Conflict Resolution Example
```bash
curl -X POST https://your-management-api-url/manual-sync \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "sync_id": "PROJ1-123#PROJ2-456",
    "resolve_conflict": true,
    "resolution_direction": "jira_1_to_2"
  }'
```

## Monitoring

### CloudWatch Logs
- `/aws/lambda/prod-jira-webhook-handler`
- `/aws/lambda/prod-jira-scheduled-sync`
- `/aws/lambda/prod-jira-manual-sync`
- `/aws/lambda/prod-jira-health-check`

### CloudWatch Alarms
- High error rate alerts
- Long execution time alerts
- Sync failure notifications

### DynamoDB Metrics
Monitor the sync state table for:
- Item count growth
- Read/write capacity usage
- Failed sync records

## Scheduled Operations

### Retry Failed Syncs
Runs every 15 minutes to retry failed synchronizations.

### Full Sync
Runs daily at 2 AM UTC to ensure all issues are in sync.

## Troubleshooting

### Common Issues

1. **Authentication Failures**
   - Verify API tokens are valid
   - Check user permissions in JIRA

2. **Webhook Not Triggered**
   - Verify webhook URL is correct
   - Check webhook secret matches
   - Ensure JIRA can reach the API Gateway

3. **Sync Conflicts**
   - Use conflict resolution API
   - Check issue modification timestamps
   - Review sync logs in CloudWatch

### Debugging

Enable detailed logging by checking CloudWatch logs for each Lambda function.

## Development

### Local Development

1. Install UV for project management:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Install dependencies:
```bash
uv sync
```

3. Set up pre-commit hooks:
```bash
pre-commit install
```

---

You can check the linting of the project with:
```bash
ruff check src/
```



### Testing

Run the main module for basic validation:
```bash
python main.py
```

## Security Considerations

- API tokens are stored as CloudFormation parameters
- Webhook endpoints use HMAC-SHA256 signature verification
- Management API requires API key authentication
- All communication uses HTTPS
- IAM roles follow least privilege principle

## Cost Optimization

- DynamoDB uses on-demand billing
- Lambda functions are optimized for cold start performance
- CloudWatch logs have appropriate retention periods
- No persistent infrastructure costs

## Status Transitions

The system handles JIRA status changes using the **transitions API**, which respects your workflow rules.

### How It Works
1. **Detects status changes** via webhooks
2. **Finds valid transition** to target status
3. **Executes transition** using JIRA API
4. **Logs success/failure** for monitoring

### Testing Transitions
```bash
# Test available transitions for an issue
python scripts/test-transitions.py PROJ-123 1

# Test transition to specific status
python scripts/test-transitions.py PROJ-123 1 "In Progress"
```

### Configuration
```env
# Enable/disable status synchronization
SYNC_STATUS_TRANSITIONS=true

# Enable/disable assignee synchronization
SYNC_ASSIGNEE=false
```

### Workflow Considerations
- **Any-to-any transitions**: Assumes any status can transition to any other status
- **Workflow validation**: JIRA will reject invalid transitions
- **Failed transitions**: Logged as warnings, don't fail the entire sync
- **Transition permissions**: Ensure API user has transition permissions

## Customization

### Field Mapping
Modify `src/jira_client.py` to customize field mapping between instances.

### Sync Rules
Update `src/lambda_handlers.py` `should_process_event()` to customize which events trigger syncs.

### Conflict Resolution
Extend `src/sync_engine.py` to implement custom conflict resolution strategies.

## Support

For issues and questions:
1. Check CloudWatch logs for detailed error information
2. Review the sync state in DynamoDB
3. Use the health check endpoint to verify system status
4. Monitor CloudWatch alarms for system health

## License

This project is licensed under the MIT License.
