from fastapi import FastAPI, Request, HTTPException
import base64, json
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Gmail Pub/Sub Webhook")

@app.post("/gmail-webhook")
async def gmail_webhook(request: Request):
    print("POST request received at /gmail-webhook")
    print(f"Headers: {dict(request.headers)}")
    logger.info("POST request received at /gmail-webhook")
    logger.info(f"Headers: {dict(request.headers)}")
    
    try:
        # Try to get raw body first
        body = await request.body()
        logger.info(f"Raw body: {body}")
        
        # Try to parse as JSON
        try:
            payload = await request.json()
            logger.info(f"Parsed JSON: {json.dumps(payload, indent=2)}")
        except Exception as e:
            logger.error(f"Error parsing JSON: {e}")
            payload = json.loads(body.decode())  # Try to parse raw body as JSON
            logger.info(f"Parsed raw body as JSON: {json.dumps(payload, indent=2)}")

        msg = payload.get("message")
        if not msg or "data" not in msg:
            logger.error(f"No message.data in payload: {payload}")
            raise HTTPException(400, "Missing message.data")

        decoded = base64.urlsafe_b64decode(msg["data"]).decode()
        logger.info(f"Decoded message: {decoded}")
        
        try:
            notif = json.loads(decoded)
            logger.info(f"Parsed notification: {json.dumps(notif, indent=2)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in decoded data: {e}")
            raise HTTPException(400, f"Invalid JSON in data: {e}")

        email = notif.get("emailAddress")
        history_id = notif.get("historyId")
        logger.info("=== GMAIL WEBHOOK TRIGGERED ===")
        logger.info(f"Email: {email}")
        logger.info(f"History ID: {history_id}")
        logger.info(f"Full notification: {json.dumps(notif, indent=2)}")
        logger.info("================================")

        return {"status": "ok", "receivedAt": datetime.utcnow().isoformat()}
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Internal server error: {str(e)}")

@app.post("/health")
async def health_check():
    print("POST request received at /health")
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}

@app.get("/")
async def health_check():
    print("GET request received at /")
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}