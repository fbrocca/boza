"""Extract design-review cases from Historic District Preservation Commission
(HDPC) and Design Review Board (DRB) minutes.

    python3 tools/extract_design.py <sources_dir> > data/design.json

<sources_dir>/hdpc and <sources_dir>/drb hold minutes text files named
YYYY-MM-DD-<agendaID>.txt. Both boards list business items as

    A. 806 Pitt St., Survey Card 5961/Historic – TMS 5320900067, Final Review for ...
    A. 349 Coleman Blvd, 349 Coleman Boulevard, 517-06-00-060, Final Approval ...

Items rarely carry a case number, so each lot's items are grouped into one
project timeline (e.g. preliminary review in March, final approval in May).
A gap of more than two years starts a new project. Both boards decide on
their own; there is no Council step.
"""
import collections
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_cases import decide, reflow  # noqa: E402
from extract_planning import ADDRESS, BASE, all_tms, meetings, segments  # noqa: E402

BODIES = {"hdpc": "Historic District Preservation Commission", "drb": "Design Review Board"}
TMS_PLAIN = re.compile(r"TMS\s*(?:No\.?|#)?\s*:?\s*(\d{3})(\d{2})(\d{2})(\d{3})\b")
SKIP = re.compile(r"^(?:approval of|public comment|general public|correspondence|adjourn|call to order|"
                  r"consent|staff|other business|executive session|election|minutes)", re.I)


TMS_BARE = re.compile(r"(?<![\d-])(\d{3})(\d{2})(\d{2})(\d{3})(?![\d-])")


def tms_in(text, header=False):
    flat = re.sub(r"\s+", " ", text)
    out = all_tms(flat)
    out += ["-".join(m.groups()) for m in TMS_PLAIN.finditer(flat)]
    if header:  # in an item heading, a bare 10-digit number is the parcel number
        out += ["-".join(m.groups()) for m in TMS_BARE.finditer(flat)]
    return list(dict.fromkeys(out))


def address_in(header):
    flat = re.sub(r"\s+", " ", header)
    flat = re.sub(r"Survey(?: Card)?\s*\d*\s*/?\s*(?:Non-)?Historic", " ", flat, flags=re.I)
    m = ADDRESS.search(flat[:160])
    if m:
        return (m.group(1) + " " + m.group(2)).strip(" ,.")
    return re.split(r"[,–—-]\s", flat, maxsplit=1)[0].strip(" .")[:60]


def kind_of(text):
    t = text.lower()
    if "demoli" in t:
        return "Demolition"
    if "conceptual" in t:
        return "Conceptual review"
    if "preliminary" in t:
        return "Preliminary review"
    if "final" in t:
        return "Final review"
    if "sign" in t.split():
        return "Signage"
    if "extension" in t or "vested" in t:
        return "Extension"
    return "Design review"


def consent_set(text):
    """TMS numbers and addresses approved in the meeting's consent motion(s)."""
    flat = re.sub(r"\s+", " ", text)
    keys = set()
    for m in re.finditer(r"consent", flat, re.I):
        win = flat[max(0, m.start() - 200): m.start() + 2500]
        end = re.search(r"seconded the motion.{0,80}?(?:All (?:present )?(?:voted )?in favor|carried|passed)|"
                        r"approved (?:through|by|via) (?:a )?consent", win[200:], re.I)
        if not end:
            continue
        block = win[: 200 + end.end()]
        if re.search(r"motion (?:failed|died)", block, re.I):
            continue
        keys.update(tms_in(block))
        keys.update(a.lower() for a in (f"{x.group(1)} {x.group(2)}".strip(" ,.") for x in ADDRESS.finditer(block)))
    return keys


STAFF_START = re.compile(r"staff(?:[\s-]+level)?\s+approvals?", re.I)
SECTION_END = re.compile(r"\n\s*(?:[IVX]{1,5}\.\s+[A-Z]|\d{1,2}\.\s+(?!\d)[A-Z][a-z]|There being no further business)")


def staff_ranges(text):
    out = []
    for m in STAFF_START.finditer(text):
        end = SECTION_END.search(text, m.end())
        out.append((m.start(), end.start() if end else len(text)))
    return out


def decision_of(header, body, consent=frozenset(), tms=(), addr=""):
    flat = re.sub(r"\s+", " ", body)
    if re.search(r"approved (?:by|through|via) (?:a )?consent|consent approval", flat + " " + header, re.I):
        return "Approved"
    if len(flat) < 120 and (set(tms) & consent or addr.lower() in consent):
        return "Approved"  # listed again under Business after the consent motion
    d = decide(body, bool(re.search(r"withdrawn", header, re.I)))
    if d == "Unknown":
        if re.search(r"provided comments|comments (?:were )?provided|no action|for comment", flat, re.I) \
                or re.search(r"preliminary|conceptual", header, re.I):
            return "Comments only"
        if re.search(r"\bdeferred\b", flat, re.I):
            return "Deferred"
        if re.search(r"moved to recommend (?:the )?approval", flat, re.I):
            return "Recommended approval"
        if re.search(r"moved to recommend (?:the )?denial", flat, re.I):
            return "Recommended denial"
    return d


def items(src):
    out = []
    for body_key, body_name in BODIES.items():
        for date, url, text in meetings(src, body_key):
            seen = {}
            consent = consent_set(text)
            section = ""
            ranges = staff_ranges(text)
            for header, body, page in segments(text):
                if SKIP.match(header) and not re.match(r"staff approval", header, re.I):
                    section = header.lower()
                    continue
                bullets = bullet_items(header, body)
                if bullets:  # "Staff approvals: ➢ 609 Pitt St ... ➢ 108 Beach St ...": one item each
                    for chunk in bullets:
                        ctms = tms_in(chunk, header=True)
                        out.append({"body": body_name, "date": date, "town": url, "page": page,
                                    "tms": ctms, "address": address_in(chunk), "kind": "Staff approval",
                                    "request": clean_request(chunk), "decision": "Approved by staff",
                                    "text": reflow(chunk)})
                    continue
                tms = tms_in(header, header=True) or tms_in(body[:300])
                addr = address_in(header)
                if not tms and not re.match(r"^\d", addr):
                    section = header.lower()  # a section heading, e.g. "7. Staff Approvals"
                    continue  # not tied to a property
                pos = text.find(header[:25])
                in_staff = any(a <= pos < b for a, b in ranges) if pos >= 0 else False
                staff = (section.startswith("staff approval") or in_staff) and not re.search(r"\bmoved\b", body)
                req = clean_request(header)
                it = {"body": body_name, "date": date, "town": url, "page": page,
                      "tms": tms, "address": addr, "kind": "Staff approval" if staff else kind_of(header),
                      "request": req,
                      "decision": "Approved by staff" if staff else decision_of(header, body, consent, tms, addr),
                      "text": reflow(body)}
                if "historic designation" in section and it["kind"] == "Design review":
                    it["kind"] = "Historic designation"
                # Consent items appear twice (consent list and business list): keep the fuller one.
                key = tuple(tms) or addr.lower()
                if key in seen:
                    prev = seen[key]
                    if len(it["text"]) <= len(prev["text"]):
                        continue
                    out.remove(prev)
                seen[key] = it
                out.append(it)
    return out


BULLET = re.compile(r"[➢•▪●]|(?:(?<=\S)\s[-–—]\s(?=\d{1,5}\s+[A-Z]))")


def clean_request(text):
    req = re.sub(r"\s+", " ", text)
    req = re.sub(r",?\s*(?:Survey(?: Card)?\s*\d*\s*/?\s*(?:Non-)?Historic|No Survey(?: Card)?\s*/?\s*(?:Non-)?Historic)\s*[–—-]?", " ", req, flags=re.I)
    req = re.sub(r"\(?\s*TMS\s*(?:No\.?|#)?\s*:?\s*[\d\s-]{10,16}\)?[.,]?", " ", req)
    req = re.sub(r"^Staff Approvals?:?\s*", "", req, flags=re.I)
    return re.sub(r"\s+", " ", req).strip(" ,.–—-")


def bullet_items(header, body):
    """A staff-approval list written as bullets, one property each. Returns the chunks, or []."""
    if not re.search(r"staff\s+(?:level\s+)?approvals?", header + " " + body[:200], re.I):
        return []
    flat = re.sub(r"\s+", " ", header + " " + body)
    flat = re.sub(r"^.*?staff\s+(?:level\s+)?approvals?[^➢•▪●\d]*", "", flat, count=1, flags=re.I)
    chunks = [c.strip(" ,.;–—-") for c in BULLET.split(flat)]
    chunks = [re.sub(r"\s*(?:Historic District Preservation Commission|[IVX]+\.\s.*)$", "", c) for c in chunks]
    chunks = [c for c in chunks if re.match(r"^\d{1,5}\s+\S", c)]
    return chunks if len(chunks) >= 2 else []


def split_by_house(its):
    """One parcel can carry two addresses (318 and 320 Morrison): keep them apart.
    Items without a house number join the address with the nearest date."""
    num = lambda it: (re.match(r"^(\d{1,5})\b", it["address"]) or [None, None])[1]
    nums = {num(it) for it in its} - {None}
    if len(nums) < 2:
        return [its]
    parts = {n: [it for it in its if num(it) == n] for n in nums}
    for it in its:
        if num(it) is None:
            best = min(nums, key=lambda n: min(abs(days(it["date"], x["date"])) for x in parts[n]))
            parts[best].append(it)
    return list(parts.values())


def days(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def main(src):
    groups = collections.defaultdict(list)
    for it in items(src):
        key = it["tms"][0] if it["tms"] else re.sub(r"[^a-z0-9]+", "-", it["address"].lower())
        groups[key].append(it)
    cases = []
    for its in [part for g in groups.values() for part in split_by_house(g)]:
        its.sort(key=lambda x: x["date"])
        project = [its[0]]
        for it in its[1:]:
            if days(project[-1]["date"], it["date"]) > 730:
                cases.append(project)
                project = []
            project.append(it)
        cases.append(project)
    out = []
    for proj in cases:
        last = proj[-1]
        kinds = [p["kind"] for p in proj]
        kind = "Demolition" if "Demolition" in kinds else next((k for k in reversed(kinds) if k != "Design review"), kinds[-1])
        out.append({
            "case": None, "board": "design", "kind": kind,
            "tms": list(dict.fromkeys(t for p in proj for t in p["tms"])),
            "label": next((p["address"] for p in reversed(proj) if re.match(r"^\d", p["address"])), last["address"]),
            "request": last["request"],
            "status": last["decision"],
            "events": [{"body": p["body"], "date": p["date"], "decision": p["decision"],
                        "page": p["page"], "town": p["town"], "text": p["text"]} for p in proj],
        })
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1])
