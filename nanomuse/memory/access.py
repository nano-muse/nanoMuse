"""Conservative task authorization while long-term memory is disabled."""

from __future__ import annotations

import re

PUBLIC_TOOLS = {"terminate", "ask_user", "web_search", "web_fetch"}
WORKSPACE_TOOLS = {"files", "shell", "python_execute"}
_OBJECT = (
    r"文件|目录|代码|脚本|命令|网页|文档|表格|报告|图片|"
    r"\b(?:file|folder|directory|code|script|command|readme|document|spreadsheet|report|image)\b|"
    r"\b\w+\.(?:py|js|ts|tsx|md|txt|csv|json|html)\b|[./~][\w/.-]+"
)
_EXPLICIT_WORK = re.compile(
    r"(?:创建|新建|生成|编写|修改|编辑|删除|读取|查看|打开|搜索|查找|列出|整理|分析|处理|转换|"
    r"计算|运行|执行|编译|构建|调试|检查|修复|写入|保存|导出|比较|对比|总结|翻译|读|写)"
    r"[^。！？\n]{0,80}(?:" + _OBJECT + r")|"
    r"\b(?:create|write|read|edit|modify|delete|remove|open|list|search|find|analyze|convert|generate)\b"
    r"[^.!?\n]{0,80}(?:" + _OBJECT + r")|"
    r"^\s*(?:(?:请|请帮我|帮我|麻烦|现在|先)\s*)*(?:运行|执行|编译|构建|调试|测试一下|测试这个)|"
    r"^\s*(?:(?:please|can you|could you|help me|let's)\s+)*(?:run|execute|build|compile|test|debug)\b",
    re.I,
)
_PERSISTENCE = re.compile(
    r"记住|记忆|偏好|习惯|以后|今后|下次|每次|长期|"
    r"\b(?:remember|recall|forget|preference|whenever)\b|"
    r"from now on|next time|every time|long.term",
    re.I,
)


def restriction(tool: str, task: str, *, memory_off: bool) -> str | None:
    if not memory_off or tool in PUBLIC_TOOLS:
        return None
    if tool in WORKSPACE_TOOLS and _EXPLICIT_WORK.search(task) and not _PERSISTENCE.search(task):
        return None
    return (
        "Memory is disabled for this space. This request did not authorize this operation. "
        "Do not use files, commands or another store to recall or save personal facts. "
        "Ask for an explicit current file or command task, or explain how to enable memory."
    )
