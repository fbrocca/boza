"""Does a Town Council item really belong to a Planning Commission case?

Council minutes describe ordinances in their own words ("a parcel located on Klink
Lane"), so matching is fuzzy. A Council item is kept on a case when its text names
the case number, a TMS, a house number from the case, two shared place/project
names (or one long one), or the same street with a compatible acreage.
"""
import re

SUF = r"(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Boulevard|Blvd|Avenue|Ave|Court|Ct|Way|Circle|Highway|Hwy|Parkway|Pkwy|Place|Trail|Point|Bluff|Landing)"
GEN = set("""request amend amendment planned development district ordinance zone zoning rezone parcel parcels
acre acres located approximately tract land charleston county plat book page recorded office identified residential
business areawide commercial community conservation public institutional professional density medium town council
planning commission committee mount pleasant road street drive lane boulevard highway avenue court north south east
west the and for with from into within portion corner known between subject proposal proposed property properties
annex annexation providing pertaining specifically unincorporated designation future use comprehensive plan
settlement minutes first second final reading general""".split())


def names(t):
    return {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z’']{3,}\b", t)} - GEN


def streets(t):
    return {re.sub(r"[’'s]+$", "", m.group(1).lower())
            for m in re.finditer(r"\b([A-Z][a-zA-Z’']{2,})\s+" + SUF + r"\b", t)} - {"north", "south", "old", "the"}


def acres(t):
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*-?\s*acres?\b", t)]


def pd_names(t):
    """Planned-development names, e.g. 'north point', 'central mount pleasant'."""
    t = re.sub(r"\bMt\.?\s", "Mount ", t)
    return {re.sub(r"\s+", " ", m.group(1).lower()) for m in
            re.finditer(r"((?:[A-Z][\w’']+\s+){1,4})(?:PD\b|Planned Development)", t)}


def belongs(case_no, tms, request, label, text):
    t = re.sub(r"\s+", " ", text)
    digits = re.sub(r"\D", "", t)
    if case_no and re.search(re.escape(case_no).replace(r"\-0", r"\-0?"), t):
        return "case"
    for x in tms:
        if x.replace("-", "") in digits or x in t:
            return "tms"
    src = request + " " + label
    for m in re.finditer(r"\b(\d{3,5})\s+(?:[NSEW]\.?\s+|North\s+|South\s+)?[A-Z]", src):
        if re.search(r"(?<![\d.,-])" + m.group(1) + r"\s+[A-Z]", t):
            return "addr"
    if pd_names(src) & pd_names(t):
        return "pd"
    shared = names(src) & names(t)
    if len(shared) >= 2 or any(len(w) >= 6 for w in shared):
        return "names"
    if streets(src) & streets(t):
        a, b = acres(src), acres(t[:600])
        if not a or not b or any(abs(x - y) <= 0.1 * max(x, y) + 0.05 for x in a for y in b):
            return "street"
    return None
