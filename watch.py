from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os.path
import datetime
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# Define scopes
SCOPES = ['https://mail.google.com/']

def authenticate():
    creds = None
    # Check if token.json exists with valid credentials
    if os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            if creds and creds.valid:
                print("Using existing valid credentials from token.json")
                return creds
            elif creds and creds.expired and creds.refresh_token:
                print("Refreshing expired credentials...")
                creds.refresh(Request())
                return creds
        except Exception as e:
            print(f"Error loading token.json: {str(e)}")
            os.remove('token.json')  # Remove invalid token file
            creds = None
    
    # If no credentials or if they're invalid
    if not creds or not creds.valid:
        try:
            # Load client secrets from credentials.json
            if not os.path.exists('credentials.json'):
                print("""
To authenticate with Gmail API, you need to:
1. Go to Google Cloud Console (https://console.cloud.google.com)
2. Create or select a project
3. Enable Gmail API
                    4. Create OAuth 2.0 credentials
5. Download the client configuration as credentials.json
6. Place it in this directory
""")
                raise FileNotFoundError(
                    "credentials.json not found. Please download it from Google Cloud Console"
                )
            
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
            
            # Save credentials for future use
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
            
            print("New credentials saved to token.json")
            return creds
            
        except Exception as e:
            print(f"Error during authentication: {str(e)}")
            raise
    
    return creds

def setup_watch(service):
    try:
        # Get the webhook URL from environment variable or use default
        WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://0568-2405-201-c024-6861-5c82-45ad-aa0d-41b1.ngrok-free.app/gmail-webhook')
        print(f"Using webhook URL: {WEBHOOK_URL}")

        body = {
            'labelIds': ['INBOX'],
            'labelFilterBehavior': 'INCLUDE',
            'topicName': 'projects/email-463310/topics/incoming-mails-topic',
            'pushConfig': {
                'pushEndpoint': WEBHOOK_URL
            }
        }
        
        resp = service.users().watch(userId='me', body=body).execute()
        
        # Convert expiration to readable format
        expiration = datetime.datetime.fromtimestamp(int(resp['expiration'])/1000)
        print(f"Watch successfully set up:")
        print(f"History ID: {resp['historyId']}")
        print(f"Expires at: {expiration}")
        print(f"Webhook URL: {WEBHOOK_URL}")
        return resp
    
    except Exception as e:
        print(f"Error setting up watch: {str(e)}")
        raise

def main():
    try:
        # Authenticate
        creds = authenticate()
        
        # Build Gmail service
        service = build('gmail', 'v1', credentials=creds)
        
        # Set up watch
        setup_watch(service)
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")

if __name__ == '__main__':
    main()