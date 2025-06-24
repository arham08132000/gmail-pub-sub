# Gmail Webhook Application

A FastAPI-based application that receives Gmail notifications via Google Cloud Pub/Sub, processes new emails, downloads attachments, and saves email data as JSON files.

## Features

- **Real-time Gmail notifications** via Google Cloud Pub/Sub webhooks
- **Email processing** with automatic attachment downloads
- **Duplicate prevention** using message ID and history ID tracking
- **Persistent state management** across application restarts
- **Automatic email marking** as read after processing
- **JSON data export** for all processed emails
- **Manual Gmail checking** endpoint for debugging

## Architecture

```
Gmail → Google Cloud Pub/Sub → Your Webhook Endpoint → FastAPI Application
```

Complete Architecture :- https://gmail-pub-sub.vercel.app/

## Prerequisites

- Python 3.7+
- Google Cloud Platform account
- Gmail account
- Public webhook URL (using ngrok, zrok, or similar tunneling service)

## Installation

1. **Clone the repository and install dependencies:**
```bash
pip install fastapi uvicorn google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dotenv
or
pip install -r requirements.txt
```

2. **Create environment file:**
```bash
cp .env.example .env
```
Edit `.env` and set your webhook URL:
```
WEBHOOK_URL="https://your-webhook-url.com/gmail-webhook"
```

## Google Cloud Setup

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing one
3. Note your project ID (e.g., `email-463310`)

### 2. Enable APIs

Enable the following APIs in your Google Cloud project:
- Gmail API
- Cloud Pub/Sub API

```bash
gcloud services enable gmail.googleapis.com
gcloud services enable pubsub.googleapis.com
```

### 3. Create Pub/Sub Topic and Subscription

#### Create Topic
```bash
gcloud pubsub topics create incoming-mails-topic
```

#### Create Push Subscription
```bash
gcloud pubsub subscriptions create incoming-mails-subscription \
    --topic=incoming-mails-topic \
    --push-endpoint=https://your-webhook-url.com/gmail-webhook
```

**Note:** Replace `your-webhook-url.com` with your actual webhook URL.

#### Verify Topic and Subscription
```bash
# List topics
gcloud pubsub topics list

# List subscriptions
gcloud pubsub subscriptions list
```

### 4. Set up OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Navigate to **APIs & Services** → **Credentials**
3. Click **Create Credentials** → **OAuth 2.0 Client IDs**
4. Choose **Desktop Application**
5. Download the JSON file and save it as `credentials.json` in your project directory

### 5. Configure Gmail API Permissions

1. In Google Cloud Console, go to **APIs & Services** → **OAuth consent screen**
2. Add your Gmail address to test users
3. Add the following scope: `https://mail.google.com/`

## Authentication Setup

### Initial Authentication
Run the watch setup script to authenticate and set up Gmail push notifications:

```bash
python watch.py
```

This will:
1. Open a browser for OAuth authentication
2. Save credentials to `token.json`
3. Set up Gmail push notifications with your Pub/Sub topic

### Manual Authentication (Alternative)
If you prefer to authenticate separately:

```bash
python auth.py
```

## Running the Application

### 1. Start the FastAPI Server
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Set up Public URL
Use a tunneling service to expose your local server:

**Using zrok (as in your .env):**
```bash
zrok share public --headless http://localhost:8000
```

**Using ngrok:**
```bash
ngrok http 8000
```

Update your `.env` file with the public URL.

### 3. Update Pub/Sub Subscription
Update your subscription with the correct webhook URL:
```bash
gcloud pubsub subscriptions modify-push-config incoming-mails-subscription \
    --push-endpoint=https://your-actual-webhook-url.com/gmail-webhook
```

### 4. Set up Gmail Watch
```bash
python watch.py
```

## API Endpoints

### Gmail Webhook
- **POST** `/gmail-webhook` - Receives Gmail push notifications
- Automatically processes new emails
- Downloads attachments
- Saves email data as JSON

### Manual Operations
- **GET** `/status` - Check application status
- **POST** `/check-gmail` - Manually check for new emails
- **POST** `/reset-start-time` - Reset tracking and start time
- **GET** `/` - Health check

## File Structure

```
├── main.py              # FastAPI application
├── auth.py              # Gmail authentication helper
├── watch.py             # Gmail watch setup script
├── credentials.json     # OAuth client secrets (not in repo)
├── token.json          # OAuth tokens (auto-generated)
├── .env                # Environment variables
├── email_data/         # Processed email JSON files
├── attachments/        # Downloaded email attachments
└── app_start_time.txt  # Application state files
```

## Configuration

### Environment Variables
- `WEBHOOK_URL` - Your public webhook endpoint URL

### Gmail API Scopes
- `https://mail.google.com/` - Full Gmail access for reading and modifying emails

## State Management

The application maintains persistent state across restarts:

- **`app_start_time.txt`** - Application start timestamp
- **`processed_messages.txt`** - List of processed message IDs
- **`processed_history_ids.txt`** - List of processed history IDs

## Data Storage

### Email Data
Processed emails are saved as JSON files in `email_data/`:
```json
{
  "messageId": "abc123",
  "subject": "Email Subject",
  "from": "sender@example.com",
  "to": "recipient@example.com",
  "date": "Mon, 1 Jan 2024 12:00:00 +0000",
  "body": "Email content...",
  "attachments": [...],
  "downloaded_attachments": [...],
  "processed_at": "2024-01-01T12:00:00"
}
```

### Attachments
Downloaded attachments are stored in `attachments/{messageId}/` with unique filenames.

## Troubleshooting

### Common Issues

**1. Authentication Errors**
- Ensure `credentials.json` is present and valid
- Check OAuth consent screen configuration
- Verify Gmail API is enabled

**2. Webhook Not Receiving Notifications**
- Verify your webhook URL is publicly accessible
- Check Pub/Sub subscription configuration
- Ensure Gmail watch is properly set up

**3. Permission Errors**
- Verify Gmail API scopes in OAuth consent screen
- Re-authenticate if scope changes were made

**4. Duplicate Processing**
- Application automatically handles duplicates
- Use `/reset-start-time` endpoint to clear state if needed

### Debugging

**Check Gmail Watch Status:**
```bash
# The watch expires after 7 days, re-run watch.py to renew
python watch.py
```

**Manual Email Check:**
```bash
curl -X POST http://localhost:8000/check-gmail
```

**View Application Status:**
```bash
curl http://localhost:8000/status
```

## Security Considerations

- Keep `credentials.json` and `token.json` secure
- Use HTTPS for webhook endpoints
- Regularly rotate OAuth credentials
- Monitor Pub/Sub subscription for unauthorized access

## Gmail Watch Renewal

Gmail push notifications expire after 7 days. Set up a cron job to renew automatically:

```bash
# Add to crontab (renew every 6 days)
0 0 */6 * * /path/to/your/venv/bin/python /path/to/your/project/watch.py
```

## Dependencies

```
fastapi
uvicorn[standard]
google-auth
google-auth-oauthlib
google-auth-httplib2
google-api-python-client
python-dotenv
```

## License

This project is provided as-is for educational and development purposes.

[![Gmail Pub-Sub](https://img.youtube.com/vi/3Qr3FYWHJBg/0.jpg)](https://www.youtube.com/watch?v=3Qr3FYWHJBg)
