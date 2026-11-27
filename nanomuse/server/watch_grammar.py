"""Shared vocabulary for public-source discovery in the runtime and phone apps."""

import re

# A bounded ASCII token prevents surrounding Chinese punctuation/text becoming part of an ID.
_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_./@-])(?:"
    r"(?:(?:https?://)|(?:github\.com/|doi\.org/|openalex\.org/|orcid\.org/|scholar\.google\.com/))"
    r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,%=;-]+"
    r"|10\.[0-9]{4,9}/[A-Za-z0-9._:;()/-]+"
    r"|(?:[0-9]{4}-){3}[0-9]{3}[0-9X](?![A-Za-z0-9_])"
    r"|A[1-9][0-9]{0,14}(?![A-Za-z0-9_]))",
    re.I,
)
_LOGIN = r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*"
_RESERVED = frozenset(
    "about account accounts apps collections contact customer-stories dashboard discussions "
    "enterprise events explore features gist gists github-sponsors issues join login logout "
    "marketplace new notifications orgs organizations pricing projects pulls readme search "
    "security sessions settings site sponsors stars topics trending users watch".split()
)
_QUOTED = re.compile(
    r"""(?:"|“|”|「|」|『|』|\x60|\b(?:forwarded message|quoted text|quote from|"""
    r"""he said|she said|they said|for example|sample text|translate this)\b|"""
    r"""如下示例|以下是示例|以下是转发|转发邮件|[他她]说|例如|举例|翻译[以下这])""",
    re.I,
)
_UNCERTAIN = re.compile(
    r"\b(?:if|unless|suppose|hypothetically|pretend|maybe|might|possibly|private|"
    r"not|never|no longer|stop|unfollow|don't|don’t|isn't|isn’t|used to)\b|"
    r"如果|假如|假设|可能|或许|不是|并非|别再|不要|不用|不再|不想|取消|停止|私有|私人链接|以前|曾经",
    re.I,
)
_SUBJECT = (
    r"(?:public\s+)?(?:github(?:\s+(?:account|username|handle|login|profile|repo(?:sitory)?|project))?|"
    r"repo(?:sitory)?|open[- ]source project|project|paper|article|doi|orcid(?:\s+(?:id|profile))?|openalex(?:\s+(?:id|profile))?|"
    r"google scholar(?:\s+profile)?|scholar profile|research profile|rss(?:\s+feed)?|atom feed|"
    r"website|site|feed|publication|blog(?:\s+feed)?)"
)
_ZSUBJECT = (
    r"(?:(?:github|openalex|orcid|google\s*scholar|谷歌学术|谷歌学者|谷歌学術|rss|atom)\s*)?"
    r"(?:(?:开源|学术|研究者|作者|个人|公开|订阅)\s*)?"
    r"(?:项目|仓库|帐号|账号|账户|主页|用户名|论文|文章|订阅源|网站|官网|博客|地址|资料|id|doi|源)?"
)
# Full sentence anchors prevent "my colleague owns ..." or an arbitrary mention elsewhere
# in a paragraph from conferring ownership on a URL.
_OWN = re.compile(
    rf"(?:here(?:'s| is) my {_SUBJECT}|my {_SUBJECT}(?:\s+(?:url|link|id|doi))?"
    rf"(?:\s+(?:is|at|can be found at))?|i (?:own|maintain|authored|published|run|created)"
    rf"(?:\s+(?:(?:the|this|an?)\s+)?{_SUBJECT})?)\s*[:=]?\s*@"
    rf"|@\s+is my {_SUBJECT}"
    rf"|(?:这是|这个是|这里是)?我(?:的|(?:在\s*github\s*上)?(?:维护|开源|发表|发布|撰写|运营)(?:的|了)?)"
    rf"\s*{_ZSUBJECT}\s*(?:是|为|在)?\s*[:：]?\s*@"
    rf"|@\s*(?:是我(?:的|(?:负责)?(?:维护|开源|发表|发布|撰写|运营)的)\s*{_ZSUBJECT})",
    re.I,
)
_REQUEST = re.compile(
    r"(?:please\s+)?(?:watch|monitor|subscribe to|keep (?:me updated on|track of)|"
    r"track(?: (?:new |future )?(?:issues|releases|citations|updates|papers)\s+(?:for|on|from|to))?)"
    r"\s*(?:(?:the|this|my)\s+)?(?:public\s+)?(?:github\s+)?"
    r"(?:repo(?:sitory)?|profile|website|site|blog|feed|paper)?\s*[:：]?\s*@"
    r"(?:\s+for (?:new |future )?(?:issues|releases|citations|updates|papers))?"
    r"|(?:请|麻烦)?\s*(?:以后|定期|持续|长期|每天|每周)?\s*(?:帮我|替我)?\s*"
    r"(?:定期|持续|长期|每天|每周)?(?:关注|订阅|监测|跟踪|追踪|留意|定期查看)"
    r"(?:一下)?(?:这个|该|我的)?(?:仓库|项目|论文|订阅源|网站|官网|博客|账号)?\s*[:：]?\s*@"
    r"(?:\s*的?(?:新|新增|最新)?\s*(?:issues?|更新|引用(?:情况)?|动态|版本|论文))?"
    r"|(?:请)?(?:定期|持续|每周|每天)(?:帮我)?(?:看下|看看|查看|检查)(?:这个|该|我的)?"
    r"(?:仓库|项目|论文)?(?:的?(?:新增|最新|新)?\s*(?:issues?|引用|更新|动态))?\s*[:：]?\s*@"
    r"(?:\s*的?(?:新增|最新|新)?\s*(?:issues?|引用|更新|动态))?",
    re.I,
)
_RELATED = re.compile(
    rf"(?:i (?:contribute to|work on|am a contributor to|regularly use)|"
    rf"(?:our|your) {_SUBJECT}(?:\s+(?:is|at))?|my team maintains|our project depends on)"
    rf"\s*[:：]?\s*@"
    rf"|(?:我们(?:的项目依赖|团队维护|的(?:仓库|项目|论文))|"
    rf"我(?:参与维护|经常使用|参与开发)|你(?:的|维护的)\s*{_ZSUBJECT})\s*(?:是)?\s*[:：]?\s*@",
    re.I,
)
# Ongoing work can imply relevance even when the person does not claim ownership or ask
# for monitoring. Only propose a choice; the same activity from someone else proves nothing.
_ONGOING = re.compile(
    r"\b(?:i|we)(?:'ve| have| am| are)?\s+(?:been\s+)?(?:regularly|usually|currently|still|keep)\s+"
    r"(?:review(?:ing)?|triag(?:e|ing)|maintain(?:ing)?|contribut(?:e|ing)|submit(?:ting)?|"
    r"teach(?:ing)?|work(?:ing)?|rely(?:ing)?|use|using|follow(?:ing)?)\b"
    r"|(?:我|我们)(?:一直|最近一直|这段时间|长期|每周|每天|经常)(?:都|还|主要)?(?:在|要|需要)?"
    r"(?:帮|给|为|维护|审阅|审核|跟进|参与|依赖|使用|参考|查阅|整理|负责)"
    r"|(?:我|我们)(?:负责|参与)(?:维护|审阅|评审|发布|更新|处理)",
    re.I,
)
# Suggestions about research interests are limited to phrases the person treats as ongoing.
_TOPIC_REQUEST = re.compile(
    r"(?:please\s+)?(?:track|monitor|watch|keep me updated on|follow|alert me (?:to|about))\s+"
    r"(?:new|upcoming|recent|related)\s+(?:papers|publications|research)\s+"
    r"(?:about|on|in|related to)\s+(.+)"
    r"|(?:请|麻烦)?(?:以后|定期|持续|长期|每天|每周)?(?:帮我)?(?:定期|持续|长期|每天|每周)?"
    r"(?:跟踪|关注|追踪|推送|留意)(?:关于)?\s*(.+?)\s*(?:相关的?|方向的|方面的|的)?"
    r"(?:最新|新的?|最近的)(?:研究)?论文",
    re.I,
)
_TOPIC_INTEREST = re.compile(
    r"(?:my (?:research interest|research focus|research topic|field of study) is|"
    r"i (?:study|research|speciali[sz]e in)|i(?:'m| am) researching)\s+(.+)"
    r"|(?:我的(?:研究方向|研究兴趣|研究课题)(?:是|为|在于|[:：])|我(?:主要|长期)?研究"
    r"(?:的是|方向是)?)\s*(.+)",
    re.I,
)
_BROAD = {
    "ai",
    "artificial intelligence",
    "computer science",
    "machine learning",
    "science",
    "research",
    "new papers",
    "计算机科学",
    "机器学习",
    "人工智能",
    "我的项目",
    "新研究论文",
}
