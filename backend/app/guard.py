"""Guard node logic: deterministic, zero-token screening before any LLM call.

* Prompt injection / data-exfiltration attempts -> refused.
* Clearly off-topic requests (no property/car signal at all) -> refused.
* Short yes/no replies while a risky action is pending -> routed to the approval node.
Anything ambiguous passes through; the main agent's system prompt also refuses off-topic asks.
"""
import re

INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|rules?|prompts?|guidelines?|polic(y|ies)|guardrails?)\b",
    r"\bsystem\s*prompt\b",
    r"\b(reveal|show|print|repeat|leak|output|display|tell me)\b.{0,40}\b(your|the|hidden|initial|internal)\b.{0,20}\b(prompt|instructions?|rules|config(uration)?)\b",
    r"\byou are now\b|\bfrom now on you (are|will)\b|\bpretend (to be|you are)\b|\broleplay as\b|\bact as (an? )?(unrestricted|different|new|evil)\b",
    r"\b(developer|dev|god|admin|debug)\s+mode\b|\bjailbreak\b|\bDAN\b|\bsudo\b",
    r"\b(show|list|give|send|export|dump|see|view|access|share|reveal|get)\b.{0,40}\b(all|every)\b\s+(the\s+|of the\s+)?(leads?|users?|customers?|clients?|buyers?|phone numbers?|contacts?|records?|bookings? of|visits? of)\b",
    r"\b(other|another|different|someone else'?s?)\s+(users?|customers?|clients?|people|person|buyers?)('s|s')?\b.{0,40}\b(data|bookings?|visits?|leads?|phone|numbers?|details|info|history|chats?|profile|budget)\b",
    r"\b(other|another|different|competitor)\s+(agenc(y|ies)|dealers?|dealerships?)('s|s')?\b.{0,40}\b(data|leads?|customers?|clients?|buyers?|bookings?)\b",
    r"\b(show|list|give|export|dump)\b.{0,15}\b(leads?)\b",
    r"\b(show|give|list|share|send|export|reveal|tell)\b.{0,50}('s|s'|\btheir|\byour|\ball|\bother|\bevery)\s+(customers|clients|buyers|visitors|leads)\b",
    r"\b(agency|dealer)\s+[a-z0-9]+('s)?\s+(data|leads?|customers?|clients?|bookings?)\b",
    r"\b(leads? list|customer list|customer database|user database|admin (panel|password|access|dashboard))\b",
    r"\b(drop|truncate|delete\s+from)\s+(table\s+)?\w+|\bunion\s+select\b|;\s*--",
    r"</?\s*(system|assistant|instructions?)\s*>|\[/?(INST|SYS)\]|^\s*#{2,}\s*(system|instruction)",
    r"\bnew instructions?\s*:",
]

OFF_TOPIC_PATTERNS = [
    r"\b(poem|poetry|haiku|song|lyrics|rap|essay|story|novel|joke|riddle|limerick)\b",
    r"\b(recipe|cook|cooking|bake)\b",
    r"\b(homework|assignment|exam|quiz|thesis)\b",
    r"\b(python|javascript|java|c\+\+|html|css|sql|code|coding|program|script|function|algorithm|debug)\b",
    r"\b(translate|translation)\b",
    r"\b(weather|forecast|temperature)\b",
    r"\b(cricket|football|match|score|movie|film|netflix|celebrity|actor|singer|game|gaming)\b",
    r"\b(capital of|who (is|was|invented|discovered)|history of|meaning of life|philosophy)\b",
    r"\b(solve|equation|calculus|integral|derivative|math problem)\b",
    r"\b(bitcoin|crypto|stock market|forex|shares)\b",
    r"\b(medical|medicine|diagnos\w*|symptoms?|doctor|disease|politics?|election|religion)\b",
]

# Words that show the message is (at least partly) about our domain.
DOMAIN_PATTERN = re.compile(
    r"\b(propert(y|ies)|plots?|house|home|homes|apartment|flat|villa|marla|kanal|sq ?ft|commercial|shop|office|"
    r"rent|buy|sell|selling|purchase|invest(ment)?|dha|bahria|gulberg|phase|sector|society|possession|"
    r"cars?|gaa?ri|vehicle|sedan|suv|hatchback|pickup|test ?drive|drive|mileage|km|automatic|manual|"
    r"toyota|honda|suzuki|kia|hyundai|haval|mg|corolla|civic|city|yaris|alto|cultus|swift|wagon|sportage|"
    r"tucson|fortuner|hilux|elantra|"
    r"lakh|lac|crore|cr|pkr|rs|price|budget|installment|financ\w*|loan|lease|down ?payment|"
    r"visit|book|booking|appointment|schedule|dealer|agent|listing|listings|showroom|viewing)\b",
    re.IGNORECASE,
)

YES_PATTERN = re.compile(
    r"^\s*(yes|y|yeah|yep|yup|ya|sure|ok|okay|okk?|confirm(ed)?|correct|right|go ahead|do it|book it|please do|"
    r"proceed|absolutely|definitely|done|haan|han|ji|ji haan|theek|theek hai|thik hai|perfect|great|sounds good)\b"
    r"[\s,.!]*(please|confirm(ed)?|book it|go ahead|do it|thanks|thank you|sure|ji)?[\s.!]*$",
    re.IGNORECASE,
)
NO_PATTERN = re.compile(
    r"^\s*(no|n|nope|nah|cancel|stop|don'?t|do not|not now|never ?mind|wait|hold on|nahi|nahin|na)\b",
    re.IGNORECASE,
)

_inj = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in INJECTION_PATTERNS]
_off = [re.compile(p, re.IGNORECASE) for p in OFF_TOPIC_PATTERNS]

REFUSE_INJECTION = ("I can't do that. I only help you find properties and cars, book visits or test drives, "
                    "and manage your own bookings. I can't change my rules or share other customers' or "
                    "dealers' data. What are you looking to buy?")
REFUSE_OFF_TOPIC = ("Sorry, I can only help with buying property or cars on DealDesk: finding listings, "
                    "financing estimates, and booking site visits or test drives. "
                    "Are you looking for a property or a car?")


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in _inj)


def looks_off_topic(text: str) -> bool:
    if DOMAIN_PATTERN.search(text):
        return False
    return any(p.search(text) for p in _off)


def classify_confirmation(text: str) -> str | None:
    """'yes' / 'no' for short confirmation replies, else None."""
    t = text.strip()
    if len(t) > 60:
        return None
    if NO_PATTERN.search(t):
        return "no"
    if YES_PATTERN.search(t):
        return "yes"
    return None
