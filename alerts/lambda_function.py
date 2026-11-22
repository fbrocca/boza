"""Alerts signup endpoint (AWS Lambda, Python 3.12, function URL).

  POST {"email": ..., "hoods": ["old-village", ...] or ["all"], "website": ""}  -> subscribe; sends a confirmation email
  GET  ?a=confirm&t=<token>                                                       -> confirm the address
  GET  ?a=unsub&t=<token>                                                         -> unsubscribe (the record is deleted)
  POST ?a=unsub&t=<token>                                                         -> same, for one-click unsubscribe in mail apps

Subscribers live in DynamoDB (TABLE), keyed by email. Nothing is sent to an address until it is confirmed
(double opt-in). If the confirmation email can't be sent (e.g. SES still in its sandbox), the record is
marked and tools/send_alerts.py retries it daily. Deployed by hand from this file; see README "Alerts".
"""
import base64
import html
import json
import os
import re
import secrets
import time

import boto3

TABLE = os.environ["TABLE"]
SENDER = os.environ["SENDER"]
SITE = os.environ.get("SITE", "https://zoningrecord.com/mount-pleasant/")
SELF = os.environ.get("SELF_URL", "")
db = boto3.resource("dynamodb").Table(TABLE)
ses = boto3.client("sesv2")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,60}$")


def page(title, body, status=200):
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · The Zoning Record</title>
<style>body{{margin:0;background:#f5f2ea;color:#191b18;font:18px/1.5 Georgia,serif;display:grid;place-items:center;min-height:100vh;padding:0 16px}}
main{{max-width:520px;border-top:3px solid #191b18;padding-top:18px}}h1{{font-weight:500;font-size:32px;margin:0 0 10px}}a{{color:#2e5b3f}}</style></head>
<body><main><h1>{html.escape(title)}</h1><p>{body}</p><p><a href="{SITE}">The Zoning Record · Mount Pleasant</a></p></main></body></html>"""
    return {"statusCode": status, "headers": {"Content-Type": "text/html; charset=utf-8"}, "body": doc}


def token_for(email, tok):
    return base64.urlsafe_b64encode(email.encode()).decode().rstrip("=") + "." + tok


def parse_token(t):
    try:
        b64, tok = t.rsplit(".", 1)
        return base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode(), tok
    except Exception:
        return None, None


def send_confirm(email, tok, hoods):
    link = f"{SELF}?a=confirm&t={token_for(email, tok)}"
    where = "all of Mount Pleasant" if "all" in hoods else f"{len(hoods)} neighborhood{'s' if len(hoods) != 1 else ''}"
    text = (f"Confirm your zoning alerts\n\nYou asked for an email when the Town of Mount Pleasant posts zoning items for {where}.\n"
            f"Confirm here: {link}\n\nIf you didn't ask, ignore this email; nothing more will be sent.\n\nThe Zoning Record · {SITE}")
    body = (f'<p style="font:16px/1.5 Georgia,serif">You asked for an email when the Town of Mount Pleasant posts zoning items for {html.escape(where)}.</p>'
            f'<p><a href="{link}" style="background:#191b18;color:#f5f2ea;padding:10px 18px;text-decoration:none;font:500 15px sans-serif">Confirm alerts</a></p>'
            f'<p style="font:13px sans-serif;color:#74776f">If you didn\'t ask, ignore this email; nothing more will be sent.<br>The Zoning Record · <a href="{SITE}">{SITE}</a></p>')
    ses.send_email(FromEmailAddress=SENDER, Destination={"ToAddresses": [email]},
                   Content={"Simple": {"Subject": {"Data": "Confirm your Mount Pleasant zoning alerts"},
                                       "Body": {"Text": {"Data": text}, "Html": {"Data": body}}}})


def subscribe(evt):
    try:
        data = json.loads(evt.get("body") or "{}")
    except ValueError:
        return {"statusCode": 400, "body": json.dumps({"ok": False, "error": "bad request"})}
    if data.get("website"):  # honeypot field, invisible to people
        return {"statusCode": 200, "body": json.dumps({"ok": True})}
    email = str(data.get("email", "")).strip().lower()
    hoods = [h for h in data.get("hoods") or [] if isinstance(h, str) and SLUG_RE.match(h)][:60] or ["all"]
    if not EMAIL_RE.match(email):
        return {"statusCode": 400, "body": json.dumps({"ok": False, "error": "Please enter a valid email address."})}
    now = int(time.time())
    item = db.get_item(Key={"email": email}).get("Item") or {}
    if now - int(item.get("confirm_sent", 0)) < 600:  # one confirmation email per address per 10 minutes
        return {"statusCode": 200, "body": json.dumps({"ok": True})}
    tok = secrets.token_urlsafe(24)
    status = "sent"
    try:
        send_confirm(email, tok, hoods)
    except Exception:
        status = "unsent"
    db.update_item(Key={"email": email},
                   UpdateExpression="SET pending_hoods = :h, tok = :t, confirm_sent = :n, confirm_status = :s, created = if_not_exists(created, :n), confirmed = if_not_exists(confirmed, :f)",
                   ExpressionAttributeValues={":h": hoods, ":t": tok, ":n": now, ":s": status, ":f": False})
    return {"statusCode": 200, "body": json.dumps({"ok": True})}


def by_token(t):
    email, tok = parse_token(t or "")
    if not email:
        return None
    item = db.get_item(Key={"email": email}).get("Item")
    return item if item and secrets.compare_digest(str(item.get("tok", "")), tok) else None


def lambda_handler(evt, ctx):
    method = evt.get("requestContext", {}).get("http", {}).get("method", "GET")
    q = evt.get("queryStringParameters") or {}
    if method == "POST" and q.get("a") != "unsub":  # one-click unsubscribe (RFC 8058) POSTs to the unsub link
        return subscribe(evt)
    item = by_token(q.get("t"))
    if q.get("a") == "confirm":
        if not item:
            return page("Link expired", "This confirmation link is no longer valid. Sign up again from the map.", 404)
        db.update_item(Key={"email": item["email"]}, UpdateExpression="SET confirmed = :t, hoods = :h, confirmed_at = :n",
                       ExpressionAttributeValues={":t": True, ":h": item.get("pending_hoods") or ["all"], ":n": int(time.time())})
        return page("You're subscribed", "You'll get an email when the Town posts zoning items for the areas you chose. Every email has a one-click unsubscribe link.")
    if q.get("a") == "unsub":
        if item:
            db.delete_item(Key={"email": item["email"]})
        return page("Unsubscribed", "You won't get any more alerts. Your address has been deleted.")
    return page("The Zoning Record", "Nothing to see here.", 404)
