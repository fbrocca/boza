"""Send zoning alerts by email (daily, after tools/upcoming.py).

    python3 tools/send_alerts.py [--dry-run]

Reads confirmed subscribers from DynamoDB (table zoningrecord-alerts; see alerts/lambda_function.py for
signup), finds zoning items on agendas for upcoming meetings in the neighborhoods each one chose (or all of
Mount Pleasant), and sends one email per subscriber listing only items they haven't been sent before.
Nothing new, nothing sent. Also retries confirmation emails that could not be sent at signup.

Emails go through Amazon SES from alerts@zoningrecord.com, with a one-click unsubscribe link and
List-Unsubscribe headers. Credentials come from the job's IAM role (GitHub OIDC); none are stored.
"""
import argparse
import base64
import datetime
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from static_pages import prop_slug  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "data")
SITE = "https://zoningrecord.com/mount-pleasant/"
FN_URL = "https://f5lvprd64h7z6xbbsh42743zoe0hxagd.lambda-url.us-east-1.on.aws/"
SENDER = "The Zoning Record <alerts@zoningrecord.com>"
TABLE = "zoningrecord-alerts"
REGION = "us-east-1"
E = lambda s: html.escape("" if s is None else str(s))  # noqa: E731


def token(email, tok):
    return base64.urlsafe_b64encode(email.encode()).decode().rstrip("=") + "." + tok


def item_key(m, it):
    return f"{m['date']}|{m['body']}|{it.get('case') or it['title']}"


def day(d):
    return datetime.date.fromisoformat(d).strftime("%A, %B %-d")


def plain(v):
    """DynamoDB attribute value to Python."""
    (t, x), = v.items()
    if t == "L":
        return [plain(i) for i in x]
    if t == "BOOL":
        return x
    if t == "N":
        return int(x)
    return x


def confirm_email(email, tok, hoods):
    link = f"{FN_URL}?a=confirm&t={token(email, tok)}"
    where = "all of Mount Pleasant" if "all" in hoods else f"{len(hoods)} neighborhood{'s' if len(hoods) != 1 else ''}"
    text = (f"Confirm your zoning alerts\n\nYou asked for an email when the Town of Mount Pleasant posts zoning items for {where}.\n"
            f"Confirm here: {link}\n\nIf you didn't ask, ignore this email; nothing more will be sent.\n\nThe Zoning Record · {SITE}")
    body = (f'<p style="font:16px/1.5 Georgia,serif">You asked for an email when the Town of Mount Pleasant posts zoning items for {E(where)}.</p>'
            f'<p><a href="{link}" style="background:#191b18;color:#f5f2ea;padding:10px 18px;text-decoration:none;font:500 15px sans-serif">Confirm alerts</a></p>'
            f'<p style="font:13px sans-serif;color:#74776f">If you didn\'t ask, ignore this email; nothing more will be sent.<br>The Zoning Record · <a href="{SITE}">{SITE}</a></p>')
    return "Confirm your Mount Pleasant zoning alerts", text, body, None


def alert_email(email, tok, groups, names):
    unsub = f"{FN_URL}?a=unsub&t={token(email, tok)}"
    n = sum(len(items) for _, items in groups)
    subject = f"{n} zoning item{'s' if n != 1 else ''} coming up" + (f" in {names[0]}" if len(names) == 1 else " in Mount Pleasant")
    t_parts, h_parts = [], []
    for m, items in groups:
        when = f"{day(m['date'])}{', ' + m['time'] if m.get('time') else ''} · {m['label']}"
        t_parts.append(when.upper())
        h_parts.append(f'<h2 style="font:500 19px Georgia,serif;margin:22px 0 6px;border-top:2px solid #191b18;padding-top:10px">{E(when)}</h2>')
        for it, link in items:
            t_parts.append(f"- {it['title']}{': ' + it['request'] if it.get('request') else ''}\n  {link}")
            h_parts.append(f'<p style="font:15px/1.45 sans-serif;margin:8px 0"><a href="{E(link)}" style="color:#2e5b3f;font-weight:600">{E(it["title"])}</a>'
                           f'{"<br>" + E(it["request"][:240]) if it.get("request") else ""}</p>')
        how = f"Comments due {m['deadline']}" if m.get("deadline") else "Public comment at the meeting"
        t_parts.append(f"{how}. Agenda: {m['agenda']}\n")
        h_parts.append(f'<p style="font:13px sans-serif;color:#4a4d47">{E(how)}. <a href="{E(m["agenda"])}" style="color:#2e5b3f">Agenda</a></p>')
    foot_t = f"\nYou get these because you asked for alerts at {SITE}. Unsubscribe: {unsub}"
    foot_h = (f'<p style="font:12px sans-serif;color:#74776f;margin-top:28px;border-top:1px solid #d6cfbd;padding-top:10px">'
              f'The Zoning Record · Mount Pleasant. Independent; not affiliated with the Town. '
              f'You get these because you asked for alerts at <a href="{SITE}" style="color:#74776f">zoningrecord.com</a>. '
              f'<a href="{unsub}" style="color:#74776f">Unsubscribe</a></p>')
    text = "\n".join(t_parts) + foot_t
    body = '<div style="max-width:600px;color:#191b18">' + "".join(h_parts) + foot_h + "</div>"
    headers = [{"Name": "List-Unsubscribe", "Value": f"<{unsub}>"}, {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"}]
    return subject, text, body, headers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    import boto3
    db, ses = boto3.client("dynamodb", region_name=REGION), boto3.client("sesv2", region_name=REGION)
    up = json.load(open(os.path.join(DATA, "upcoming.json")))
    nb = json.load(open(os.path.join(DATA, "neighborhoods.json")))
    props = {p["id"]: p for p in json.load(open(os.path.join(DATA, "properties.json")))["properties"]}
    names = {h["slug"]: h["name"] for h in nb["hoods"]}
    today = datetime.date.today().isoformat()
    meets = [m for m in up.get("meetings", []) if m["date"] >= today]
    subs = []
    kw = {"TableName": TABLE}
    while True:
        r = db.scan(**kw)
        subs += [{k: plain(v) for k, v in it.items()} for it in r.get("Items", [])]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    sent = confirms = errors = 0

    def send(to, msg):
        subject, text, body, headers = msg
        simple = {"Subject": {"Data": subject}, "Body": {"Text": {"Data": text}, "Html": {"Data": body}}}
        if headers:
            simple["Headers"] = headers
        if args.dry_run:
            print(f"--- to {to}: {subject}\n{text}\n")
            return
        ses.send_email(FromEmailAddress=SENDER, Destination={"ToAddresses": [to]}, Content={"Simple": simple})

    for s in subs:
        email = s["email"]
        try:
            if not s.get("confirmed"):
                if s.get("confirm_status") == "unsent":
                    send(email, confirm_email(email, s["tok"], s.get("pending_hoods") or ["all"]))
                    if not args.dry_run:
                        db.update_item(TableName=TABLE, Key={"email": {"S": email}}, UpdateExpression="SET confirm_status = :s",
                                       ExpressionAttributeValues={":s": {"S": "sent"}})
                    confirms += 1
                continue
            want = set(s.get("hoods") or ["all"])
            done = set(s.get("sent") or [])
            groups, new_keys = [], []
            for m in meets:
                items = []
                for it in m["items"]:
                    pid = it.get("property")
                    hood = nb["assign"].get(pid) if pid else None
                    if "all" not in want and hood not in want:
                        continue
                    k = item_key(m, it)
                    if k in done:
                        continue
                    link = f"{SITE}p/{prop_slug(props[pid])}/" if pid in props else m["agenda"]
                    items.append((it, link))
                    new_keys.append(k)
                if items:
                    groups.append((m, items))
            if not groups:
                continue
            chosen = [names[h] for h in want if h in names]
            send(email, alert_email(email, s["tok"], groups, chosen))
            if not args.dry_run:
                keep = (list(done) + new_keys)[-300:]
                db.update_item(TableName=TABLE, Key={"email": {"S": email}}, UpdateExpression="SET sent = :k, last_alert = :d",
                               ExpressionAttributeValues={":k": {"L": [{"S": k} for k in keep]}, ":d": {"S": today}})
            sent += 1
        except Exception as e:  # one bad address must not stop the rest
            errors += 1
            print(f"alert to one subscriber failed: {type(e).__name__}: {str(e)[:160]}")
    print(f"alerts: {len(subs)} subscribers ({sum(1 for s in subs if s.get('confirmed'))} confirmed), "
          f"{sent} alert emails, {confirms} confirmations sent, {errors} errors")


if __name__ == "__main__":
    main()
