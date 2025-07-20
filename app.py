from flask import Flask, redirect, url_for, session, request, render_template, send_file
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os
import base64
import mimetypes
from io import BytesIO

app = Flask(__name__)
app.secret_key = "super_secret_key"  # Keep this safe and change in production

# Allow OAuth for local testing
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_SECRETS_FILE = "credentials.json"

# In-memory storage for attachments
attachment_store = {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://127.0.0.1:8000/callback"
    )
    authorization_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true"
    )
    session["state"] = state
    return redirect(authorization_url)

@app.route("/callback")
def callback():
    state = session.get("state")
    if not state:
        return redirect(url_for("index"))

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://127.0.0.1:8000/callback"
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session["credentials"] = credentials_to_dict(credentials)  # Only safe values

    return redirect(url_for("certificates"))

@app.route("/certificates")
def certificates():
    creds_data = session.get("credentials")
    if not creds_data:
        return redirect(url_for("index"))

    creds = Credentials(**creds_data)
    service = build("gmail", "v1", credentials=creds)

    query = 'has:attachment subject:(certificate OR completion OR award)'
    results = service.users().messages().list(userId='me', q=query, maxResults=20).execute()
    messages = results.get("messages", [])

    document_emails = []

    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        headers = msg_data['payload'].get('headers', [])

        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
        date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'Unknown Date')
        snippet = msg_data.get('snippet', '')

        parts = msg_data['payload'].get('parts', [])
        attachments = []

        for part in parts:
            if part.get('filename') and 'attachmentId' in part.get('body', {}):
                filename = part['filename']
                att_id = part['body']['attachmentId']
                attachment = service.users().messages().attachments().get(
                    userId='me',
                    messageId=msg['id'],
                    id=att_id
                ).execute()
                file_data = base64.urlsafe_b64decode(attachment['data'])
                attachment_store[filename] = file_data

                attachments.append({
                    "filename": filename,
                    "url": f"/download/{filename}"
                })

        if attachments:
            document_emails.append({
                "from": sender,
                "subject": subject,
                "date": date,
                "preview": snippet,
                "attachments": attachments
            })

    return render_template("certificates.html", emails=document_emails)

@app.route("/download/<filename>")
def download(filename):
    if filename not in attachment_store:
        return "File not found", 404

    data = attachment_store[filename]
    mime_type, _ = mimetypes.guess_type(filename)
    return send_file(BytesIO(data), mimetype=mime_type, as_attachment=True, download_name=filename)

def credentials_to_dict(credentials):
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "scopes": credentials.scopes
    }

if __name__ == "__main__":
    app.run(port=8000, debug=True)
