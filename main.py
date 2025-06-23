from fastapi import FastAPI, Request, HTTPException
import base64, json, os
from datetime import datetime
import logging
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
import uuid
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Gmail Pub/Sub Webhook")

# Gmail API scopes
SCOPES = ['https://mail.google.com/']

def get_gmail_service():
    """Get authenticated Gmail service"""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            raise Exception("No valid Gmail credentials available")
    
    return build('gmail', 'v1', credentials=creds)

def get_messages_from_history(service, user_id: str, current_history_id: str) -> List[str]:
    """Get message IDs from recent messages since we can't rely on history API with current ID"""
    try:
        # First, try to get messages from history if we have a stored previous history ID
        if os.path.exists('last_history_id.txt'):
            with open('last_history_id.txt', 'r') as f:
                last_history_id = f.read().strip()
            
            try:
                history = service.users().history().list(
                    userId=user_id,
                    startHistoryId=last_history_id,
                    historyTypes=['messageAdded']
                ).execute()
                
                message_ids = []
                if 'history' in history:
                    for record in history['history']:
                        if 'messagesAdded' in record:
                            for msg_added in record['messagesAdded']:
                                message_ids.append(msg_added['message']['id'])
                
                # Save current history ID for next time
                with open('last_history_id.txt', 'w') as f:
                    f.write(current_history_id)
                
                if message_ids:
                    return message_ids
            except Exception as e:
                logger.warning(f"History API failed: {e}, falling back to recent messages")
        
        # Fallback: Get recent messages from INBOX
        logger.info("Getting recent messages from INBOX as fallback")
        messages = service.users().messages().list(
            userId=user_id,
            labelIds=['INBOX'],
            maxResults=5,  # Get last 5 messages
            q='is:unread'  # Only unread messages
        ).execute()
        
        message_ids = []
        if 'messages' in messages:
            message_ids = [msg['id'] for msg in messages['messages']]
        
        # Save current history ID for next time
        with open('last_history_id.txt', 'w') as f:
            f.write(current_history_id)
        
        return message_ids
        
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        return []

def get_email_details(service, user_id: str, message_id: str) -> Dict[str, Any]:
    """Get detailed email information including subject, body, and attachments"""
    try:
        message = service.users().messages().get(
            userId=user_id, 
            id=message_id,
            format='full'
        ).execute()
        
        # Extract headers
        headers = {}
        if 'payload' in message and 'headers' in message['payload']:
            for header in message['payload']['headers']:
                headers[header['name'].lower()] = header['value']
        
        # Extract body
        body = extract_body(message['payload'])
        
        # Extract attachments info
        attachments = extract_attachment_info(message['payload'])
        
        return {
            'messageId': message_id,
            'subject': headers.get('subject', 'No Subject'),
            'from': headers.get('from', 'Unknown Sender'),
            'to': headers.get('to', 'Unknown Recipient'),
            'date': headers.get('date', 'Unknown Date'),
            'body': body,
            'attachments': attachments,
            'snippet': message.get('snippet', '')
        }
    except Exception as e:
        logger.error(f"Error getting email details: {e}")
        return None

def extract_body(payload) -> str:
    """Extract email body from payload"""
    body = ""
    
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                if 'data' in part['body']:
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break
            elif part['mimeType'] == 'text/html' and not body:
                if 'data' in part['body']:
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            elif part['mimeType'].startswith('multipart/'):
                body = extract_body(part)
                if body:
                    break
    else:
        if payload['mimeType'] == 'text/plain' and 'data' in payload['body']:
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        elif payload['mimeType'] == 'text/html' and 'data' in payload['body']:
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    
    return body

def extract_attachment_info(payload) -> List[Dict[str, Any]]:
    """Extract attachment information from payload"""
    attachments = []
    
    if 'parts' in payload:
        for part in payload['parts']:
            if 'filename' in part and part['filename']:
                attachment_info = {
                    'filename': part['filename'],
                    'mimeType': part['mimeType'],
                    'size': part['body'].get('size', 0),
                    'attachmentId': part['body'].get('attachmentId')
                }
                attachments.append(attachment_info)
            elif 'parts' in part:
                attachments.extend(extract_attachment_info(part))
    
    return attachments

def download_attachment(service, user_id: str, message_id: str, attachment_id: str, filename: str, folder_path: str) -> str:
    """Download attachment and save to folder"""
    try:
        # Create attachments folder if it doesn't exist
        os.makedirs(folder_path, exist_ok=True)
        
        # Get attachment data
        attachment = service.users().messages().attachments().get(
            userId=user_id,
            messageId=message_id,
            id=attachment_id
        ).execute()
        
        # Decode and save attachment
        file_data = base64.urlsafe_b64decode(attachment['data'])
        
        # Generate unique filename to avoid conflicts
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(folder_path, unique_filename)
        
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        logger.info(f"Downloaded attachment: {unique_filename}")
        return unique_filename
    except Exception as e:
        logger.error(f"Error downloading attachment {filename}: {e}")
        return None

def mark_message_as_read(service, user_id: str, message_id: str):
    """Mark a message as read"""
    try:
        service.users().messages().modify(
            userId=user_id,
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        logger.info(f"Marked message {message_id} as read")
    except Exception as e:
        logger.error(f"Error marking message as read: {e}")

def save_email_data(email_data: Dict[str, Any], folder_path: str = "email_data"):
    """Save email data as JSON file"""
    try:
        os.makedirs(folder_path, exist_ok=True)
        
        # Create filename with timestamp and message ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"email_{timestamp}_{email_data['messageId']}.json"
        file_path = os.path.join(folder_path, filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(email_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved email data: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Error saving email data: {e}")
        return None

@app.post("/gmail-webhook")
async def gmail_webhook(request: Request):
    logger.info("POST request received at /gmail-webhook")
    logger.info(f"Headers: {dict(request.headers)}")
    
    try:
        # Parse the webhook payload
        body = await request.body()
        logger.info(f"Raw body: {body}")
        
        payload = await request.json()
        logger.info(f"Parsed JSON: {json.dumps(payload, indent=2)}")

        msg = payload.get("message")
        if not msg or "data" not in msg:
            logger.error(f"No message.data in payload: {payload}")
            raise HTTPException(400, "Missing message.data")

        decoded = base64.urlsafe_b64decode(msg["data"]).decode()
        logger.info(f"Decoded message: {decoded}")
        
        notif = json.loads(decoded)
        logger.info(f"Parsed notification: {json.dumps(notif, indent=2)}")

        email_address = notif.get("emailAddress")
        history_id = notif.get("historyId")
        
        logger.info("=== GMAIL WEBHOOK TRIGGERED ===")
        logger.info(f"Email: {email_address}")
        logger.info(f"History ID: {history_id}")
        
        # Get Gmail service
        try:
            service = get_gmail_service()
            logger.info("Gmail service authenticated successfully")
        except Exception as e:
            logger.error(f"Failed to authenticate Gmail service: {e}")
            return {"status": "error", "message": "Gmail authentication failed"}
        
        # Get new messages from history
        message_ids = get_messages_from_history(service, 'me', str(history_id))
        logger.info(f"Found {len(message_ids)} new messages")
        
        processed_emails = []
        
        for message_id in message_ids:
            logger.info(f"Processing message ID: {message_id}")
            
            # Get email details
            email_details = get_email_details(service, 'me', message_id)
            if not email_details:
                continue
            
            logger.info(f"Email Subject: {email_details['subject']}")
            logger.info(f"Email From: {email_details['from']}")
            logger.info(f"Email To: {email_details['to']}")
            logger.info(f"Attachments: {len(email_details['attachments'])}")
            
            # Download attachments
            downloaded_attachments = []
            attachments_folder = f"attachments/{message_id}"
            
            for attachment in email_details['attachments']:
                if attachment['attachmentId']:
                    downloaded_filename = download_attachment(
                        service, 'me', message_id, 
                        attachment['attachmentId'], 
                        attachment['filename'],
                        attachments_folder
                    )
                    if downloaded_filename:
                        attachment['downloaded_filename'] = downloaded_filename
                        attachment['local_path'] = os.path.join(attachments_folder, downloaded_filename)
                        downloaded_attachments.append(attachment)
            
            # Update email details with downloaded attachment info
            email_details['downloaded_attachments'] = downloaded_attachments
            email_details['attachments_folder'] = attachments_folder
            email_details['processed_at'] = datetime.utcnow().isoformat()
            
            # Save email data as JSON
            json_filename = save_email_data(email_details)
            if json_filename:
                email_details['json_file'] = json_filename
            
            processed_emails.append(email_details)
            
            # Mark message as read after processing
            mark_message_as_read(service, 'me', message_id)
        
        logger.info(f"Successfully processed {len(processed_emails)} emails")
        logger.info("================================")

        return {
            "status": "ok", 
            "receivedAt": datetime.utcnow().isoformat(),
            "processedEmails": len(processed_emails),
            "emails": [
                {
                    "messageId": email['messageId'],
                    "subject": email['subject'],
                    "from": email['from'],
                    "attachments": len(email['attachments']),
                    "downloaded_attachments": len(email['downloaded_attachments'])
                } for email in processed_emails
            ]
        }
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Internal server error: {str(e)}")

@app.post("/health")
async def health_check():
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}

@app.get("/")
async def root():
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}