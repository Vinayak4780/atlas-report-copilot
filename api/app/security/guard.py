"""Deterministic input guard: runs before any retrieval or LLM call.

Catches the cases where a wrong answer is dangerous (data modification, confidential data,
other clients, injection in the question) and obvious out-of-scope topics, with a reason the
client can read. Anything not caught here goes to the router.
"""
import re
from dataclasses import dataclass

from app.security.injection import find_injection

WRITE_RE = re.compile(
    r"\b(delete|drop|truncate|insert|alter|grant|revoke|wipe|erase|purge|overwrite)\b[\s\S]{0,60}"
    r"\b(rows?|tables?|database|db|records?|entries|schema)\b"
    r"|\bupdate\b[\s\S]{0,40}\b(tables?|rows?|records?|database|set)\b"
    r"|\b(drop\s+table|delete\s+from|insert\s+into|truncate\s+table|alter\s+table|create\s+(table|user))\b",
    re.IGNORECASE,
)
PII_RE = re.compile(
    r"\b(list|show|give|share|print|reveal|tell|send|dump|export|what(?:'s| is| are)|find)\b[\s\S]{0,50}"
    r"\b(e-?mails?|e-?mail address(es)?|contact (details|info|information|emails?)|phone numbers?|"
    r"personal (data|details|information)|home address(es)?|passwords?|api keys?|credentials)\b"
    r"|\b(clients?|customers?)\b[\s\S]{0,30}\b(e-?mails?|contacts?|phone)\b",
    re.IGNORECASE,
)
OTHER_CLIENTS_RE = re.compile(
    r"\b(other|another|which|what|who|all|your)\s+(clients?|customers?)\b[\s\S]{0,50}"
    r"\b(bought|purchased|buy|buys|subscribe[sd]?|own|have|has)\b"
    r"|\bwho else\b[\s\S]{0,30}\b(bought|purchased|subscribe)"
    r"|\b(clients?|customers?)\s+(list|table)\b"
    r"|\bwho (has )?(bought|purchased)\b",
    re.IGNORECASE,
)
POLITICS_RE = re.compile(
    r"\b(elections?|electoral|voting|vote for|ballot|political|politics|politicians?|prime minister|"
    r"presidential|parliament(ary)?|senators?|democrats?|republicans?|bjp|congress party|left[- ]wing|right[- ]wing)\b",
    re.IGNORECASE,
)
ESCALATION_RE = re.compile(
    r"\b(escalate|talk to (an? )?(human|analyst|person)|speak (to|with) (an? )?(human|analyst|person)|"
    r"human analyst|connect me (to|with) (an? )?analyst|real analyst)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GuardVerdict:
    route: str          # unsafe | out_of_scope | escalation_request
    kind: str           # finer reason, drives the refusal text
    reason: str         # human readable, also logged
    security_event: bool


def check_question(question: str, own_company: str, other_companies: list[str]) -> GuardVerdict | None:
    hit = find_injection(question)
    if hit:
        return GuardVerdict("unsafe", "prompt_injection", f"Instruction-override attempt: '{hit}'", True)
    if WRITE_RE.search(question):
        return GuardVerdict("unsafe", "data_modification", "Request to modify or delete data", True)
    if PII_RE.search(question):
        return GuardVerdict("unsafe", "personal_data", "Request for confidential or personal data", True)
    q_lower = question.lower()
    named_other = [c for c in other_companies if c and c.lower() in q_lower and c.lower() != own_company.lower()]
    if named_other or OTHER_CLIENTS_RE.search(question):
        detail = f"Asked about other clients: {', '.join(named_other)}" if named_other else "Asked about other clients"
        return GuardVerdict("out_of_scope", "other_clients", detail, True)
    if POLITICS_RE.search(question):
        return GuardVerdict("out_of_scope", "politics", "Political topic", False)
    if ESCALATION_RE.search(question):
        return GuardVerdict("escalation_request", "client_request", "Client asked for a human analyst", False)
    return None
