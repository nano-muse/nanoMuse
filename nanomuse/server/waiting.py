"""Date-bound promises of a reply in the main chat. Derive them from the current history."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from nanomuse.memory.store import tokenize

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DATE = re.compile(
    r"\b(?:the day after tomorrow|tomorrow|today|tonight|"
    rf"(?:(?:next week(?: on)?|next|this) )?(?:{'|'.join(_WEEKDAYS)})(?: next week)?)\b|(?<!\d)\d{{4}}-\d{{2}}-\d{{2}}(?!\d)"
    r"|大后天|后天|明[天早晚]|今[天晚]|(?:下|本|这)?(?:周|星期)(?:[一二三四五六日天])",
    re.I,
)
_CLOCK = re.compile(
    r"(?:(?:at\s+)?(?<![\d:])(?P<h>\d{1,2})(?::(?P<m>\d{2})\s*(?P<period>[ap]\.?m\.?)?|\s*(?P<ampm>[ap]\.?m\.?))(?![a-z0-9])"
    r"|(?P<cn_period>上午|中午|下午|晚上|早上|凌晨)?\s*(?P<cn_h>\d{1,2}|[零一二两三四五六七八九十]{1,3})"
    r"\s*[点點时時](?:(?P<half>半)|(?P<cn_m>\d{1,2})分)?)",
    re.I,
)
_FOREIGN_TIME = re.compile(
    r"\b(?:UTC|GMT|[PMCE][DS]T|CET|CEST|BST|IST|JST|HKT|SGT|AEST|AEDT)(?:[+-]\d+)?\b|北京时间|纽约时间|美东时间|伦敦时间"
)


def _clock(text: str) -> time | None:
    clock = _CLOCK.search(text)
    if clock is None:
        return None
    raw = clock["cn_h"] or clock["h"]
    if raw.isdecimal():
        hour = int(raw)
    else:
        digits = "零一二三四五六七八九"
        raw = raw.replace("两", "二")
        tens, sep, ones = raw.partition("十")
        if any(len(v) > 1 for v in (tens, ones)) or any(c not in digits for c in tens + ones):
            return None
        hour = (
            (10 * (digits.index(tens) if tens else 1) + (digits.index(ones) if ones else 0))
            if sep
            else digits.index(raw)
        )
    minute = 30 if clock["half"] else int(clock["m"] or clock["cn_m"] or 0)
    period = (clock["period"] or clock["ampm"] or clock["cn_period"] or "").lower().replace(".", "")
    if hour > 23 or minute > 59 or (period and not 1 <= hour <= 12):
        return None
    if period in ("am", "上午", "早上", "凌晨"):
        hour %= 12
    elif period in ("pm", "中午", "下午", "晚上"):
        hour = hour % 12 + 12
    return time(hour, minute)


def _unclear_clock(text: str) -> bool:
    matches = list(_CLOCK.finditer(text))
    return bool(matches) and (len(matches) > 1 or _clock(text) is None)


def _without_schedule(text: str) -> str:
    return _CLOCK.sub("", _DATE.sub("", text))


_WAIT = re.compile(
    r"^(?:i(?:'m|’m| am) (?:still )?waiting (?:for|on) |我(?:还在|正在|在|还)?等待?\s*)", re.I
)
_TRANSFER = re.compile(
    r"^(?P<sender>.{1,60}?)\bto (?:send|share|return|confirm|provide|deliver) (?:me |us )?", re.I
)
_CN_TRANSFER = re.compile(
    r"^(?P<sender>.{1,24}?)(?:发给我|发来|给我发|寄来|提供|给我寄|发回|确认一下|回复我)\s*"
)
_DELIVERY = re.compile(
    r"\b(?:reply|response|quote|estimate|approval|confirmation|feedback|proposal|report|invoice|"
    r"results?|answer|to (?:send|share|return|confirm|provide|deliver))\b"
    r"|回信|回复|答复|报价|反馈|审批|确认|单据|发票|报告|结果|发来|发给我|给我发|寄来|提供",
    re.I,
)
_CLOSE = re.compile(
    r"^(?:just |already )?(?:got|received)\b|\b(?:I|we)(?:'ve|’ve| have)? (?:already |just )?(?:received|got|cancelled|canceled)\b"
    r"|\b(?:came in|arrived|called off|no longer waiting)\b|收到(?:了|啦)|已(?:经)?收到|到手了|不用(?:再)?等|不等了|已(?:经)?取消",
    re.I,
)
_MOVE = re.compile(
    r"\b(?:moved|move|pushed|postponed|rescheduled|changed|delayed) (?:it |back )?(?:until|to)\b"
    r"|改(?:期|为|成|到)|推迟(?:到|至)|延至|延期到",
    re.I,
)
_UNCERTAIN = re.compile(
    r"\b(?:if|whether|unless|maybe|might|not yet|haven['’]t|hasn['’]t|didn['’]t|never|not (?:received|cancelled|canceled|moved|postponed))\b"
    r"|如果|假如|要是|可能|没(?:有)?(?:收|改|取消)|还没|是否|[?？]",
    re.I,
)
_SKIP = set(
    "the a an of for on to my our me from supplier vendor send received got by quote update"
    " reply about waiting it just please already changed moved until have with this that".split()
)
_SKIP.update({"报价", "回信", "收到", "回复", "供应", "应商", "时间", "推迟", "改到", "确认"})
_OBJECTS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\b(?:quote|estimate|quotation)s?\b|报价",
        r"\binvoices?\b|发票",
        r"\breports?\b|报告",
        r"\b(?:approvals?|permission)\b|审批",
        r"\bconfirmations?\b|确认",
        r"\bproposals?\b|提案",
        r"\bresults?\b|结果",
        r"\b(?:reminders?|tickets?|itinerar(?:y|ies))\b|提醒|行程单",
    )
)
_BARE = re.compile(
    r"^(?:(?:i(?:'ve| have)? |we |just |already )*(?:got|received) (?:it|that)|it (?:arrived|came in)"
    r"|(?:it(?:'s| is| was) |they |we )?(?:moved|move|changed|pushed|postponed|rescheduled|delayed) "
    r"(?:it |back )?(?:to|until)\s*|(?:我|我这边)?(?:已经|已|刚刚|刚)?收到(?:了|啦)|不用再等(?:了)?|不等了"
    r"|(?:他们|对方|日期|时间|那就|这件事)?(?:说)?(?:改到|改成|推迟到|延期到))$",
    re.I,
)


def _subject_words(text: str) -> set[str]:
    text = _without_schedule(text)
    for kind in _OBJECTS:
        text = kind.sub(" ", text)
    return tokenize(text) - _SKIP


def _due(text: str, observed: date) -> date | None:
    matches = list(_DATE.finditer(text))
    if len(matches) != 1:
        return None  # "Friday or Monday" does not give us an agreed date
    match = matches[0]
    if re.search(r"\b(?:last|previous)\s*$|上(?:个|個)?$", text[: match.start()], re.I):
        return None
    word = match[0].lower()
    if word[0].isdigit():
        try:
            return date.fromisoformat(word)
        except ValueError:
            return None
    if "next week" in word:
        weekday = next(day for day in _WEEKDAYS if day in word)
        word = "next " + weekday
    if word.endswith(_WEEKDAYS):
        index = _WEEKDAYS.index(word.split()[-1])
    elif "周" in word or "星期" in word:
        index = "一二三四五六日".index(word[-1].replace("天", "日"))
    else:
        offset = (
            3
            if word == "大后天"
            else 2
            if word in ("后天", "the day after tomorrow")
            else int(word.startswith(("明", "tomorrow")))
        )
        return observed + timedelta(days=offset)
    if word.startswith(("next ", "下")):
        return observed + timedelta(days=7 - observed.weekday() + index)
    if word.startswith(("this ", "本", "这")):
        return observed + timedelta(days=index - observed.weekday())
    return observed + timedelta(days=(index - observed.weekday()) % 7)


def personal_message(event: dict[str, Any]) -> bool:
    return (
        event.get("type") == "user"
        and not event.get("synced")
        and event.get("source") in (None, "", "user")
        and not any(name in event for name in ("via", "via_device", "to_device"))
    )


_SHORT_TRANSFER = re.compile(
    r"^(?P<sender>.{1,22}?(?:方|商|室|公司|团队|同事|老师))(?:给我|发(?!票))(?=.{0,14}(?:报价|报告|回复|反馈|发票|结果))"
)


def _sender_and_subject(text: str) -> tuple[str, str]:
    text = _without_schedule(_WAIT.sub("", text, count=1))
    text = re.split(r"[,，;；。.!！]|\s+from\s+", text, maxsplit=1, flags=re.I)[0]
    sender = ""
    for transfer in (_TRANSFER, _CN_TRANSFER, _SHORT_TRANSFER):
        if match := transfer.match(text.strip()):
            sender = match["sender"].strip()
            text = text.strip()[match.end() :]
            break
    item = re.sub(r"(?:\s+\b(?:on|by|until|before)|之?前|之前发来)$", "", text.strip(), flags=re.I)
    return sender, item.strip(" ，。")[:120]


@dataclass(frozen=True)
class Waiting:
    source: str
    quote: str
    subject: str
    due: date
    correction: str = ""
    clock: time | None = None
    sender: str = ""

    @property
    def key(self) -> str:
        material = "\0".join((self.source, self.quote, self.due.isoformat(), str(self.clock or "")))
        return "wait_" + hashlib.sha256(material.encode()).hexdigest()

    def ready(self, now: datetime) -> bool:
        days = (now.date() - self.due).days
        return 0 <= days <= 3 and (days > 0 or self.clock is None or now.time() >= self.clock)

    def card(self) -> dict[str, str]:
        return {
            "kind": "waiting",
            "id": self.key,
            "quote": self.quote,
            "subject": self.subject,
            "sender": self.sender,
            "due": self.due.isoformat(),
            "correction": self.correction,
            "time": self.clock.strftime("%H:%M") if self.clock else "",
        }


def waiting_for(timeline: list[dict[str, Any]], now: datetime) -> tuple[list[Waiting], set[str]]:
    """Keep independent matters separate. A bare 'got it' needs an unambiguous preceding turn."""
    pending: dict[str, Waiting] = {}
    consumed: set[str] = set()
    focus: str | None = None
    last_focus_time: datetime | None = None
    assistant_spoke = False
    for event in timeline[-300:]:
        if event.get("type") == "assistant" and event.get("text"):
            # "Got it" after an assistant's own answer can just acknowledge that answer.
            assistant_spoke = True
        if event.get("type") != "user":
            continue
        previous, focus = focus, None
        after_reply, assistant_spoke = assistant_spoke, False
        if not personal_message(event) or event.get("files"):
            continue
        key, text = event.get("id"), event.get("text")
        if (
            not isinstance(key, str)
            or not isinstance(text, str)
            or not 2 <= len(text.strip()) <= 400
        ):
            continue
        text = text.strip()
        try:
            stamp = datetime.fromisoformat(event["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        when = (stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)).astimezone(now.tzinfo)
        if not timedelta(0) <= now - when <= timedelta(days=28) or _UNCERTAIN.search(text):
            continue
        if _WAIT.match(text):
            # A later sentence about a different day is not a deadline. Keep the
            # source punctuation and EN time abbreviations in the displayed quotation.
            # Mask the periods in "p.m." without changing character offsets.
            masked = re.sub(r"\b([ap])\.m\.", r"\1 m ", text, flags=re.I)
            boundary = re.search(r"[。!！\n]|\.(?=\s|$)", masked)
            sentence = text[: boundary.end()].strip() if boundary else text
            if (
                not _DELIVERY.search(sentence)
                or _FOREIGN_TIME.search(sentence)
                or _unclear_clock(sentence)
            ):
                continue
            due = _due(sentence, when.date())
            sender, subject = _sender_and_subject(sentence)
            if due and 0 <= (due - when.date()).days <= 21 and len(subject) >= 2:
                # Repeating the same wait does not create a second reminder. Keep both
                # the recipient and subject in the comparison, even for identical quotes.
                identity = _without_schedule(sentence).rstrip(" ,，。.!！").casefold()
                same = next(
                    (
                        w
                        for w in pending.values()
                        if _without_schedule(w.quote).rstrip(" ,，。.!！").casefold() == identity
                    ),
                    None,
                )
                if same is None:
                    pending[key] = Waiting(
                        key, sentence, subject, due, clock=_clock(sentence), sender=sender
                    )
                    focus = key
                else:
                    if due != same.due or _clock(sentence) != same.clock:
                        pending[same.source] = replace(
                            same, due=due, correction=sentence, clock=_clock(sentence)
                        )
                    focus = same.source
                consumed.add(key)
                last_focus_time = when
            continue
        closing, moving = _CLOSE.search(text), _MOVE.search(text)
        if not (closing or moving) or re.search(r"still waiting|还在等|仍在等", text, re.I):
            continue
        bare = _without_schedule(text).strip(" ,，。.!！")
        if _BARE.fullmatch(bare):
            target = (
                previous
                if len(pending) == 1
                and (moving or not after_reply)
                and last_focus_time
                and when - last_focus_time <= timedelta(days=2)
                else None
            )
        else:
            # A shared document type alone must not match differently named things,
            # e.g. "the Atlas report" and "the Fjord report".
            words = _subject_words(text)
            objects = {obj for obj in _OBJECTS if obj.search(text)}
            scores = []
            for k, w in pending.items():
                expected = {obj for obj in _OBJECTS if obj.search(w.subject)}
                if objects and expected and objects.isdisjoint(expected):
                    continue
                specific = _subject_words(w.subject)
                overlap = len(words & specific)
                sender_named = len(w.sender) >= 2 and w.sender.casefold() in text.casefold()
                if overlap or (objects & expected and not specific and (sender_named or not words)):
                    scores.append((2 * overlap + int(sender_named), k))
            scores.sort(reverse=True)
            target = (
                scores[0][1]
                if scores and (len(scores) == 1 or scores[0][0] > scores[1][0])
                else None
            )
        if target is None or target not in pending:
            continue
        consumed.add(key)
        if (
            closing
            or _FOREIGN_TIME.search(text)
            or _unclear_clock(text)
            or not (updated := _due(text, when.date()))
        ):
            del pending[target]  # An indefinite postponement also retires the old date.
        else:
            pending[target] = replace(
                pending[target], due=updated, correction=text, clock=_clock(text)
            )
            focus = target
            last_focus_time = when
    return list(pending.values()), consumed
