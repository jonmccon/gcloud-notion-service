# Notion API Integration Documentation

## Overview

This document provides detailed information about the Notion API integration used in the `gcloud-notion-service`. It serves as a reference for the API payload structure, required headers, and Cloud Scheduler configuration.

**Revision:** gcloud-notion-service-00007-mdm  
**Notion API Version:** 2022-06-28  
**Last Updated:** 2025-12-27

## Notion API Endpoints Used

### 1. Database Query API
**Endpoint:** `POST /v1/databases/{database_id}/query`  
**Documentation:** https://developers.notion.com/reference/post-database-query

**Purpose:** Search for existing tasks in Notion database by Google Task ID

**Request Headers:**
```json
{
  "Authorization": "Bearer {notion_api_key}",
  "Notion-Version": "2022-06-28",
  "Content-Type": "application/json"
}
```

**Request Body:**
```json
{
  "filter": {
    "property": "Google Task ID",
    "rich_text": {
      "equals": "{google_task_id}"
    }
  }
}
```

**Implementation:** `find_notion_task()` function in `main.py`

### 2. Create Page API
**Endpoint:** `POST /v1/pages`  
**Documentation:** https://developers.notion.com/reference/post-page

**Purpose:** Create new task pages in the Notion database

**Request Headers:**
```json
{
  "Authorization": "Bearer {notion_api_key}",
  "Notion-Version": "2022-06-28",
  "Content-Type": "application/json"
}
```

**Request Body Structure:**
```json
{
  "parent": {
    "database_id": "{notion_database_id}"
  },
  "properties": {
    "Task name": {
      "title": [
        {
          "text": {
            "content": "Task title here"
          }
        }
      ]
    },
    "Status": {
      "status": {
        "name": "To do"
      }
    },
    "Google Task ID": {
      "rich_text": [
        {
          "text": {
            "content": "google_task_id_here"
          }
        }
      ]
    },
    "Imported at": {
      "date": {
        "start": "2025-12-27T07:00:00.000Z"
      }
    },
    "Updated at": {
      "date": {
        "start": "2025-12-27T07:00:00.000Z"
      }
    },
    "Due date": {
      "date": {
        "start": "2025-12-31T00:00:00.000Z"
      }
    },
    "Description": {
      "rich_text": [
        {
          "text": {
            "content": "Task description/notes"
          }
        }
      ]
    },
    "Link": {
      "url": "https://tasks.google.com/..."
    },
    "Effort level": {
      "select": {
        "name": "Medium"
      }
    },
    "Task type": {
      "multi_select": [
        {
          "name": "CODE"
        }
      ]
    }
  }
}
```

**Implementation:** `create_notion_task()` function in `main.py`

**Required Properties:**
- `Task name` (title) - Required
- `Status` (status) - Required
- `Google Task ID` (rich_text) - Required for tracking
- `Imported at` (date) - Required for cleanup logic

**Optional Properties:**
- `Updated at` (date) - Only if task has update timestamp
- `Due date` (date) - Only if task has due date
- `Description` (rich_text) - Only if task has notes
- `Link` (url) - Only if task has selfLink
- `Effort level` (select) - Defaults to "Medium"
- `Task type` (multi_select) - Only if task title contains type prefix (e.g., "CODE-")

### 3. Update Page API
**Endpoint:** `PATCH /v1/pages/{page_id}`  
**Documentation:** https://developers.notion.com/reference/patch-page

**Purpose:** Update existing task properties when tasks change in Google Tasks

**Request Headers:**
```json
{
  "Authorization": "Bearer {notion_api_key}",
  "Notion-Version": "2022-06-28",
  "Content-Type": "application/json"
}
```

**Request Body Structure:**
```json
{
  "properties": {
    "Task name": {
      "title": [
        {
          "text": {
            "content": "Updated task title"
          }
        }
      ]
    },
    "Updated at": {
      "date": {
        "start": "2025-12-27T08:00:00.000Z"
      }
    },
    "Due date": {
      "date": {
        "start": "2025-12-31T00:00:00.000Z"
      }
    },
    "Description": {
      "rich_text": [
        {
          "text": {
            "content": "Updated description"
          }
        }
      ]
    }
  }
}
```

**Implementation:** `update_notion_task()` function in `main.py`

## Notion-Version Header

**Header Name:** `Notion-Version`  
**Required:** Yes (for all Notion API requests)  
**Format:** YYYY-MM-DD  
**Current Value:** `2022-06-28`

The `Notion-Version` header is **required** by the Notion API for all requests. It ensures API stability by locking the request to a specific version of the API schema.

### Version Selection Rationale
- **2022-06-28** is a stable, well-documented version
- Supports all property types used in this service (title, rich_text, date, url, select, multi_select, status)
- Widely used and tested in production environments

### Version Documentation
https://developers.notion.com/reference/versioning

### Implementation
The header is automatically added to all Notion API requests via the `notion_headers()` function in `main.py`:

```python
def notion_headers():
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,  # "2022-06-28"
        "Content-Type": "application/json",
    }
```

## Property Types and Data Types

All property values strictly follow the Notion API property value object schema:  
https://developers.notion.com/reference/property-value-object

### Property Type Reference

| Property Name | Notion Type | Data Type | Required | Description |
|--------------|-------------|-----------|----------|-------------|
| Task name | title | array of rich text | Yes | Task title/name |
| Status | status | object with name | Yes | Task status (To do/Completed) |
| Google Task ID | rich_text | array of rich text | Yes | Unique identifier from Google Tasks |
| Imported at | date | object with ISO 8601 start | Yes | When task was imported to Notion |
| Updated at | date | object with ISO 8601 start | No | Last update timestamp from Google |
| Due date | date | object with ISO 8601 start | No | Task due date |
| Description | rich_text | array of rich text | No | Task notes/description |
| Link | url | string (URL) | No | Link to Google Task |
| Effort level | select | object with name | No | Effort estimation (default: Medium) |
| Task type | multi_select | array of objects with name | No | Task type prefix (CODE, BUG, etc.) |

### Data Validation

All input data is sanitized before being sent to Notion:

1. **String Sanitization** (`sanitize_string()` function):
   - Removes control characters and null bytes
   - Strips HTML tags to prevent injection
   - Truncates to maximum length (2000 chars)
   - Removes leading/trailing whitespace

2. **Date Format Validation**:
   - All dates are in ISO 8601 format with timezone
   - Format: `YYYY-MM-DDTHH:MM:SS.sssZ`
   - Generated using Python's `.isoformat()` method

3. **URL Validation**:
   - URLs are passed through from Google Tasks API
   - Expected to be valid HTTPS URLs

## Cloud Scheduler Configuration

The Cloud Function can be triggered by Cloud Scheduler for automated, scheduled syncs.

### Basic Scheduler Configuration

**Purpose:** Trigger daily task sync from Google Tasks to Notion

**Command:**
```bash
gcloud scheduler jobs create http tasks-to-notion \
  --location=us-west1 \
  --schedule="0 6 * * *" \
  --uri=https://us-west1-notion-bot-482105.cloudfunctions.net/sync_tasks \
  --http-method=GET \
  --oidc-service-account-email=notion-bot-482105@notion-bot-482105.iam.gserviceaccount.com
```

**Schedule:** `0 6 * * *` (Daily at 6:00 AM UTC)  
**HTTP Method:** GET  
**Authentication:** OIDC token (automatically added by Cloud Scheduler)

### Scheduler with Idempotency

**Purpose:** Prevent duplicate processing with transaction IDs

**Command:**
```bash
gcloud scheduler jobs create http tasks-to-notion \
  --location=us-west1 \
  --schedule="0 6 * * *" \
  --uri=https://us-west1-notion-bot-482105.cloudfunctions.net/sync_tasks \
  --http-method=GET \
  --headers="X-Transaction-ID=scheduled-$(date +%Y%m%d)" \
  --oidc-service-account-email=notion-bot-482105@notion-bot-482105.iam.gserviceaccount.com
```

### Scheduler Payload Structure

**Method:** GET (no request body required)

**Headers sent by Cloud Scheduler:**
- `Authorization: Bearer {OIDC_TOKEN}` - Automatically added for authentication
- `X-Transaction-ID: {unique_id}` - Optional, for idempotency
- Standard HTTP headers (User-Agent, Content-Type, etc.)

**What the Cloud Function expects:**
1. **OIDC Token** (via `Authorization` header): Used for authentication via `verify_cloud_function_auth()`
2. **Transaction ID** (optional via `X-Transaction-ID` header): Used for idempotency to prevent duplicate processing

**No additional payload data is required** - the Cloud Function retrieves all necessary configuration from:
- Secret Manager: `NOTION_API_KEY`, `NOTION_DB_ID`, `GOOGLE_OAUTH_TOKEN`
- The function autonomously fetches all tasks from Google Tasks and syncs to Notion

### Scheduler Job Verification

To verify the scheduler job configuration:
```bash
# List all scheduler jobs
gcloud scheduler jobs list --location=us-west1

# Describe a specific job
gcloud scheduler jobs describe tasks-to-notion --location=us-west1

# Test the job manually
gcloud scheduler jobs run tasks-to-notion --location=us-west1
```

## Security Considerations

### Authentication & Authorization
1. **Notion API Key**: Stored in Google Secret Manager (`NOTION_API_KEY`)
2. **OIDC Tokens**: Cloud Scheduler automatically includes OIDC tokens for Cloud Function authentication
3. **Service Account**: The Cloud Scheduler service account must have:
   - `cloudfunctions.functions.invoke` permission on the Cloud Function
   - `secretmanager.secretAccessor` role on secrets (granted to Cloud Function service account)

### Input Sanitization
All external input is sanitized before constructing API payloads:
- Task titles: HTML tags removed, control characters stripped
- Task descriptions: Same sanitization as titles
- Maximum length enforced (2000 characters)

### Rate Limiting
- Client-based rate limiting: 100 requests per minute per client
- Implemented in `rate_limit()` function

### Retry Logic
- Automatic retry with exponential backoff for transient failures
- Maximum 3 attempts per API call
- Initial delay: 1 second, doubles on each retry

## Testing and Validation

### Unit Tests
The following test cases validate the Notion API integration:

1. **Header Validation** (`test_notion_headers`):
   - Ensures `Notion-Version` header is present
   - Validates header format and value

2. **Payload Validation** (`test_create_notion_task`):
   - Validates payload structure for page creation
   - Ensures all required properties are included

3. **Property Type Validation** (`test_notion_task_properties`):
   - Validates each property type matches Notion schema
   - Tests optional vs required properties

Run tests with:
```bash
python -m unittest test_main -v
```

### Manual Testing
Test the Cloud Function locally:
```bash
export ENVIRONMENT=local
export NOTION_API_KEY="your_test_api_key"
export NOTION_DB_ID="your_test_database_id"
export GOOGLE_OAUTH_TOKEN='{"token": "...", "refresh_token": "...", ...}'

# Run the function (requires Flask or similar testing framework)
```

## Troubleshooting

### Common Issues

**1. Missing Notion-Version Header**
- **Symptom:** API returns 400 Bad Request
- **Cause:** Missing or invalid `Notion-Version` header
- **Solution:** Verify `NOTION_VERSION` constant is set to "2022-06-28"

**2. Invalid Property Type**
- **Symptom:** API returns 400 with "validation_error"
- **Cause:** Property value doesn't match expected type
- **Solution:** Verify property structure matches Notion API schema

**3. Database Not Found**
- **Symptom:** API returns 404
- **Cause:** Invalid `NOTION_DB_ID` or insufficient permissions
- **Solution:** Verify database ID and API key permissions

**4. Rate Limiting**
- **Symptom:** 429 Too Many Requests
- **Cause:** Exceeding Notion API rate limits
- **Solution:** Implement exponential backoff (already implemented)

## References

1. **Notion API Documentation**: https://developers.notion.com/reference/intro
2. **Notion API Versioning**: https://developers.notion.com/reference/versioning
3. **Create Page API**: https://developers.notion.com/reference/post-page
4. **Update Page API**: https://developers.notion.com/reference/patch-page
5. **Database Query API**: https://developers.notion.com/reference/post-database-query
6. **Property Value Object**: https://developers.notion.com/reference/property-value-object
7. **Google Cloud Scheduler**: https://cloud.google.com/scheduler/docs
8. **OIDC Authentication**: https://cloud.google.com/scheduler/docs/http-target-auth

## Changelog

### 2025-12-27 (gcloud-notion-service-00007-mdm)
- Added comprehensive API integration documentation
- Documented all Notion API endpoints and payload structures
- Added Cloud Scheduler configuration details
- Verified `Notion-Version` header in all requests
- Added inline code documentation referencing Notion API docs
