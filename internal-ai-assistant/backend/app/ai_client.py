import base64
import hashlib
import math
import mimetypes
import re
from pathlib import Path
from typing import List, Optional

from openai import OpenAI

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
    return OpenAI(api_key=real_key, base_url=real_base_url)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """生成文本向量。

    默认使用 local-hash，方便本地试用；当 EMBEDDING_PROVIDER=openai 且配置了
    EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL 时，会调用兼容 OpenAI
    的 embeddings 接口。外部服务失败时自动退回本地向量，避免上传/问答中断。
    """
    if not texts:
        return []
    if EMBEDDING_PROVIDER in {"openai", "openai-compatible", "remote"} and EMBEDDING_API_KEY:
        try:
            client = OpenAI(api_key=EMBEDDING_API_KEY, base_url=EMBEDDING_BASE_URL)
            resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [list(item.embedding) for item in resp.data]
        except Exception:
            # 不能因为向量服务临时不可用阻断系统使用；生产环境建议接监控告警。
            pass
    return [local_hash_embedding(text) for text in texts]


def chat_answer(
    question: str,
    contexts: List[dict],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    try:
        client = _openai_client(api_key, base_url)
    except ValueError as exc:
        return str(exc)

    real_model = model or CHAT_MODEL or "deepseek-chat"
    context_text = "\n\n".join(
        f"[来源{i + 1}] 文档：{c['document_title']}；页码：{c.get('page_number') or '未知'}；类型：{c.get('source_type') or 'document'}\n{c['content']}"
        for i, c in enumerate(contexts)
    )
    system = (
        "你是公司内部 AI 助手，必须只根据本次提供的授权知识库片段、个人附件或图片 OCR 结果回答。"
        "不要使用未出现在片段中的外部知识；如果片段中没有答案，请明确说明没有在授权资料中找到依据。"
        "回答要简洁、准确，优先使用中文；可以使用 Markdown 分点，并在末尾按 [来源1]、[来源2] 标注实际用到的引用，不要编造来源。"
    )
    user = f"授权知识库片段（回答只能依据以下内容）：\n{context_text}\n\n用户问题：{question}"
    response = client.chat.completions.create(
        model=real_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
    )
    return response.choices[0].message.content or "未生成回答。"


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
