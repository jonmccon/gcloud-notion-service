#!/usr/bin/env python3
"""
OAuth 2.0 Setup Script for Google Tasks API

This script handles the one-time OAuth 2.0 consent flow to obtain user credentials
for accessing Google Tasks. The obtained tokens are stored in Google Secret Manager
for use by the Cloud Function.

This script uses OOB (out-of-band) flow which works well in container environments
where a browser cannot be automatically opened.

Usage:
    1. Create OAuth 2.0 credentials in Google Cloud Console:
       - Go to APIs & Services > Credentials
       - Create OAuth 2.0 Client ID (Desktop application type)
       - Download the credentials JSON file
    
    2. Run this script:
       python setup_oauth.py --credentials-file client_secrets.json --project-id YOUR_PROJECT_ID
    
    3. The script will display a URL - visit it in your browser to authorize
    
    4. Copy the authorization code from the browser and paste it into the script
    
    5. The script will store the tokens in Secret Manager as:
       - GOOGLE_OAUTH_TOKEN (contains all credential data including refresh token)
       - GOOGLE_OAUTH_CLIENT_CONFIG (client configuration for reference)
"""

import argparse
import json
import os
import sys
from typing import Optional

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials

# Scopes required for Google Tasks API
SCOPES = ['https://www.googleapis.com/auth/tasks']

# Secret Manager secret IDs
TOKEN_SECRET_ID = 'GOOGLE_OAUTH_TOKEN'
CLIENT_CONFIG_SECRET_ID = 'GOOGLE_OAUTH_CLIENT_CONFIG'


def create_or_update_secret(project_id: str, secret_id: str, secret_value: str) -> None:
    """
    Create or update a secret in Google Secret Manager.
    
    Args:
        project_id: GCP project ID
        secret_id: Secret identifier
        secret_value: Secret value to store
    """
    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{project_id}"
    secret_path = f"{parent}/secrets/{secret_id}"
    
    # Check if secret exists
    try:
        client.get_secret(request={"name": secret_path})
        secret_exists = True
    except Exception:
        secret_exists = False
    
    # Create secret if it doesn't exist
    if not secret_exists:
        print(f"Creating secret: {secret_id}")
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {
                    "replication": {"automatic": {}},
                },
            }
        )
    
    # Add secret version
    print(f"Adding new version to secret: {secret_id}")
    client.add_secret_version(
        request={
            "parent": secret_path,
            "payload": {"data": secret_value.encode("UTF-8")},
        }
    )
    print(f"✓ Secret {secret_id} updated successfully")


def run_oauth_flow(credentials_file: str) -> Credentials:
    """
    Run the OAuth 2.0 consent flow to obtain user credentials.
    Uses OOB (out-of-band) flow which is better for container environments.
    
    Args:
        credentials_file: Path to the OAuth client secrets JSON file
        
    Returns:
        Credentials object with access and refresh tokens
    """
    print("\n" + "="*60)
    print("AUTHORIZATION REQUIRED")
    print("="*60)
    print("\nStarting OAuth 2.0 Authorization Flow (OOB mode)")
    print("This mode works in container environments where a browser cannot be opened.")
    print()
    
    # Use OOB (out-of-band) flow - better for containers
    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_file,
        SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )
    
    # Get the authorization URL
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent'
    )
    
    print("Please visit this URL to authorize the application:\n")
    print(auth_url)
    print("\n" + "="*60)
    print("\nAfter authorizing, Google will display a code on the page.")
    print("Copy that code and paste it here.")
    print("="*60 + "\n")
    
    # Get the authorization code from user
    code = input('Enter the authorization code: ').strip()
    
    # Exchange the code for credentials
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    print("\n✓ Authorization successful!")
    return creds


def store_credentials(project_id: str, creds: Credentials, client_config: str) -> None:
    """
    Store OAuth credentials in Google Secret Manager.
    
    Args:
        project_id: GCP project ID
        creds: Credentials object with tokens
        client_config: Original client configuration JSON
    """
    print("\n" + "="*60)
    print("Storing Credentials in Secret Manager")
    print("="*60 + "\n")
    
    # Store the full credentials as JSON for easier refresh
    creds_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }
    
    # Store access token
    create_or_update_secret(
        project_id,
        TOKEN_SECRET_ID,
        json.dumps(creds_data)
    )
    
    # Store the original client config for future reference
    create_or_update_secret(
        project_id,
        CLIENT_CONFIG_SECRET_ID,
        client_config
    )
    
    print("\n" + "="*60)
    print("Setup Complete!")
    print("="*60)
    print(f"\nYour OAuth credentials have been stored in Secret Manager.")
    print(f"The Cloud Function will now be able to access your Google Tasks.\n")


def main():
    parser = argparse.ArgumentParser(
        description='Setup OAuth 2.0 credentials for Google Tasks API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--credentials-file',
        required=True,
        help='Path to OAuth 2.0 client secrets JSON file'
    )
    parser.add_argument(
        '--project-id',
        required=True,
        help='Google Cloud Project ID'
    )
    
    args = parser.parse_args()
    
    # Validate credentials file exists
    if not os.path.exists(args.credentials_file):
        print(f"Error: Credentials file not found: {args.credentials_file}")
        sys.exit(1)
    
    # Read the client config
    with open(args.credentials_file, 'r') as f:
        client_config = f.read()
    
    try:
        # Run OAuth flow
        creds = run_oauth_flow(args.credentials_file)
        
        # Store credentials
        store_credentials(args.project_id, creds, client_config)
        
    except Exception as e:
        print(f"\n❌ Error during setup: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
