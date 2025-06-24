from fastapi import FastAPI, Request, HTTPException
import base64, json, os
from datetime import datetime, timedelta
import logging
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
import uuid
from typing import List, Dict, Any, Optional
import email.utils
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")

app = FastAPI(title="Gmail Pub/Sub Webhook")

# Track application start time, processed messages, and history IDs
APP_START_TIME = datetime.utcnow()
PROCESSED_MESSAGES = set()  # Track processed message IDs to prevent duplicates
PROCESSED_HISTORY_IDS = set()  # Track processed history IDs to prevent duplicate webhook processing
logger.info(f"Application started at: {APP_START_TIME.isoformat()}")

# Gmail API scopes
SCOPES = ['https://mail.google.com/']

def save_app_state():
    """Save app start time, processed messages, and history IDs to files"""
    with open('app_start_time.txt', 'w') as f:
        f.write(APP_START_TIME.isoformat())
    
    with open('processed_messages.txt', 'w') as f:
        for msg_id in PROCESSED_MESSAGES:
            f.write(f"{msg_id}\n")
    
    with open('processed_history_ids.txt', 'w') as f:
        for history_id in PROCESSED_HISTORY_IDS:
            f.write(f"{history_id}\n")

def load_app_state():
    """Load app start time, processed messages, and history IDs from files"""
    global APP_START_TIME, PROCESSED_MESSAGES, PROCESSED_HISTORY_IDS
    
    # Load start time
    if os.path.exists('app_start_time.txt'):
        try:
            with open('app_start_time.txt', 'r') as f:
                APP_START_TIME = datetime.fromisoformat(f.read().strip())
            logger.info(f"Loaded previous app start time: {APP_START_TIME.isoformat()}")
        except Exception as e:
            logger.warning(f"Could not load previous start time: {e}")
            save_app_state()
    else:
        save_app_state()
    
    # Load processed messages
    if os.path.exists('processed_messages.txt'):
        try:
            with open('processed_messages.txt', 'r') as f:
                PROCESSED_MESSAGES = {line.strip() for line in f if line.strip()}
            logger.info(f"Loaded {len(PROCESSED_MESSAGES)} previously processed messages")
        except Exception as e:
            logger.warning(f"Could not load processed messages: {e}")
    
    # Load processed history IDs
    if os.path.exists('processed_history_ids.txt'):
        try:
            with open('processed_history_ids.txt', 'r') as f:
                PROCESSED_HISTORY_IDS = {line.strip() for line in f if line.strip()}
            logger.info(f"Loaded {len(PROCESSED_HISTORY_IDS)} previously processed history IDs")
        except Exception as e:
            logger.warning(f"Could not load processed history IDs: {e}")

# Load state on application startup
load_app_state()

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

def get_new_messages(service, user_id: str) -> List[str]:
    """Get new unread messages received after app start time"""
    try:
        # Format date for Gmail search
        start_date_str = APP_START_TIME.strftime('%Y/%m/%d')
        query = f'after:{start_date_str} in:inbox is:unread'
        
        logger.info(f"Gmail search query: {query}")
        
        response = service.users().messages().list(
            userId=user_id,
            q=query,
            maxResults=50
        ).execute()
        
        all_message_ids = []
        if 'messages' in response:
            all_message_ids = [msg['id'] for msg in response['messages']]
        
        # Filter out already processed messages
        new_message_ids = [msg_id for msg_id in all_message_ids if msg_id not in PROCESSED_MESSAGES]
        
        logger.info(f"Found {len(all_message_ids)} total messages, {len(new_message_ids)} new messages")
        return new_message_ids
        
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        return []

def is_message_after_start_time(message: Dict) -> bool:
    """Check if message was received after app start time"""
    try:
        headers = {}
        if 'payload' in message and 'headers' in message['payload']:
            for header in message['payload']['headers']:
                headers[header['name'].lower()] = header['value']
        
        date_str = headers.get('date', '')
        if not date_str:
            return False
            
        # Parse email date
        message_date = email.utils.parsedate_to_datetime(date_str).replace(tzinfo=None)
        return message_date >= APP_START_TIME
            
    except Exception as e:
        logger.warning(f"Could not parse message date: {e}")
        return False

def get_email_details(service, user_id: str, message_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed email information"""
    try:
        message = service.users().messages().get(
            userId=user_id, 
            id=message_id,
            format='full'
        ).execute()
        
        # Double-check message date
        if not is_message_after_start_time(message):
            logger.info(f"Message {message_id} is before app start time, skipping")
            return None
        
        # Extract headers
        headers = {}
        if 'payload' in message and 'headers' in message['payload']:
            for header in message['payload']['headers']:
                headers[header['name'].lower()] = header['value']
        
        # Extract body and attachments
        body = extract_body(message['payload'])
        attachments = extract_attachment_info(message['payload'])
        
        return {
            'messageId': message_id,
            'subject': headers.get('subject', 'No Subject'),
            'from': headers.get('from', 'Unknown Sender'),
            'to': headers.get('to', 'Unknown Recipient'),
            'date': headers.get('date', 'Unknown Date'),
            'body': body,
            'attachments': attachments,
            'snippet': message.get('snippet', ''),
            'processed_at': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting email details for {message_id}: {e}")
        return None

def extract_body(payload) -> str:
    """Extract email body from payload"""
    def _extract_body_recursive(payload):
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                    return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                elif part['mimeType'].startswith('multipart/'):
                    result = _extract_body_recursive(part)
                    if result:
                        return result
            
            # If no plain text found, try HTML
            for part in payload['parts']:
                if part['mimeType'] == 'text/html' and 'data' in part['body']:
                    return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
        else:
            if payload['mimeType'] == 'text/plain' and 'data' in payload['body']:
                return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
            elif payload['mimeType'] == 'text/html' and 'data' in payload['body']:
                return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        
        return ""
    
    return _extract_body_recursive(payload)

def extract_attachment_info(payload) -> List[Dict[str, Any]]:
    """Extract attachment information from payload"""
    attachments = []
    
    def _extract_attachments_recursive(payload):
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
                    _extract_attachments_recursive(part)
    
    _extract_attachments_recursive(payload)
    return attachments

def download_attachment(service, user_id: str, message_id: str, attachment_id: str, filename: str, folder_path: str) -> Optional[str]:
    """Download attachment and save to folder"""
    try:
        os.makedirs(folder_path, exist_ok=True)
        
        attachment = service.users().messages().attachments().get(
            userId=user_id,
            messageId=message_id,
            id=attachment_id
        ).execute()
        
        file_data = base64.urlsafe_b64decode(attachment['data'])
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

def save_email_data(email_data: Dict[str, Any], folder_path: str = "email_data") -> Optional[str]:
    """Save email data as JSON file"""
    try:
        os.makedirs(folder_path, exist_ok=True)
        
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

def process_email(service, message_id: str) -> Optional[Dict[str, Any]]:
    """Process a single email message"""
    try:
        # Get email details
        email_details = get_email_details(service, 'me', message_id)
        if not email_details:
            return None
        
        logger.info(f"Processing: {email_details['subject']} from {email_details['from']}")
        
        # Download attachments
        downloaded_attachments = []
        if email_details['attachments']:
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
        
        # Update email details
        email_details['downloaded_attachments'] = downloaded_attachments
        email_details['attachments_folder'] = f"attachments/{message_id}" if downloaded_attachments else None
        
        # Save email data as JSON
        json_filename = save_email_data(email_details)
        if json_filename:
            email_details['json_file'] = json_filename
        
        # Mark as processed and read
        PROCESSED_MESSAGES.add(message_id)
        mark_message_as_read(service, 'me', message_id)
        
        # Save updated state
        save_app_state()
        
        return email_details
        
    except Exception as e:
        logger.error(f"Error processing email {message_id}: {e}")
        return None

@app.post("/gmail-webhook")
async def gmail_webhook(request: Request):
    """Handle Gmail webhook notifications"""
    
    try:
        body = await request.body()
        payload = await request.json()
        
        msg = payload.get("message")
        if not msg or "data" not in msg:
            raise HTTPException(400, "Missing message.data")

        decoded = base64.urlsafe_b64decode(msg["data"]).decode()
        notif = json.loads(decoded)
        
        email_address = notif.get("emailAddress")
        history_id = notif.get("historyId")
        
        # Check if we've already processed this history ID
        if history_id in PROCESSED_HISTORY_IDS:
            logger.info(f"History ID {history_id} already processed, skipping")
            return {
                "status": "ok",
                "message": "Already processed",
                "historyId": history_id
            }
        
        logger.info(f"Gmail webhook triggered - Email: {email_address}, History ID: {history_id}")
        
        # Add this history ID to processed set immediately to prevent duplicate processing
        PROCESSED_HISTORY_IDS.add(history_id)
        save_app_state()
        
        # Get Gmail service
        try:
            service = get_gmail_service()
        except Exception as e:
            logger.error(f"Failed to authenticate Gmail service: {e}")
            # Remove from processed set since we couldn't process it
            PROCESSED_HISTORY_IDS.discard(history_id)
            save_app_state()
            return {"status": "error", "message": "Gmail authentication failed"}
        
        # Get new messages
        message_ids = get_new_messages(service, 'me')
        
        if not message_ids:
            logger.info("No new messages to process")
            return {
                "status": "ok",
                "message": "No new messages",
                "historyId": history_id,
                "processedEmails": 0
            }
        
        # Process each message
        processed_emails = []
        for message_id in message_ids:
            email_details = process_email(service, message_id)
            if email_details:
                processed_emails.append({
                    "messageId": email_details['messageId'],
                    "subject": email_details['subject'],
                    "from": email_details['from'],
                    "attachments": len(email_details['attachments']),
                    "downloaded_attachments": len(email_details['downloaded_attachments'])
                })
        
        logger.info(f"Successfully processed {len(processed_emails)} emails for history ID {history_id}")
        
        return {
            "status": "ok",
            "receivedAt": datetime.utcnow().isoformat(),
            "appStartTime": APP_START_TIME.isoformat(),
            "historyId": history_id,
            "processedEmails": len(processed_emails),
            "totalProcessedMessages": len(PROCESSED_MESSAGES),
            "emails": processed_emails
        }
        
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        # If there was an error and we added a history ID, remove it so it can be reprocessed
        if 'history_id' in locals():
            PROCESSED_HISTORY_IDS.discard(history_id)
            save_app_state()
        raise HTTPException(500, f"Internal server error: {str(e)}")

@app.post("/reset-start-time")
async def reset_start_time():
    """Reset the application start time and clear processed messages and history IDs"""
    global APP_START_TIME, PROCESSED_MESSAGES, PROCESSED_HISTORY_IDS
    APP_START_TIME = datetime.utcnow()
    PROCESSED_MESSAGES.clear()
    PROCESSED_HISTORY_IDS.clear()
    save_app_state()
    
    logger.info(f"App start time reset to: {APP_START_TIME.isoformat()}")
    return {
        "status": "ok",
        "message": "App start time reset and all processed data cleared",
        "newStartTime": APP_START_TIME.isoformat()
    }

@app.get("/status")
async def get_status():
    """Get application status"""
    return {
        "status": "healthy",
        "appStartTime": APP_START_TIME.isoformat(),
        "totalProcessedMessages": len(PROCESSED_MESSAGES),
        "totalProcessedHistoryIds": len(PROCESSED_HISTORY_IDS),
        "currentTime": datetime.utcnow().isoformat()
    }

@app.post("/check-gmail")
async def manual_check_gmail():
    """Manually check for new Gmail messages (for debugging)"""
    try:
        service = get_gmail_service()
        message_ids = get_new_messages(service, 'me')
        
        return {
            "status": "ok",
            "newMessages": len(message_ids),
            "messageIds": message_ids,
            "appStartTime": APP_START_TIME.isoformat(),
            "totalProcessedMessages": len(PROCESSED_MESSAGES)
        }
    except Exception as e:
        logger.error(f"Manual check error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/")
async def root():
    """Render the main page"""
    return templates.TemplateResponse("index.html", {"request": {}})