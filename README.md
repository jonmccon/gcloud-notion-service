# gcloud-notion-service

A secure, production-ready Google Cloud Function that syncs tasks from Google Tasks to Notion with comprehensive security features, error handling, and automatic cleanup capabilities.

## Features

### Security
- **Authentication**: Validates IAM/OIDC tokens for Cloud Function invocations
- **Rate Limiting**: Prevents abuse with configurable rate limits (100 requests/minute per client)
- **Input Sanitization**: All external input is sanitized to prevent injection attacks
- **Secret Management**: Supports Google Secret Manager with environment variable fallback
- **Structured Logging**: Cloud Logging integration for production monitoring

### Functionality
- **Unidirectional Sync**: Syncs tasks from Google Tasks to Notion as an input to your Notion-based workflow
- **Pagination**: Handles large task lists with API pagination
- **Idempotency**: Transaction IDs prevent duplicate processing
- **Retry Logic**: Exponential backoff for transient failures
- **Error Recovery**: Comprehensive error handling with detailed logging

### Data Quality
- **Incremental Updates**: Only updates tasks when changes are detected
- **Automatic Cleanup**: Completes old Google Tasks after 7 days in Notion
- **Task Type Detection**: Extracts and categorizes task types (e.g., "CODE-", "BUG-")

## Setup

### Prerequisites
- Google Cloud Project with:
  - Cloud Functions API enabled
  - Google Tasks API enabled
  - Notion integration with API key and database ID

### 1. Create Secrets (Recommended)

Using Google Secret Manager for production:

```bash
# Create and set the Notion API key
echo -n "your_notion_api_key" | gcloud secrets create NOTION_API_KEY --data-file=-

# Create and set the Notion database ID
echo -n "your_notion_database_id" | gcloud secrets create NOTION_DB_ID --data-file=-

# Grant access to the Cloud Function service account
gcloud secrets add-iam-policy-binding NOTION_API_KEY \
  --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding NOTION_DB_ID \
  --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud run services add-iam-policy-binding sync_tasks \
  --member="serviceAccount:SERVICE_ACCOUNT@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

Alternatively, use environment variables (not recommended for production):

```bash
export NOTION_API_KEY="your_notion_api_key"
export NOTION_DB_ID="your_notion_database_id"
```

### 2. Deploy the Cloud Function

```bash
gcloud functions deploy sync_tasks \
  --gen2 \
  --runtime python311 \
  --region us-west1 \
  --entry-point sync_tasks \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account=notion-bot-482105@notion-bot-482105.iam.gserviceaccount.com
```


**Note**: Both `NOTION_API_KEY` and `NOTION_DB_ID` are now retrieved from Secret Manager or environment variables automatically.

### 3. Schedule Automated Syncs

Create a Cloud Scheduler job for daily syncs:

```bash
gcloud scheduler jobs create http tasks-to-notion \
  --location=us-west1 \
  --schedule="0 6 * * *" \
  --uri=https://us-west1-notion-bot-482105.cloudfunctions.net/sync_tasks \
  --http-method=GET \
  --oidc-service-account-email=notion-bot-482105@notion-bot-482105.iam.gserviceaccount.com
```

For idempotent requests with transaction IDs:

```bash
gcloud scheduler jobs create http tasks-to-notion \
  --schedule="0 6 * * *" \
  --uri=FUNCTION_URL \
  --http-method=GET \
  --headers="X-Transaction-ID=scheduled-$(date +%Y%m%d)" \
  --oidc-service-account-email=notion-bot-482105@appspot.gserviceaccount.com
```

## Development

### Running Tests

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
python -m unittest test_main -v
```

### Local Testing

Set the environment to local mode to bypass authentication:

```bash
export ENVIRONMENT=local
export NOTION_API_KEY="your_test_api_key"
export NOTION_DB_ID="your_test_database_id"
```

### Code Quality

The codebase includes:
- Comprehensive unit tests (20+ test cases)
- Input validation and sanitization
- Error handling with structured logging
- Type hints for better code clarity

## Architecture

### Security Layers
1. **Authentication**: Verifies OIDC/IAP tokens
2. **Rate Limiting**: Per-client request throttling
3. **Input Sanitization**: Prevents XSS and injection attacks
4. **Secret Management**: Secure credential handling

### Sync Flow
1. Authenticate incoming request
2. Check for duplicate transaction (idempotency)
3. Fetch all Google Tasks with pagination
4. Sync Google Tasks → Notion:
   - Create new tasks in Notion
   - Update modified tasks
   - Complete old tasks in Google after 7 days in Notion (automatic cleanup)
5. Return detailed statistics

## API Response

```json
{
  "status": "ok",
  "created": 5,
  "updated": 3,
  "completed_in_google": 2,
  "total_seen": 150
}
```

## Notion Database Schema

Required properties in your Notion database:
- **Task name** (Title)
- **Status** (Status) - Values: "To do", "Completed"
- **Google Task ID** (Rich Text)
- **Imported at** (Date)
- **Updated at** (Date)
- **Due date** (Date)
- **Description** (Rich Text)
- **Link** (URL)
- **Effort level** (Select)
- **Task type** (Multi-select)

## Monitoring

View logs in Cloud Logging:

```bash
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=sync_tasks" \
  --limit 50 \
  --format json
```

## Security Considerations

1. **Never commit secrets** to version control
2. **Use Secret Manager** in production
3. **Restrict function access** with IAM policies
4. **Monitor rate limits** for unusual activity
5. **Review logs regularly** for security events

## Troubleshooting

### Authentication Errors
- Verify OIDC token is present in request headers
- Check service account permissions
- Ensure `--allow-unauthenticated=false` is set

### Rate Limiting
- Default: 100 requests per minute per client
- Adjust `MAX_REQUESTS_PER_WINDOW` and `RATE_LIMIT_WINDOW` as needed

### Pagination Issues
- Check Google Tasks API quotas
- Verify `maxResults` parameter (default: 100)

## Contributing

1. Write tests for new features
2. Ensure all tests pass: `python -m unittest test_main -v`
3. Follow existing code style and patterns
4. Update documentation for user-facing changes

## License

MIT
