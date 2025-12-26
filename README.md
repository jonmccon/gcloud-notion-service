# gcloud-notion-service

A secure, production-ready Google Cloud Function that syncs tasks from Google Tasks to Notion with comprehensive security features, error handling, and automatic cleanup capabilities.

**Authentication**: Uses OAuth 2.0 user credentials to access your personal Google Tasks (not service accounts).

## Features

### Security
- **OAuth 2.0 Authentication**: Secure user credential-based access to Google Tasks
- **Authentication**: Validates IAM/OIDC tokens for Cloud Function invocations
- **Rate Limiting**: Prevents abuse with configurable rate limits (100 requests/minute per client)
- **Input Sanitization**: All external input is sanitized to prevent injection attacks
- **Secret Management**: Supports Google Secret Manager with environment variable fallback
- **Structured Logging**: Cloud Logging integration for production monitoring
- **Automatic Token Refresh**: OAuth tokens are automatically refreshed when expired

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

### 1. Create OAuth 2.0 Credentials

The service uses OAuth 2.0 user credentials to access your personal Google Tasks.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) > APIs & Services > Credentials
2. Click "Create Credentials" > "OAuth 2.0 Client ID"
3. Select "Desktop app" as the application type
4. Give it a name (e.g., "Tasks-Notion Sync")
5. Download the credentials JSON file (save as `client_secrets.json`)

### 2. Run OAuth Setup

There are two ways to set up OAuth credentials, depending on your environment:

#### Option A: Full Setup with Secret Manager (Recommended for Production)

Run the setup script to authorize access and store credentials in Secret Manager:

```bash
# Install dependencies
pip install -r requirements.txt

# Run OAuth setup
python setup_oauth.py \
  --credentials-file client_secrets.json \
  --project-id YOUR_PROJECT_ID
```

This script will:
- Display a URL for you to visit in your browser (works in container environments)
- Prompt you to paste an authorization code after authorizing
- Store the OAuth tokens in Google Secret Manager as `GOOGLE_OAUTH_TOKEN`
- Store the client configuration as `GOOGLE_OAUTH_CLIENT_CONFIG`

**Important**: Sign in with the Google account that has the Tasks you want to sync.

#### Option B: Simple Token Generation (For Testing/Development)

If you just need to generate a token file for local testing:

```bash
# Run the simpler auth flow script
python auth-flow.py
```

This will:
- Display a URL for you to visit in your browser
- Prompt you to paste an authorization code
- Save credentials to `token.json` (not to Secret Manager)

**Note**: For production deployments, use Option A to store credentials in Secret Manager.

### 3. Grant Secret Access to Cloud Function Service Account

```bash
# Grant access to OAuth tokens
gcloud secrets add-iam-policy-binding GOOGLE_OAUTH_TOKEN \
  --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding GOOGLE_OAUTH_CLIENT_CONFIG \
  --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Grant access to Notion secrets
gcloud secrets add-iam-policy-binding NOTION_API_KEY \
  --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding NOTION_DB_ID \
  --member="serviceAccount:PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 4. Create Notion Secrets (if not already created)

```bash
# Create and set the Notion API key
echo -n "your_notion_api_key" | gcloud secrets create NOTION_API_KEY --data-file=-

# Create and set the Notion database ID
echo -n "your_notion_database_id" | gcloud secrets create NOTION_DB_ID --data-file=-
```

Alternatively, use environment variables for local testing (not recommended for production):

```bash
export NOTION_API_KEY="your_notion_api_key"
export NOTION_DB_ID="your_notion_database_id"
export GOOGLE_OAUTH_TOKEN='{"token": "...", "refresh_token": "...", ...}'
```

### 5. Deploy the Cloud Function

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

## OAuth Credential Maintenance

### Token Refresh
The Cloud Function automatically refreshes OAuth tokens when they expire. The refresh token is used to obtain new access tokens without requiring user interaction.

### Re-authorization
If you need to re-authorize (e.g., if you revoke access or switch accounts):

1. Run the setup script again:
   ```bash
   python setup_oauth.py \
     --credentials-file client_secrets.json \
     --project-id YOUR_PROJECT_ID
   ```

2. The new tokens will overwrite the old ones in Secret Manager

### Revoking Access
To revoke access to your Google Tasks:

1. Go to [Google Account Permissions](https://myaccount.google.com/permissions)
2. Find "Tasks-Notion Sync" (or your OAuth app name)
3. Click "Remove Access"

Note: After revoking, you'll need to re-run the setup script to restore functionality.

### Monitoring OAuth Issues
If you see authentication errors in logs:
- Check that `GOOGLE_OAUTH_TOKEN` secret exists in Secret Manager
- Verify the Cloud Function service account has `secretmanager.secretAccessor` role
- Check token expiration and refresh token validity
- Re-run setup if needed

## Security Considerations

1. **Never commit secrets** to version control
2. **Use Secret Manager** in production for all sensitive data (OAuth tokens, API keys)
3. **Restrict function access** with IAM policies
4. **Monitor rate limits** for unusual activity
5. **Review logs regularly** for security events
6. **Protect OAuth credentials**: Keep `client_secrets.json` secure and never commit it
7. **Use OAuth scopes carefully**: Only request necessary permissions (currently only Tasks access)
8. **Regularly review OAuth permissions** in your Google Account settings

## Troubleshooting

### Authentication Errors
- Verify OIDC token is present in request headers
- Check service account permissions
- Ensure `--allow-unauthenticated=false` is set

### OAuth Errors
- If you see "OAuth credentials not found": Run `setup_oauth.py` to configure authentication
- If tokens are expired and won't refresh: Re-run the setup script to re-authorize
- Check that service account has access to `GOOGLE_OAUTH_TOKEN` secret

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
