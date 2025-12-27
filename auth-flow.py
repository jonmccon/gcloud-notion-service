"""
Simple OAuth 2.0 authentication script for Google Tasks API.

This script uses the loopback flow (recommended by Google) to obtain OAuth credentials.
The OOB (out-of-band) flow has been deprecated and is no longer used.

For production deployments, use setup_oauth.py which stores credentials in Secret Manager.
This script is for local development/testing only.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/tasks']

print('\n' + '='*60)
print('AUTHORIZATION REQUIRED')
print('='*60)
print('\nStarting OAuth 2.0 Authorization Flow')
print('A browser window will open for authorization.')
print('If you\'re in a container/headless environment:')
print('  1. Copy the URL that will be displayed')
print('  2. Open it in a browser on another machine')
print('  3. After authorizing, copy the full redirect URL from the browser')
print('  4. Paste it back here when prompted')
print('='*60 + '\n')

# Use loopback flow (recommended by Google, replaces deprecated OOB flow)
flow = InstalledAppFlow.from_client_secrets_file(
    'client_secret.json',
    SCOPES
)

# Run the flow - this will attempt to open a browser and start a local server
try:
    creds = flow.run_local_server(
        host='localhost',
        port=8080,
        authorization_prompt_message='Please visit this URL to authorize: {url}',
        success_message='Authorization successful! You may close this window.',
        open_browser=False  # Don't auto-open browser (better for containers)
    )
except Exception as e:
    # Fallback for environments where local server cannot be started
    print(f'\nCould not start local server: {e}')
    print('\nFalling back to manual authorization...')
    
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent'
    )
    
    print('\nPlease visit this URL to authorize the application:\n')
    print(auth_url)
    print('\n' + '='*60)
    print('\nAfter authorizing, copy the FULL URL from your browser\'s address bar')
    print('(it will start with http://localhost:8080/)')
    print('='*60 + '\n')
    
    redirect_response = input('Paste the full redirect URL here: ').strip()
    flow.fetch_token(authorization_response=redirect_response)
    creds = flow.credentials

# Save the credentials to token.json
with open('token.json', 'w') as token_file:
    token_file.write(creds.to_json())

print('\n' + '='*60)
print('✓ Authentication successful!')
print('✓ Credentials saved to token.json')
print('='*60 + '\n')