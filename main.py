import os
import re
import requests
import logging
import time
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from functools import wraps

from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.cloud import logging as cloud_logging
from google.cloud import secretmanager

# ----------------------------
# Configuration & Setup
# ----------------------------

# Initialize Cloud Logging
try:
    logging_client = cloud_logging.Client()
    logging_client.setup_logging()
except Exception:
    # Fallback to standard logging if Cloud Logging is not available
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

logger = logging.getLogger(__name__)

# ----------------------------
# Constants
# ----------------------------

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

TASK_TYPE_REGEX = re.compile(r'^([A-Za-z]{3,5})-\s?')
CLEANUP_DAYS = 7

# Rate limiting
REQUEST_COUNTS = {}
RATE_LIMIT_WINDOW = 60  # seconds
MAX_REQUESTS_PER_WINDOW = 100

# Required environment variables
REQUIRED_ENV_VARS = ['NOTION_DB_ID']
# Note: NOTION_API_KEY is checked separately via get_secret() which handles both env vars and Secret Manager

# ----------------------------
# Environment & Secret Management
# ----------------------------

def validate_environment():
    """Validate that all required environment variables are set."""
    missing_vars = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_msg)
        raise EnvironmentError(error_msg)
    
    logger.info("Environment validation successful")


def get_secret(secret_id: str, project_id: Optional[str] = None) -> str:
    """
    Retrieve a secret from Google Secret Manager.
    Falls back to environment variable if Secret Manager is not available.
    
    Args:
        secret_id: The ID of the secret to retrieve
        project_id: Optional GCP project ID. If not provided, uses default credentials
        
    Returns:
        The secret value as a string
    """
    # Try environment variable first for local development
    env_value = os.environ.get(secret_id)
    if env_value:
        logger.info(f"Using environment variable for {secret_id}")
        return env_value
    
    # Try Secret Manager
    try:
        client = secretmanager.SecretManagerServiceClient()
        if not project_id:
            credentials, project_id = default()
            if not project_id:
                raise EnvironmentError("Unable to determine GCP project ID")
        
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode('UTF-8')
        logger.info(f"Retrieved {secret_id} from Secret Manager")
        return secret_value
    except Exception as e:
        logger.error(f"Failed to retrieve secret {secret_id}: {str(e)}")
        raise EnvironmentError(f"Secret {secret_id} not found in environment or Secret Manager")


# ----------------------------
# Input Sanitization
# ----------------------------

def sanitize_string(input_str: Optional[str], max_length: int = 2000) -> str:
    """
    Sanitize string input to prevent injection attacks.
    
    NOTE: This removes all HTML tags. For a production system handling complex HTML,
    consider using a library like bleach for more robust HTML sanitization.
    
    Args:
        input_str: The string to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized string
    """
    if not input_str:
        return ""
    
    # Remove null bytes and control characters
    sanitized = ''.join(char for char in input_str if ord(char) >= 32 or char in '\n\r\t')
    
    # Truncate to max length
    sanitized = sanitized[:max_length]
    
    # Remove all HTML tags to prevent any HTML injection
    # This simple approach works for task titles/descriptions which shouldn't contain HTML
    sanitized = re.sub(r'<[^>]*>', '', sanitized)
    
    return sanitized.strip()


# ----------------------------
# Authentication & Authorization
# ----------------------------

def verify_cloud_function_auth(request) -> bool:
    """
    Verify that the request is properly authenticated for Cloud Functions.
    Checks for valid IAM authentication token.
    
    Args:
        request: Flask request object
        
    Returns:
        True if authenticated, False otherwise
    """
    # Check for the Identity-Aware Proxy (IAP) JWT token
    iap_jwt = request.headers.get('X-Goog-IAP-JWT-Assertion')
    
    # Check for OIDC token from Cloud Scheduler
    auth_header = request.headers.get('Authorization', '')
    
    if iap_jwt or auth_header.startswith('Bearer '):
        logger.info("Request authenticated with IAP or OIDC token")
        return True
    
    # For local testing, check for a test token
    if os.environ.get('ENVIRONMENT') == 'local':
        logger.warning("Running in local mode - bypassing authentication")
        return True
    
    logger.warning("Authentication failed - no valid token found")
    return False


def verify_signature(request, secret: str) -> bool:
    """
    Verify request signature for additional security.
    
    NOTE: This function is available but not currently called in the main flow.
    To enable signature verification, add it to the sync_tasks function:
        if not verify_signature(request, SIGNATURE_SECRET):
            return {"error": "Invalid signature"}, 401
    
    Args:
        request: Flask request object
        secret: Shared secret for HMAC verification
        
    Returns:
        True if signature is valid, False otherwise
    """
    signature = request.headers.get('X-Signature')
    if not signature:
        return False
    
    # Get request body
    body = request.get_data()
    
    # Calculate expected signature
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)


# ----------------------------
# Rate Limiting
# ----------------------------

def rate_limit(client_id: str) -> bool:
    """
    Simple rate limiting implementation.
    
    Args:
        client_id: Identifier for the client (IP address or user ID)
        
    Returns:
        True if request is allowed, False if rate limited
    """
    now = time.time()
    
    # Clean up old entries
    expired_keys = [k for k, v in REQUEST_COUNTS.items() 
                    if now - v['reset_time'] > RATE_LIMIT_WINDOW]
    for key in expired_keys:
        del REQUEST_COUNTS[key]
    
    # Check rate limit
    if client_id not in REQUEST_COUNTS:
        REQUEST_COUNTS[client_id] = {
            'count': 1,
            'reset_time': now
        }
        return True
    
    client_data = REQUEST_COUNTS[client_id]
    
    # Reset window if expired
    if now - client_data['reset_time'] > RATE_LIMIT_WINDOW:
        client_data['count'] = 1
        client_data['reset_time'] = now
        return True
    
    # Check if under limit
    if client_data['count'] < MAX_REQUESTS_PER_WINDOW:
        client_data['count'] += 1
        return True
    
    logger.warning(f"Rate limit exceeded for client {client_id}")
    return False


def rate_limited(func):
    """Decorator to apply rate limiting to a function."""
    @wraps(func)
    def wrapper(request):
        # Get client IP, preferring the first IP from X-Forwarded-For if present
        # This prevents header spoofing by only using the first (leftmost) IP
        forwarded_for = request.headers.get('X-Forwarded-For', '')
        if forwarded_for:
            client_id = forwarded_for.split(',')[0].strip()
        else:
            client_id = request.remote_addr or 'unknown'
        
        if not rate_limit(client_id):
            logger.warning(f"Rate limit exceeded for {client_id}")
            return {"error": "Rate limit exceeded"}, 429
        return func(request)
    return wrapper


# ----------------------------
# Idempotency
# ----------------------------

PROCESSED_TRANSACTIONS = {}
TRANSACTION_TTL = 3600  # 1 hour

def is_idempotent_request(transaction_id: str) -> bool:
    """
    Check if a request with the given transaction ID has already been processed.
    
    Args:
        transaction_id: Unique identifier for the request
        
    Returns:
        True if already processed, False otherwise
    """
    now = time.time()
    
    # Clean up expired transactions
    expired = [tid for tid, data in PROCESSED_TRANSACTIONS.items() 
               if now - data['timestamp'] > TRANSACTION_TTL]
    for tid in expired:
        del PROCESSED_TRANSACTIONS[tid]
    
    if transaction_id in PROCESSED_TRANSACTIONS:
        logger.info(f"Duplicate request detected: {transaction_id}")
        return True
    
    return False


def mark_transaction_processed(transaction_id: str, result: Dict[str, Any]):
    """Mark a transaction as processed."""
    PROCESSED_TRANSACTIONS[transaction_id] = {
        'timestamp': time.time(),
        'result': result
    }


def get_transaction_result(transaction_id: str) -> Optional[Dict[str, Any]]:
    """Get the result of a previously processed transaction."""
    if transaction_id in PROCESSED_TRANSACTIONS:
        return PROCESSED_TRANSACTIONS[transaction_id]['result']
    return None


# ----------------------------
# Helpers
# ----------------------------

def now_utc():
    return datetime.now(timezone.utc)


def parse_rfc3339(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def extract_task_type(title: str) -> Optional[str]:
    match = TASK_TYPE_REGEX.match(title or "")
    return match.group(1).upper() if match else None


def normalize_title(title: str) -> str:
    return sanitize_string(TASK_TYPE_REGEX.sub("", title).strip())


# ----------------------------
# Retry Logic
# ----------------------------

def retry_with_backoff(func, max_retries: int = 3, initial_delay: float = 1.0):
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        
    Returns:
        Result of the function call
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
            
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.error(f"All {max_retries} attempts failed")
    
    raise last_exception


# ----------------------------
# Google Tasks
# ----------------------------

def google_service():
    creds, _ = default()
    return build("tasks", "v1", credentials=creds)


def get_google_tasks() -> list[dict]:
    """
    Retrieve all tasks from Google Tasks with pagination support.
    
    Returns:
        List of task dictionaries
    """
    try:
        service = google_service()
        tasks = []

        tasklists = service.tasklists().list().execute().get("items", [])
        logger.info(f"Found {len(tasklists)} task lists")
        
        for tasklist in tasklists:
            page_token = None
            
            while True:
                try:
                    # Add pagination support
                    request_params = {
                        'tasklist': tasklist["id"],
                        'showCompleted': True,
                        'showHidden': True,
                        'maxResults': 100  # Maximum allowed by API
                    }
                    
                    if page_token:
                        request_params['pageToken'] = page_token
                    
                    result = service.tasks().list(**request_params).execute()

                    for task in result.get("items", []):
                        task["tasklist_id"] = tasklist["id"]
                        tasks.append(task)
                    
                    page_token = result.get('nextPageToken')
                    if not page_token:
                        break
                        
                except HttpError as e:
                    logger.error(f"Error fetching tasks from list {tasklist['id']}: {str(e)}")
                    raise

        logger.info(f"Retrieved {len(tasks)} total tasks")
        return tasks
        
    except Exception as e:
        logger.error(f"Failed to retrieve Google Tasks: {str(e)}")
        raise


def complete_google_task(task: dict):
    """
    Mark a Google Task as completed.
    
    Args:
        task: Task dictionary containing tasklist_id and id
    """
    try:
        service = google_service()
        service.tasks().patch(
            tasklist=task["tasklist_id"],
            task=task["id"],
            body={"status": "completed"}
        ).execute()
        logger.info(f"Completed Google task: {task['id']}")
    except HttpError as e:
        logger.error(f"Failed to complete Google task {task['id']}: {str(e)}")
        raise


# ----------------------------
# Notion Helpers
# ----------------------------

def notion_headers():
    """Get headers for Notion API requests."""
    try:
        api_key = get_secret('NOTION_API_KEY')
        return {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
    except Exception as e:
        logger.error(f"Failed to get Notion API key: {str(e)}")
        raise


def find_notion_task(google_task_id: str) -> Optional[dict]:
    """
    Find a Notion task by Google Task ID.
    
    Args:
        google_task_id: The Google Task ID to search for
        
    Returns:
        Notion page dictionary if found, None otherwise
    """
    try:
        def _find():
            response = requests.post(
                f"{NOTION_API_URL}/databases/{os.environ['NOTION_DB_ID']}/query",
                headers=notion_headers(),
                json={
                    "filter": {
                        "property": "Google Task ID",
                        "rich_text": {"equals": google_task_id}
                    }
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("results", [])
        
        results = retry_with_backoff(_find)
        return results[0] if results else None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to find Notion task {google_task_id}: {str(e)}")
        raise


def create_notion_task(task: dict):
    """
    Create a new task in Notion.
    
    Args:
        task: Task dictionary from Google Tasks
    """
    try:
        raw_title = sanitize_string(task.get("title", "Untitled"))
        task_type = extract_task_type(raw_title)

        properties = {
            "Task name": {
                "title": [{"text": {"content": normalize_title(raw_title)}}]
            },
            "Status": {
                "status": {
                    "name": "Completed" if task.get("status") == "completed" else "To do"
                }
            },
            "Google Task ID": {
                "rich_text": [{"text": {"content": task["id"]}}]
            },
            "Imported at": {
                "date": {"start": now_utc().isoformat()}
            },
            "Updated at": {
                "date": {"start": task.get("updated")}
            } if task.get("updated") else None,
            "Due date": {
                "date": {"start": task.get("due")}
            } if task.get("due") else None,
            "Description": {
                "rich_text": [{"text": {"content": sanitize_string(task.get("notes", ""))}}]
            } if task.get("notes") else None,
            "Link": {"url": task.get("selfLink")},
            "Effort level": {"select": {"name": "Medium"}},
        }

        if task_type:
            properties["Task type"] = {
                "multi_select": [{"name": task_type}]
            }

        properties = {k: v for k, v in properties.items() if v is not None}

        def _create():
            response = requests.post(
                f"{NOTION_API_URL}/pages",
                headers=notion_headers(),
                json={
                    "parent": {"database_id": os.environ["NOTION_DB_ID"]},
                    "properties": properties,
                },
                timeout=10,
            )
            response.raise_for_status()
            return response
        
        retry_with_backoff(_create)
        logger.info(f"Created Notion task for Google task {task['id']}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to create Notion task for {task.get('id')}: {str(e)}")
        raise


def update_notion_task(page_id: str, task: dict):
    """
    Update an existing Notion task.
    
    Args:
        page_id: Notion page ID to update
        task: Task dictionary from Google Tasks
    """
    try:
        properties = {
            "Task name": {
                "title": [{"text": {"content": normalize_title(sanitize_string(task["title"]))}}]
            },
            "Updated at": {
                "date": {"start": task.get("updated")}
            } if task.get("updated") else None,
            "Due date": {
                "date": {"start": task.get("due")}
            } if task.get("due") else None,
            "Description": {
                "rich_text": [{"text": {"content": sanitize_string(task.get("notes", ""))}}]
            } if task.get("notes") else None,
        }

        properties = {k: v for k, v in properties.items() if v is not None}

        def _update():
            response = requests.patch(
                f"{NOTION_API_URL}/pages/{page_id}",
                headers=notion_headers(),
                json={"properties": properties},
                timeout=10,
            )
            response.raise_for_status()
            return response
        
        retry_with_backoff(_update)
        logger.info(f"Updated Notion task {page_id}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to update Notion task {page_id}: {str(e)}")
        raise


def get_completed_notion_tasks() -> list[dict]:
    """
    Get all completed tasks from Notion that haven't been synced back to Google.
    
    Returns:
        List of Notion page dictionaries
    """
    try:
        def _query():
            response = requests.post(
                f"{NOTION_API_URL}/databases/{os.environ['NOTION_DB_ID']}/query",
                headers=notion_headers(),
                json={
                    "filter": {
                        "and": [
                            {
                                "property": "Status",
                                "status": {"equals": "Completed"}
                            },
                            {
                                "property": "Google Task ID",
                                "rich_text": {"is_not_empty": True}
                            }
                        ]
                    }
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("results", [])
        
        results = retry_with_backoff(_query)
        logger.info(f"Found {len(results)} completed Notion tasks")
        return results
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get completed Notion tasks: {str(e)}")
        raise


def sync_notion_to_google(notion_pages: list[dict], google_tasks_map: dict) -> int:
    """
    Sync completed tasks from Notion back to Google Tasks.
    
    Args:
        notion_pages: List of Notion page dictionaries
        google_tasks_map: Map of Google Task ID to task dictionary
        
    Returns:
        Number of tasks synced
    """
    synced = 0
    
    for page in notion_pages:
        try:
            # Get Google Task ID from Notion page
            google_task_id_prop = page["properties"].get("Google Task ID", {})
            google_task_id_texts = google_task_id_prop.get("rich_text", [])
            
            if not google_task_id_texts:
                continue
                
            google_task_id = google_task_id_texts[0]["text"]["content"]
            
            # Find corresponding Google Task
            if google_task_id not in google_tasks_map:
                logger.warning(f"Google task {google_task_id} not found")
                continue
            
            google_task = google_tasks_map[google_task_id]
            
            # Check if Google Task is already completed
            if google_task.get("status") == "completed":
                continue
            
            # Complete the Google Task
            complete_google_task(google_task)
            synced += 1
            logger.info(f"Synced completion from Notion to Google: {google_task_id}")
            
        except Exception as e:
            logger.error(f"Failed to sync Notion page {page['id']}: {str(e)}")
            # Continue with other tasks
            continue
    
    return synced


# ----------------------------
# Main Sync Logic
# ----------------------------

@rate_limited
def sync_tasks(request):
    """
    Main Cloud Function entry point for syncing tasks between Google Tasks and Notion.
    
    Args:
        request: Flask request object
        
    Returns:
        JSON response with sync statistics
    """
    try:
        # Validate environment variables
        validate_environment()
        
        # Check authentication
        if not verify_cloud_function_auth(request):
            logger.error("Authentication failed")
            return {"error": "Unauthorized"}, 401
        
        # Check for idempotency token
        transaction_id = request.headers.get('X-Transaction-ID')
        if transaction_id:
            if is_idempotent_request(transaction_id):
                cached_result = get_transaction_result(transaction_id)
                logger.info(f"Returning cached result for transaction {transaction_id}")
                return cached_result
        
        logger.info("Starting task sync")
        
        # Get all Google Tasks
        tasks = get_google_tasks()
        google_tasks_map = {task["id"]: task for task in tasks}
        
        created = updated = completed = notion_synced = 0

        # Sync from Google to Notion
        for task in tasks:
            try:
                if task.get("deleted"):
                    continue

                notion_page = find_notion_task(task["id"])

                if not notion_page:
                    create_notion_task(task)
                    created += 1
                    continue

                # Incremental update
                notion_updated = notion_page["properties"].get("Updated at", {}) \
                    .get("date", {}) \
                    .get("start")

                if notion_updated and task.get("updated"):
                    if parse_rfc3339(task["updated"]) > parse_rfc3339(notion_updated):
                        update_notion_task(notion_page["id"], task)
                        updated += 1

                # Weekly cleanup
                imported_at = notion_page["properties"]["Imported at"]["date"]["start"]
                if now_utc() - parse_rfc3339(imported_at) > timedelta(days=CLEANUP_DAYS):
                    if task.get("status") != "completed":
                        complete_google_task(task)
                        completed += 1
                        
            except Exception as e:
                logger.error(f"Failed to process task {task.get('id')}: {str(e)}")
                # Continue with other tasks
                continue
        
        # Bidirectional sync: Notion -> Google
        try:
            completed_notion_tasks = get_completed_notion_tasks()
            notion_synced = sync_notion_to_google(completed_notion_tasks, google_tasks_map)
        except Exception as e:
            logger.error(f"Failed to sync from Notion to Google: {str(e)}")
            # Don't fail the entire sync if bidirectional sync fails

        result = {
            "status": "ok",
            "created": created,
            "updated": updated,
            "completed_in_google": completed,
            "synced_from_notion": notion_synced,
            "total_seen": len(tasks),
        }
        
        # Store result for idempotency
        if transaction_id:
            mark_transaction_processed(transaction_id, result)
        
        logger.info(f"Sync completed: {result}")
        return result
        
    except EnvironmentError as e:
        logger.error(f"Environment error: {str(e)}")
        return {"error": str(e)}, 500
    except Exception as e:
        logger.error(f"Unexpected error during sync: {str(e)}")
        return {"error": "Internal server error"}, 500
