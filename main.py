# main.py
from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}

# receives Gmail webhook notifications
@app.post("/gmail-webhook")
async def gmail_webhook(request: Request):
    body = await request.json()
    return {"status": "Webhook received", "data": body}
