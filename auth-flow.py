from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/tasks']

# Use OOB (out-of-band) flow - better for containers
flow = InstalledAppFlow.from_client_secrets_file(
    'client_secret.json',
    SCOPES,
    redirect_uri='urn:ietf:wg:oauth:2.0:oob'
)

# Get the authorization URL
auth_url, _ = flow.authorization_url(
    access_type='offline',
    prompt='consent'
)

print('\n' + '='*60)
print('AUTHORIZATION REQUIRED')
print('='*60)
print('\nPlease visit this URL to authorize the application:\n')
print(auth_url)
print('\n' + '='*60)
print('\nAfter authorizing, Google will display a code on the page.')
print('Copy that code and paste it here.')
print('='*60 + '\n')

# Get the authorization code from user
code = input('Enter the authorization code: ').strip()

# Exchange the code for credentials
flow.fetch_token(code=code)
creds = flow.credentials

# Save the credentials to token.json
with open('token.json', 'w') as token_file:
    token_file.write(creds.to_json())

print('\n' + '='*60)
print('✓ Authentication successful!')
print('✓ Credentials saved to token.json')
print('='*60 + '\n')