
import base64
from pathlib import Path
from email import policy
from email.parser import BytesParser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent
SECRETS_DIR = BASE_DIR / "secrets"
CREDENTIALS = SECRETS_DIR / "credentials.json"
TOKEN = SECRETS_DIR / "token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def connect_gmail():
    creds = None

    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN), SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def read_handshake_emails():
    service = connect_gmail()

    results = service.users().messages().list(
        userId="me",
        q="Handshake",
        maxResults=10
    ).execute()

    messages = results.get("messages", [])

    print(f"Found {len(messages)} Handshake emails")

    for item in messages:
        result = service.users().messages().get(
            userId="me",
            id=item["id"],
            format="raw"
        ).execute()

        raw = base64.urlsafe_b64decode(result["raw"])
        mail = BytesParser(
            policy=policy.default
        ).parsebytes(raw)

        print("\n" + "=" * 50)
        print("From:", mail.get("From"))
        print("Subject:", mail.get("Subject"))
        print("Date:", mail.get("Date"))

        body = mail.get_body(
            preferencelist=("plain", "html")
        )

        if body:
            print("Content:")
            print(body.get_content()[:1500])


if __name__ == "__main__":
    read_handshake_emails()
