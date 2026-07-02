import base64
import hashlib
import json
import math
import mimetypes
import re
from pathlib import Path
from typing import List, Optional

from openai import OpenAI

from .structured_digest import build_structured_digest, should_use_structured_digest

from .config import (
    CHAT_MODEL,
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
)


def _runtime_embedding_config() -> dict:
    fallback = {
        "provider": EMBEDDING_PROVIDER,
        "api_key": EMBEDDING_API_KEY,
        "base_url": EMBEDDING_BASE_URL,
        "model": EMBEDDING_MODEL,
    }
    try:
        from .database import SessionLocal
        from .settings_service import get_embedding_config

        db = SessionLocal()
        try:
            return get_embedding_config(db)
        finally:
            db.close()
    except Exception:
        return fallback


def local_hash_embedding(text: str) -> List[float]:
    """小型部署可用的本地轻量向量，不依赖外部服务。"""
    vec = [0.0] * EMBEDDING_DIM
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+", text.lower())
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).hexdigest()
        idx = int(digest[:8], 16) % EMBEDDING_DIM
        sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _openai_client(api_key: Optional[str] = None, base_url: Optional[str] = None) -> OpenAI:
    real_key = api_key or OPENAI_API_KEY
    real_base_url = base_url or OPENAI_BASE_URL or "https://api.deepseek.com"
    if not real_key:
        raise ValueError("还没有配置模型 API Key。请先到后台的模型配置中填写。")
    # 交互式问答不应在外部模型慢响应时卡住太久；失败会由调用方走本地证据兜底。
    return OpenAI(api_key=real_key, base_url=real_base_url, timeout=45.0, max_retries=0)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """生成文本向量。

    默认使用 local-hash，方便本地试用；当 EMBEDDING_PROVIDER=openai 且配置了
    EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL 时，会调用兼容 OpenAI
    的 embeddings 接口。外部服务失败时自动退回本地向量，避免上传/问答中断。
    """
    if not texts:
        return []
    cfg = _runtime_embedding_config()
    provider = str(cfg.get("provider") or "local").lower()
    api_key = str(cfg.get("api_key") or "")
    base_url = str(cfg.get("base_url") or "") or None
    model = str(cfg.get("model") or "local-hash")
    if provider in {"openai", "openai-compatible", "remote"} and api_key:
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.embeddings.create(model=model, input=texts)
            return [list(item.embedding) for item in resp.data]
        except Exception as exc:
            from .config import IS_PRODUCTION
            if IS_PRODUCTION:
                raise RuntimeError(f"Embedding service unavailable: {str(exc)[:200]}") from exc
            # 不能因为向量服务临时不可用阻断系统使用；生产环境建议接监控告警。
            pass
    return [local_hash_embedding(text) for text in texts]


def extractive_fallback_answer(question: str, contexts: List[dict], reason: str = "") -> str:
    if not contexts:
        return "没有在授权知识库中找到相关内容，因此不能脱离资料泛答。"

    docs: list[str] = []
    highlights: list[str] = []
    for context in contexts[:8]:
        title = context.get("document_title") or context.get("filename") or "未知文档"
        if title not in docs:
            docs.append(title)
        content = " ".join(str(context.get("content") or "").split())
        content = re.sub(r"(?:[A-Z]{1,3}\d+\s*[:：]\s*)", "", content)
        content = re.sub(r"\[数据结果\]", "", content).strip(" |")
        if content:
            highlights.append(content[:220])

    lines = [
        "## 本地兜底整理（模型暂不可用）",
        "模型暂时没有返回稳定结果，下面先基于命中证据给出简短整理；请结合来源面板核验。",
        f"- 命中文档：{'、'.join(docs[:5]) or '未知文档'}",
        f"- 命中片段数：{len(contexts)}",
        "",
        "## 关键信息",
    ]
    if highlights:
        lines.extend(f"- {item}" for item in highlights[:5])
    else:
        lines.append("- 当前命中内容较少，暂无法稳定提炼字段。")

    if reason:
        lines.append(f"\n> 说明：模型生成失败或未配置（{reason[:160]}），已避免把原始切分片段直接输出。")
    return "\n".join(lines)


def chat_answer(
    question: str,
    contexts: List[dict],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
       model: Optional[str] = None,
    history: Optional[List[dict]] = None,
) -> str:
    try:
        client = _openai_client(api_key, base_url)
    except ValueError as exc:
        return extractive_fallback_answer(question, contexts, str(exc))

    real_model = model or CHAT_MODEL or "deepseek-chat"
    context_text = "\n\n".join(
        f"[来源{i + 1}] 文档：{c['document_title']}；页码：{c.get('page_number') or '未知'}；类型：{c.get('source_type') or 'document'}\n{c['content']}"
        for i, c in enumerate(contexts)
    )
    system = (
        "你是公司内部 AI 助手，必须只根据本次提供的授权知识库片段、个人附件或图片 OCR 结果回答。"
        "不要使用未出现在片段中的外部知识；如果片段中没有答案，请明确说明没有在授权资料中找到依据。"
        "回答要简洁、准确，优先使用中文；可以使用 Markdown 分点。不要在正文或末尾输出 [来源1]、[来源2] 这类标记；引用来源会由系统在独立来源面板展示，不要编造来源。"
    )
    user = f"授权知识库片段（回答只能依据以下内容）：\n{context_text}\n\n用户问题：{question}"
    try:
        response = client.chat.completions.create(
            model=real_model,
            messages=[{"role": "system", "content": system}, *[{"role": h["role"], "content": h["content"]} for h in (history or [])], {"role": "user", "content": user}],
            temperature=0.2,
        )
        return response.choices[0].message.content or "未生成回答。"
    except Exception as exc:
        return extractive_fallback_answer(question, contexts, str(exc)[:200])


def classify_chat_intent(
    question: str,
    history: Optional[List[dict]] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Use the configured chat model as a lightweight router for ambiguous questions.

    Returns a conservative dict with:
    - intent: chat | knowledge | summary | followup
    - should_retrieve: bool
    - reason: short human-readable reason
    If the classifier is unavailable or returns invalid JSON, callers can fall back to rules.
    """
    result = {"intent": "unknown", "should_retrieve": None, "reason": "classifier_unavailable", "confidence": 0.0}
    text = (question or "").strip()
    if not text:
        return {"intent": "chat", "should_retrieve": False, "reason": "empty_question", "confidence": 1.0}
    try:
        client = _openai_client(api_key, base_url)
    except ValueError:
        return result

    real_model = model or CHAT_MODEL or "deepseek-chat"
    recent = []
    for item in (history or [])[-4:]:
        role = item.get("role")
        content = str(item.get("content") or "")[:300]
        if role in {"user", "assistant"} and content:
            recent.append({"role": role, "content": content})

    system = (
        "你是内部知识库问答系统的意图分类器，只能输出 JSON，不要输出解释文本。"
        "判断用户当前问题是否需要检索知识库/附件/公司资料。"
        "分类标准："
        "1. chat：寒暄、问你是谁、你能做什么、如何使用你、普通闲聊、无需公司资料的通用表达。should_retrieve=false。"
        "2. knowledge：询问公司制度、流程、权限、报销、年假、合同、数据、文档内容、附件内容等，需要授权资料。should_retrieve=true。"
        "3. summary：要求总结/列出当前可读文档、知识库有什么、全部资料概览。should_retrieve=true。"
        "4. followup：明显追问上一轮来源/上面内容/继续展开/引用来源。通常 should_retrieve=true。"
        "如果不确定，要保守：只有看起来确实需要公司资料、知识库、附件或文档时才 should_retrieve=true；普通闲聊和询问助手能力应为 false。"
        "输出格式必须是：{\"intent\":\"chat|knowledge|summary|followup\",\"should_retrieve\":true|false,\"reason\":\"...\",\"confidence\":0到1}"
    )
    user = json.dumps({"question": text, "recent_history": recent}, ensure_ascii=False)
    try:
        response = client.chat.completions.create(
            model=real_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            max_tokens=160,
        )
        content = (response.choices[0].message.content or "").strip()
        match = re.search(r"\{.*\}", content, re.S)
        parsed = json.loads(match.group(0) if match else content)
        intent = str(parsed.get("intent") or "unknown").lower()
        if intent not in {"chat", "knowledge", "summary", "followup"}:
            intent = "unknown"
        should = parsed.get("should_retrieve")
        if not isinstance(should, bool):
            should = None
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "intent": intent,
            "should_retrieve": should,
            "reason": str(parsed.get("reason") or "model_classified")[:240],
            "confidence": max(0.0, min(confidence, 1.0)),
        }
    except Exception as exc:
        return {"intent": "unknown", "should_retrieve": None, "reason": f"classifier_error: {str(exc)[:160]}", "confidence": 0.0}


def _build_conversation_messages(question: str, history: Optional[List[dict]] = None) -> list[dict]:
    system = (
        "你是公司内部 AI 助手。用户发来的任何普通问题都要自然回答，不要因为没有知识库上下文就沉默。"
        "对于问候、感谢、闲聊、写作、改写、整理成表格、翻译、解释、追问上一轮回答等请求，可以直接结合对话上下文作答。"
        "如果用户要求整理、改写、总结某段内容，但当前对话里没有提供可整理的原文，就请用户把内容粘贴或上传，并可给出一个表格模板示例。"
        "只有当用户明确询问具体公司制度、数据、流程或文档事实，而你没有获得任何可依据的资料时，才说明没有在知识库中找到依据，并建议上传或授权相关文档；绝不要编造公司事实。"
        "优先使用中文，简洁作答。"
    )
    messages = [{"role": "system", "content": system}]
    for h in (history or []):
        if h.get("role") in {"user", "assistant"} and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})
    return messages


def conversational_answer(
    question: str,
    history: Optional[List[dict]] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    try:
        client = _openai_client(api_key, base_url)
    except ValueError:
        return "可以。请把需要整理的具体内容发给我，我可以帮你整理成表格、清单或摘要；如果是公司文档内容，也可以先上传或授权相关资料。"
    real_model = model or CHAT_MODEL or "deepseek-chat"
    try:
        response = client.chat.completions.create(model=real_model, messages=_build_conversation_messages(question, history), temperature=0.3)
        return response.choices[0].message.content or "未生成回答。"
    except Exception:
        return "抱歉，我暂时无法回答这条消息，请稍后再试。"


def stream_conversational_answer(
    question: str,
    history: Optional[List[dict]] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
):
    fallback = "你好，我是公司内部知识助手。我可以基于你有权限访问的文档回答问题；这条消息没有匹配到知识库内容。"
    try:
        client = _openai_client(api_key, base_url)
    except ValueError:
        for i in range(0, len(fallback), 80):
            yield fallback[i : i + 80]
        return
    real_model = model or CHAT_MODEL or "deepseek-chat"
    try:
        stream = client.chat.completions.create(
            model=real_model,
            messages=_build_conversation_messages(question, history),
            temperature=0.3,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
            if delta:
                yield delta
    except Exception:
        error_text = "抱歉，我暂时无法回答这条消息，请稍后再试。"
        for i in range(0, len(error_text), 80):
            yield error_text[i : i + 80]


def _build_knowledge_messages(question: str, contexts: List[dict], history: Optional[List[dict]] = None, structured_digest: str = "") -> list[dict]:
    context_text = "\n\n".join(
        f"[来源{i + 1}] 文档：{c.get('document_title') or c.get('filename') or '未知文档'}；页码：{c.get('page_number') or '未知'}；类型：{c.get('source_type') or 'document'}\n{c.get('content') or ''}"
        for i, c in enumerate(contexts)
    )
    system = (
        "你是公司内部 AI 助手。你的任务是基于授权资料进行理解、归纳、判断和表达，最终答案必须由你重新组织，不能直接粘贴检索片段。"
        "证据预处理包只用于帮你看懂资料：它可能包含跨 chunk 合并、表格行列还原、字段分组和去重结果，但它不是最终答案模板。"
        "原始引用片段只用于核验和标注来源；不要把 A1/B1 单元格、[数据结果]、chunk 截断文本或大段原文展示给用户。"
        "回答风格要像清晰的业务分析报告：先给结论，再按需要用小标题、项目符号或 Markdown 表格整理，最后列出风险/需要核验项和引用。"
        "如果用户问的是表格/Excel/CSV，优先基于证据预处理包中的合并记录回答；不要把切片造成的字段断裂误判为缺失。"
        "如果资料不足，要明确说不足在哪里；不要使用未出现在授权资料中的外部事实。"
        "不要把资料中的动作改写成更强含义：例如只有‘签署’证据时，不要写成‘签章/盖章/审核/自动同步’；只有员工端操作证据时，不要补写内部审批或合同组流程。"
        "少客套，不要以‘好的，根据您提供的……’开头。"
    )
    evidence_block = f"\n\n【证据预处理包（给 AI 理解资料用，不要照抄为最终答案）】\n{structured_digest}" if structured_digest else ""
    user = (
        f"用户问题：{question}\n\n"
        "请基于下面证据回答。你需要自己完成二次分析、归纳、排序和排版。\n"
        f"{evidence_block}\n\n"
        f"【原始引用片段（只用于核验和引用标注，禁止原样直出）】\n{context_text}\n\n"
        "最终输出要求：\n"
        "1. 不要展示原始切分片段、单元格坐标或 chunk 痕迹；\n"
        "2. 根据问题选择合适结构，不要机械套固定模板；\n"
        "3. 能表格化就用 Markdown 表格，但只放用户真正需要的信息；\n"
        "4. 不要在正文或末尾输出 [来源1]、[来源2] 这类标记；引用依据会由系统在右侧/底部来源面板展示。"
    )
    return [
        {"role": "system", "content": system},
        *[{"role": h["role"], "content": h["content"]} for h in (history or [])],
        {"role": "user", "content": user},
    ]


def chat_answer_v2(
    question: str,
    contexts: List[dict],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    history: Optional[List[dict]] = None,
    structured_digest: str = "",
) -> str:
    try:
        client = _openai_client(api_key, base_url)
    except ValueError as exc:
        return extractive_fallback_answer(question, contexts, str(exc))
    real_model = model or CHAT_MODEL or "deepseek-chat"
    try:
        response = client.chat.completions.create(
            model=real_model,
            messages=_build_knowledge_messages(question, contexts, history, structured_digest),
            temperature=0.2,
        )
        return response.choices[0].message.content or "未生成回答。"
    except Exception as exc:
        return extractive_fallback_answer(question, contexts, str(exc)[:200])


def stream_chat_answer_v2(
    question: str,
    contexts: List[dict],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    history: Optional[List[dict]] = None,
    structured_digest: str = "",
):
    try:
        client = _openai_client(api_key, base_url)
    except ValueError as exc:
        fallback = extractive_fallback_answer(question, contexts, str(exc))
        for i in range(0, len(fallback), 80):
            yield fallback[i : i + 80]
        return
    real_model = model or CHAT_MODEL or "deepseek-chat"
    try:
        stream = client.chat.completions.create(
            model=real_model,
            messages=_build_knowledge_messages(question, contexts, history, structured_digest),
            temperature=0.2,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
            if delta:
                yield delta
    except Exception as exc:
        fallback = extractive_fallback_answer(question, contexts, str(exc)[:200])
        for i in range(0, len(fallback), 80):
            yield fallback[i : i + 80]

def image_to_text(
    file_path: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """使用支持视觉输入的 OpenAI-compatible 模型识别图片文字和内容。"""
    client = _openai_client(api_key, base_url)
    real_model = model or CHAT_MODEL or "gpt-4o-mini"
    path = Path(file_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    prompt = (
        "请对这张图片做 OCR 和内容理解：\n"
        "1. 尽可能完整提取所有可见文字；\n"
        "2. 如果有表格、票据、合同、截图，请保留关键字段和值；\n"
        "3. 如果文字很少，也请用中文简要描述图片内容；\n"
        "4. 只输出纯文本，便于后续检索。"
    )
    response = client.chat.completions.create(
        model=real_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ],
            }
        ],
        temperature=0.0,
    )
    return (response.choices[0].message.content or "").strip()
