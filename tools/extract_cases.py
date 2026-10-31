"""Extract individual zoning cases from Board of Zoning Appeals minutes.

Input:  a directory of `YYYY-MM-DD.txt` files produced by
        `pdftotext -layout minutes/YYYY-MM-DD.pdf`.
Output: JSON list of hearings on stdout, one entry per case heard at a meeting.

Each minutes file lists business items like:
    1. Case V-06-25, 683 Linns Point, TMS# 559-02-00-233, Request for relief ...
Older minutes drop the word "Case" and sometimes the "TMS" label. The parser
finds those headers, cuts the text between headers into per-case sections, and
reads the motions in each section to infer the decision.
"""
import json
import os
import re
import sys

CASE_ID = r"(?P<id>[AVSR])\s?-\s?(?P<n>\d{1,2})\s?-\s?(?P<y>\d{2,4})"
HEADER = re.compile(
    r"^\s{0,12}(?:[0-9]{1,2}\.|[A-Za-z]\.)?\s*"
    r"(?P<pre>(?:Request for [^,]{0,60}?(?:,|of|for)\s*)?)"
    r"(?:Case\s*(?:No\.?|#)?\s*)?" + CASE_ID + r"\s*[,.]\s*(?P<rest>.*)$"
)
TMS = re.compile(r"(\d{3})\s?-?\s?(\d{2})\s?-?\s?(\d{2})\s?-?\s?(\d{3})")
PAGE_FURNITURE = re.compile(
    r"^\s*(Board of Zoning Appeals|Page \d+ of \d+|"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December) \d{1,2}, \d{4})\s*$",
    re.I,
)
SECTION_END = re.compile(
    r"^\s*(?:[A-Z0-9]{1,2}\.\s*)?(Approval of Final Orders|Final Orders|Adjourn|"
    r"Other Business|Miscellaneous|There being no further business|"
    r"Respectfully submitted)",
    re.I,
)
KIND = {"V": "Variance", "A": "Appeal", "S": "Special exception", "R": "Rehearing"}


def norm_case(m):
    y = m.group("y")
    y = y[-2:] if len(y) == 4 else y
    return f"{m.group('id')}-{int(m.group('n')):02d}-{y}"


def clean_lines(text):
    """Return (line, page) pairs with page headers/footers removed."""
    out = []
    for page_no, page in enumerate(text.split("\f"), start=1):
        for line in page.splitlines():
            if PAGE_FURNITURE.match(line):
                continue
            out.append((line.rstrip(), page_no))
    return out


def header_block(lines, i):
    """Join the header line with its continuation lines (until a blank line)."""
    parts = [lines[i][0].strip()]
    j = i + 1
    while j < len(lines) and lines[j][0].strip() and len(parts) < 8:
        s = lines[j][0].strip()
        if (re.match(r"^(Mr|Ms|Mrs|Dr)\.\s", s) or HEADER.match(lines[j][0])
                or re.match(r"^(Correspondence|Staff Report|Staff Comments)\b", s, re.I)):
            break
        parts.append(s)
        j += 1
    return " ".join(parts), j


ADDR_STOP = re.compile(r"\bTMS\b|,|\(|WITHDRAWN|\b\d{3}-\d{2}|\.\s+(?=Request|Appeal)", re.I)


def parse_header(block):
    m = HEADER.match(block)
    rest = m.group("rest")
    tms_m = TMS.search(rest)
    tms = "-".join(tms_m.groups()) if tms_m else None
    # Address: text up to the first comma / TMS label.
    addr = ADDR_STOP.split(rest, maxsplit=1)[0].strip(" .;:")
    if not addr or addr[0].islower() or re.search(r"accordance|request|to allow", addr, re.I):
        addr = ""  # extension items carry no address; the build step inherits it
    # Request: text after the TMS number (or after the address).
    req = rest[tms_m.end():] if tms_m else rest[len(addr):]
    req = re.sub(r"^[\s.,;:]+", "", req)
    req = re.sub(r"\s+", " ", req).strip()
    req = re.sub(r"\s*\b(Correspondence|Staff Report|Staff Comments)\s*$", "", req, flags=re.I)
    pre = m.group("pre").lower()
    item = "hearing"
    if "rehearing" in pre:
        item = "rehearing request"
    elif "extension" in pre:
        item = "extension request"
    return {
        "case": norm_case(m),
        "address": re.sub(r"\s+", " ", addr),
        "tms": tms,
        "request": req,
        "item": item,
        "withdrawn": bool(re.search(r"withdrawn", block, re.I)),
    }


MOTION = re.compile(
    r"(?:moved|made a motion|motion was made)\s+(?:for|to|that)\s+(?:the\s+)?(?:a\s+)?"
    r"(?P<verb>approv\w*|den\w*|defer\w*|grant\w*|continu\w*|uph\w*|revers\w*|"
    r"overturn\w*|table\w*|withdr\w*|accept\w*|amend\w*)",
    re.I,
)
FAILED = re.compile(r"motion (?:failed|died)|failed on a|died for lack|failed for lack", re.I)
DEFER_OBJ = re.compile(
    r"^\W*(?:of|for)?\s*(?:the\s+|a\s+)?(?:applicant.s\s+)?(?:request(?:ed)?\s+(?:for\s+)?)?"
    r"(?:deferral|continuance|deferment|postponement)",
    re.I,
)


def decide(body, withdrawn):
    """Infer the decision from the last motion in a case section that did not fail."""
    if withdrawn:
        return "Withdrawn"
    flat = re.sub(r"\s+", " ", body)
    motions = list(MOTION.finditer(flat))
    result = None
    for k, m in enumerate(motions):
        stop = motions[k + 1].start() if k + 1 < len(motions) else len(flat)
        tail = flat[m.end():stop]
        verb = m.group("verb").lower()
        if verb.startswith("amend") or FAILED.search(tail[:1500]):
            continue
        cond = bool(re.search(
            r"with (?:the )?(?:following )?(?:conditions?|stipulations?)|subject to|"
            r"on the condition|conditioned (?:up)?on|provided that|contingent (?:up)?on",
            tail[:700], re.I))
        if verb.startswith(("approv", "grant", "accept")):
            if DEFER_OBJ.match(tail[:60]):
                result = "Deferred"
            else:
                result = "Approved with conditions" if cond else "Approved"
        elif verb.startswith("den"):
            result = "Denied"
        elif verb.startswith(("defer", "continu", "table")):
            result = "Deferred"
        elif verb.startswith("uph"):
            result = "Upheld"
        elif verb.startswith(("revers", "overturn")):
            result = "Reversed"
        elif verb.startswith("withdr"):
            result = "Withdrawn"
    if result is None:
        if re.search(r"should be upheld|be upheld|is upheld", flat, re.I):
            result = "Upheld"
        elif re.search(r"\bdismissed\b", flat, re.I):
            result = "Dismissed"
        elif re.search(r"rehearing was denied", flat, re.I):
            result = "Denied"
        elif re.search(r"no variance is needed|variance is not needed|no longer needed", flat, re.I):
            result = "Not needed"
        elif re.search(r"deadlock|tie vote|no action was taken", flat, re.I):
            result = "No decision"
        elif re.search(r"withdr[ae]wn|withdrawal|request(?:ed)? to withdraw", flat, re.I):
            result = "Withdrawn"
        elif re.search(r"\b(deferred|continued|continuance|deferral)\b", flat, re.I):
            result = "Deferred"
    return result or "Unknown"


def reflow(body):
    """Join PDF layout lines back into paragraphs (blank line = paragraph break)."""
    paras = re.split(r"\n\s*\n", body)
    return "\n\n".join(re.sub(r"\s+", " ", p).strip() for p in paras if p.strip())


def extract(path, date):
    text = open(path, encoding="utf-8", errors="replace").read()
    lines = clean_lines(text)
    heads = []
    i = 0
    while i < len(lines):
        line = lines[i][0]
        if HEADER.match(line) and not re.search(r"moved|seconded", line, re.I):
            block, j = header_block(lines, i)
            if HEADER.match(block):
                heads.append((i, j, block))
                i = j
                continue
        i += 1
    cases = []
    for k, (start, body_start, block) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        for t in range(body_start, end):
            if SECTION_END.match(lines[t][0]):
                end = t
                break
        h = parse_header(block)
        body = "\n".join(l for l, _ in lines[body_start:end]).strip()
        decision = decide(body, h["withdrawn"])
        body = re.sub(r"\n{3,}", "\n\n", body)
        cases.append({
            **h,
            "kind": KIND[h["case"][0]],
            "decision": decision,
            "date": date,
            "page": lines[start][1],
            "header": re.sub(r"\s+", " ", block),
            "text": reflow(body),
        })
    for k, c in enumerate(cases):
        if c["decision"] == "Unknown" and len(c["text"]) < 40 and k + 1 < len(cases):
            nxt = cases[k + 1]
            if nxt["case"] == c["case"] or (c["tms"] and nxt["tms"] == c["tms"]):
                c["decision"] = nxt["decision"]
                c["note"] = f"Heard together with {nxt['case']}; see that entry."
    return cases


def main(src):
    out = []
    for name in sorted(os.listdir(src)):
        if name.endswith(".txt"):
            out.extend(extract(os.path.join(src, name), name[:-4]))
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1])
