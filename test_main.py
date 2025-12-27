"""
Unit tests for the gcloud-notion-service
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import os
import time
import json
from datetime import datetime, timezone

# Set test environment before importing main
os.environ['NOTION_DB_ID'] = 'test-db-id'
os.environ['NOTION_API_KEY'] = 'test-api-key'
os.environ['ENVIRONMENT'] = 'local'

import main


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions"""
    
    def test_sanitize_string(self):
        """Test input sanitization"""
        # Test normal string
        result = main.sanitize_string("Hello World")
        self.assertEqual(result, "Hello World")
        
        # Test with script tags - all HTML tags are removed
        result = main.sanitize_string("<script>alert('xss')</script>Hello")
        self.assertNotIn("<script>", result)
        self.assertNotIn("<", result)
        self.assertEqual(result, "alert('xss')Hello")
        
        # Test with script tags with spaces (CodeQL security fix)
        result = main.sanitize_string("<script>alert('xss')</script >Hello")
        self.assertNotIn("<script>", result)
        self.assertNotIn("<", result)
        
        result = main.sanitize_string("<script>alert('xss')</script\t>Hello")
        self.assertNotIn("<script>", result)
        self.assertNotIn("<", result)
        
        # Test with any HTML tags
        result = main.sanitize_string("<div>text</div>")
        self.assertNotIn("<", result)
        self.assertEqual(result, "text")
        
        # Test with control characters
        result = main.sanitize_string("Hello\x00World")
        self.assertEqual(result, "HelloWorld")
        
        # Test max length
        long_string = "a" * 3000
        result = main.sanitize_string(long_string)
        self.assertEqual(len(result), 2000)
    
    def test_extract_task_type(self):
        """Test task type extraction"""
        self.assertEqual(main.extract_task_type("CODE- Fix bug"), "CODE")
        self.assertEqual(main.extract_task_type("BUG- Handle error"), "BUG")
        self.assertIsNone(main.extract_task_type("Regular task"))
    
    def test_normalize_title(self):
        """Test title normalization"""
        self.assertEqual(main.normalize_title("CODE- Fix bug"), "Fix bug")
        self.assertEqual(main.normalize_title("Regular task"), "Regular task")


class TestAuthentication(unittest.TestCase):
    """Test authentication and authorization"""
    
    def test_verify_cloud_function_auth_with_iap(self):
        """Test authentication with IAP JWT"""
        request = Mock()
        request.headers.get = Mock(side_effect=lambda x, default='': 
            'fake-jwt-token' if x == 'X-Goog-IAP-JWT-Assertion' else default)
        
        result = main.verify_cloud_function_auth(request)
        self.assertTrue(result)
    
    def test_verify_cloud_function_auth_with_bearer(self):
        """Test authentication with Bearer token"""
        request = Mock()
        request.headers.get = Mock(side_effect=lambda x, default='': 
            'Bearer fake-token' if x == 'Authorization' else default)
        
        result = main.verify_cloud_function_auth(request)
        self.assertTrue(result)
    
    def test_verify_cloud_function_auth_local_mode(self):
        """Test authentication in local mode"""
        request = Mock()
        request.headers.get = Mock(return_value='')
        
        # Should pass in local mode
        result = main.verify_cloud_function_auth(request)
        self.assertTrue(result)


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting functionality"""
    
    def setUp(self):
        """Clear rate limit data before each test"""
        main.REQUEST_COUNTS.clear()
    
    def test_rate_limit_allows_initial_request(self):
        """Test that initial requests are allowed"""
        result = main.rate_limit('test-client-1')
        self.assertTrue(result)
    
    def test_rate_limit_allows_under_limit(self):
        """Test that requests under the limit are allowed"""
        client_id = 'test-client-2'
        for i in range(10):
            result = main.rate_limit(client_id)
            self.assertTrue(result)
    
    def test_rate_limit_blocks_over_limit(self):
        """Test that requests over the limit are blocked"""
        client_id = 'test-client-3'
        
        # Make requests up to the limit
        for i in range(main.MAX_REQUESTS_PER_WINDOW):
            main.rate_limit(client_id)
        
        # Next request should be blocked
        result = main.rate_limit(client_id)
        self.assertFalse(result)


class TestIdempotency(unittest.TestCase):
    """Test idempotency functionality"""
    
    def setUp(self):
        """Clear processed transactions before each test"""
        main.PROCESSED_TRANSACTIONS.clear()
    
    def test_first_request_not_idempotent(self):
        """Test that first request is not detected as duplicate"""
        result = main.is_idempotent_request('txn-123')
        self.assertFalse(result)
    
    def test_duplicate_request_detected(self):
        """Test that duplicate requests are detected"""
        txn_id = 'txn-456'
        main.mark_transaction_processed(txn_id, {'status': 'ok'})
        
        result = main.is_idempotent_request(txn_id)
        self.assertTrue(result)
    
    def test_get_transaction_result(self):
        """Test retrieving cached transaction results"""
        txn_id = 'txn-789'
        expected_result = {'status': 'ok', 'count': 5}
        
        main.mark_transaction_processed(txn_id, expected_result)
        result = main.get_transaction_result(txn_id)
        
        self.assertEqual(result, expected_result)


class TestEnvironmentValidation(unittest.TestCase):
    """Test environment variable validation"""
    
    def test_validate_environment_success(self):
        """Test successful environment validation"""
        # Should not raise exception
        main.validate_environment()
    
    def test_validate_environment_missing_vars(self):
        """Test validation with empty REQUIRED_ENV_VARS list"""
        # Note: REQUIRED_ENV_VARS is intentionally empty in the current implementation
        # because secrets (NOTION_API_KEY, NOTION_DB_ID, GOOGLE_OAUTH_TOKEN) are
        # retrieved via get_secret() which handles both Secret Manager and env vars.
        # This test verifies that validation passes when there are no required env vars.
        try:
            main.validate_environment()
            # Should succeed since REQUIRED_ENV_VARS is empty
        except EnvironmentError:
            self.fail("validate_environment() raised EnvironmentError unexpectedly")


class TestRetryLogic(unittest.TestCase):
    """Test retry with backoff functionality"""
    
    def test_retry_success_on_first_attempt(self):
        """Test function succeeds on first try"""
        mock_func = Mock(return_value='success')
        result = main.retry_with_backoff(mock_func)
        
        self.assertEqual(result, 'success')
        self.assertEqual(mock_func.call_count, 1)
    
    def test_retry_success_after_failures(self):
        """Test function succeeds after some failures"""
        mock_func = Mock(side_effect=[Exception('fail'), Exception('fail'), 'success'])
        result = main.retry_with_backoff(mock_func, max_retries=3, initial_delay=0.01)
        
        self.assertEqual(result, 'success')
        self.assertEqual(mock_func.call_count, 3)
    
    def test_retry_exhausts_attempts(self):
        """Test all retry attempts are exhausted"""
        mock_func = Mock(side_effect=Exception('fail'))
        
        with self.assertRaises(Exception):
            main.retry_with_backoff(mock_func, max_retries=3, initial_delay=0.01)
        
        self.assertEqual(mock_func.call_count, 3)


class TestGoogleTasksPagination(unittest.TestCase):
    """Test Google Tasks API pagination"""
    
    @patch('main.google_service')
    def test_get_google_tasks_with_pagination(self, mock_service):
        """Test that pagination is handled correctly"""
        # Setup mocks
        mock_tasks_service = MagicMock()
        mock_tasklists_service = MagicMock()
        
        mock_service.return_value.tasks.return_value = mock_tasks_service
        mock_service.return_value.tasklists.return_value = mock_tasklists_service
        
        # Mock tasklists response
        mock_tasklists_service.list.return_value.execute.return_value = {
            'items': [{'id': 'list1', 'title': 'My Tasks'}]
        }
        
        # Mock paginated tasks response
        mock_tasks_list = mock_tasks_service.list.return_value
        mock_tasks_list.execute.side_effect = [
            {
                'items': [
                    {'id': 'task1', 'title': 'Task 1'},
                    {'id': 'task2', 'title': 'Task 2'}
                ],
                'nextPageToken': 'page2'
            },
            {
                'items': [
                    {'id': 'task3', 'title': 'Task 3'}
                ]
            }
        ]
        
        # Execute
        tasks = main.get_google_tasks()
        
        # Verify
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0]['id'], 'task1')
        self.assertEqual(tasks[1]['id'], 'task2')
        self.assertEqual(tasks[2]['id'], 'task3')
        
        # Verify pagination was used
        self.assertEqual(mock_tasks_service.list.call_count, 2)


class TestNotionIntegration(unittest.TestCase):
    """Test Notion API integration"""
    
    def test_notion_headers_include_version(self):
        """Test that Notion-Version header is included in all requests"""
        with patch('main.get_secret') as mock_get_secret:
            mock_get_secret.return_value = 'test-api-key'
            
            headers = main.notion_headers()
            
            # Verify all required headers are present
            self.assertIn('Authorization', headers)
            self.assertIn('Notion-Version', headers)
            self.assertIn('Content-Type', headers)
            
            # Verify Notion-Version header value
            self.assertEqual(headers['Notion-Version'], '2022-06-28')
            
            # Verify header format
            self.assertTrue(headers['Authorization'].startswith('Bearer '))
            self.assertEqual(headers['Content-Type'], 'application/json')
    
    def test_notion_version_format(self):
        """Test that Notion-Version follows YYYY-MM-DD format"""
        import re
        version_pattern = r'^\d{4}-\d{2}-\d{2}$'
        self.assertRegex(main.NOTION_VERSION, version_pattern,
                        "Notion-Version must be in YYYY-MM-DD format")
    
    @patch('main.requests.post')
    @patch('main.notion_headers')
    def test_find_notion_task(self, mock_headers, mock_post):
        """Test finding a Notion task"""
        mock_headers.return_value = {
            'Authorization': 'Bearer test',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json'
        }
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': [{'id': 'page1', 'properties': {}}]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        result = main.find_notion_task('google-task-123')
        
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'page1')
    
    @patch('main.requests.post')
    @patch('main.notion_headers')
    @patch('main.get_secret')
    def test_create_notion_task_payload_structure(self, mock_get_secret, mock_headers, mock_post):
        """Test that create_notion_task sends properly structured payload"""
        mock_get_secret.return_value = 'test-db-id'
        mock_headers.return_value = {
            'Authorization': 'Bearer test',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json'
        }
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        task = {
            'id': 'task123',
            'title': 'CODE- Test Task',
            'status': 'needsAction',
            'updated': '2024-01-01T00:00:00Z',
            'due': '2024-01-10T00:00:00Z',
            'notes': 'Task description',
            'selfLink': 'https://tasks.google.com/task123'
        }
        
        main.create_notion_task(task)
        
        # Verify POST was called
        self.assertTrue(mock_post.called)
        
        # Get the call arguments
        call_args = mock_post.call_args
        
        # Verify URL
        self.assertEqual(call_args[0][0], 'https://api.notion.com/v1/pages')
        
        # Verify payload structure
        payload = call_args[1]['json']
        self.assertIn('parent', payload)
        self.assertIn('properties', payload)
        
        # Verify parent structure
        self.assertIn('database_id', payload['parent'])
        
        # Verify required properties are present
        properties = payload['properties']
        self.assertIn('Task name', properties)
        self.assertIn('Status', properties)
        self.assertIn('Google Task ID', properties)
        self.assertIn('Imported at', properties)
        
        # Verify property types match Notion API schema
        # Title property
        self.assertIn('title', properties['Task name'])
        self.assertIsInstance(properties['Task name']['title'], list)
        self.assertIn('text', properties['Task name']['title'][0])
        
        # Status property
        self.assertIn('status', properties['Status'])
        self.assertIn('name', properties['Status']['status'])
        
        # Rich text property
        self.assertIn('rich_text', properties['Google Task ID'])
        self.assertIsInstance(properties['Google Task ID']['rich_text'], list)
        
        # Date property
        self.assertIn('date', properties['Imported at'])
        self.assertIn('start', properties['Imported at']['date'])
        
        # Verify task type was extracted
        self.assertIn('Task type', properties)
        self.assertIn('multi_select', properties['Task type'])
    
    @patch('main.requests.post')
    @patch('main.notion_headers')
    def test_create_notion_task(self, mock_headers, mock_post):
        """Test creating a Notion task"""
        mock_headers.return_value = {
            'Authorization': 'Bearer test',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json'
        }
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        task = {
            'id': 'task123',
            'title': 'Test Task',
            'status': 'needsAction',
            'updated': '2024-01-01T00:00:00Z'
        }
        
        # Should not raise exception
        main.create_notion_task(task)
        
        # Verify request was made
        self.assertTrue(mock_post.called)
    
    @patch('main.requests.patch')
    @patch('main.notion_headers')
    def test_update_notion_task_payload_structure(self, mock_headers, mock_patch):
        """Test that update_notion_task sends properly structured payload"""
        mock_headers.return_value = {
            'Authorization': 'Bearer test',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json'
        }
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_patch.return_value = mock_response
        
        task = {
            'id': 'task123',
            'title': 'Updated Task',
            'updated': '2024-01-02T00:00:00Z',
            'due': '2024-01-15T00:00:00Z',
            'notes': 'Updated description'
        }
        
        main.update_notion_task('page123', task)
        
        # Verify PATCH was called
        self.assertTrue(mock_patch.called)
        
        # Get the call arguments
        call_args = mock_patch.call_args
        
        # Verify URL format
        self.assertEqual(call_args[0][0], 'https://api.notion.com/v1/pages/page123')
        
        # Verify payload structure
        payload = call_args[1]['json']
        self.assertIn('properties', payload)
        
        properties = payload['properties']
        
        # Verify properties that should be updated
        self.assertIn('Task name', properties)
        self.assertIn('Updated at', properties)
        self.assertIn('Due date', properties)
        self.assertIn('Description', properties)
        
        # Verify property structure matches Notion API schema
        self.assertIn('title', properties['Task name'])
        self.assertIn('date', properties['Updated at'])
        self.assertIn('date', properties['Due date'])
        self.assertIn('rich_text', properties['Description'])
    
    @patch('main.requests.post')
    @patch('main.notion_headers')
    def test_database_query_payload_structure(self, mock_headers, mock_post):
        """Test database query uses proper filter structure"""
        mock_headers.return_value = {
            'Authorization': 'Bearer test',
            'Notion-Version': '2022-06-28'
        }
        mock_response = Mock()
        mock_response.json.return_value = {'results': []}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        main.find_notion_task('google-task-456')
        
        # Verify POST was called
        self.assertTrue(mock_post.called)
        
        # Get call arguments
        call_args = mock_post.call_args
        
        # Verify payload structure for database query
        payload = call_args[1]['json']
        self.assertIn('filter', payload)
        
        # Verify filter structure matches Notion API schema
        filter_obj = payload['filter']
        self.assertIn('property', filter_obj)
        self.assertIn('rich_text', filter_obj)
        self.assertEqual(filter_obj['property'], 'Google Task ID')
        self.assertIn('equals', filter_obj['rich_text'])
        self.assertEqual(filter_obj['rich_text']['equals'], 'google-task-456')


class TestOAuthAuthentication(unittest.TestCase):
    """Test OAuth 2.0 authentication functionality"""
    
    @patch('main.get_secret')
    @patch('main.Request')
    def test_get_oauth_credentials_valid_token(self, mock_request, mock_get_secret):
        """Test getting valid OAuth credentials"""
        # Mock credentials data
        creds_data = {
            'token': 'valid_access_token',
            'refresh_token': 'valid_refresh_token',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'scopes': ['https://www.googleapis.com/auth/tasks']
        }
        mock_get_secret.return_value = json.dumps(creds_data)
        
        # Mock valid credentials (not expired)
        with patch('main.Credentials') as mock_creds_class:
            mock_creds = Mock()
            mock_creds.valid = True
            mock_creds_class.return_value = mock_creds
            
            result = main.get_oauth_credentials()
            
            # Verify credentials were created
            self.assertIsNotNone(result)
            mock_get_secret.assert_called_once_with('GOOGLE_OAUTH_TOKEN', None)
    
    @patch('main.get_secret')
    @patch('main.update_secret')
    @patch('main.Request')
    def test_get_oauth_credentials_refresh_expired(self, mock_request, mock_update_secret, mock_get_secret):
        """Test refreshing expired OAuth credentials"""
        import json
        
        # Mock credentials data
        creds_data = {
            'token': 'expired_access_token',
            'refresh_token': 'valid_refresh_token',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'scopes': ['https://www.googleapis.com/auth/tasks']
        }
        mock_get_secret.return_value = json.dumps(creds_data)
        
        # Mock expired credentials that need refresh
        with patch('main.Credentials') as mock_creds_class:
            mock_creds = Mock()
            mock_creds.valid = False
            mock_creds.expired = True
            mock_creds.refresh_token = 'valid_refresh_token'
            mock_creds.token = 'new_access_token'
            mock_creds.client_id = 'test_client_id'
            mock_creds.client_secret = 'test_client_secret'
            mock_creds.token_uri = 'https://oauth2.googleapis.com/token'
            mock_creds.scopes = ['https://www.googleapis.com/auth/tasks']
            
            # Mock refresh to set valid to True
            def refresh_side_effect(request):
                mock_creds.valid = True
            
            mock_creds.refresh = Mock(side_effect=refresh_side_effect)
            mock_creds_class.return_value = mock_creds
            
            result = main.get_oauth_credentials()
            
            # Verify refresh was called
            mock_creds.refresh.assert_called_once()
            
            # Verify updated credentials were stored
            self.assertTrue(mock_update_secret.called)
    
    @patch('main.get_secret')
    def test_get_oauth_credentials_missing(self, mock_get_secret):
        """Test handling of missing OAuth credentials"""
        mock_get_secret.side_effect = EnvironmentError("Secret not found")
        
        with self.assertRaises(EnvironmentError) as context:
            main.get_oauth_credentials()
        
        self.assertIn("OAuth credentials not found", str(context.exception))
    
    @patch('main.get_oauth_credentials')
    def test_google_service_with_oauth(self, mock_get_oauth):
        """Test Google service creation with OAuth credentials"""
        # Mock OAuth credentials
        mock_creds = Mock()
        mock_get_oauth.return_value = mock_creds
        
        with patch('main.build') as mock_build:
            mock_build.return_value = Mock()
            
            service = main.google_service()
            
            # Verify build was called with OAuth credentials
            mock_build.assert_called_once_with("tasks", "v1", credentials=mock_creds)
            mock_get_oauth.assert_called_once()


if __name__ == '__main__':
    unittest.main()
