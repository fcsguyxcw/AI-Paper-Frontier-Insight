from __future__ import annotations

import asyncio, json
import re
import uuid
from datetime import datetime, timedelta
from typing import AsyncIterable, Dict, List, Optional, Literal

from fastapi import Body, Request
from fastapi.concurrency import run_in_threadpool
from sse_starlette.sse import EventSourceResponse
from langchain.callbacks import AsyncIteratorCallbackHandler
from langchain.prompts.chat import ChatPromptTemplate


from chatchat.settings import Settings
from chatchat.server.agent.tools_factory.search_internet import search_engine
from chatchat.server.api_server.api_schemas import OpenAIChatOutput
from chatchat.server.chat.utils import History
from chatchat.server.knowledge_base.kb_service.base import KBServiceFactory
from chatchat.server.knowledge_base.kb_doc_api import search_docs, search_temp_docs
from chatchat.server.knowledge_base.utils import format_reference
from chatchat.server.utils import (wrap_done, get_ChatOpenAI, get_default_llm,
                                   BaseResponse, get_prompt_template, build_logger,
                                   check_embed_model, api_address
                                )


logger = build_logger()


NUMERAL_MAP = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
NUMERAL_PATTERN = re.compile(r"(?:最近|近|过去)\s*([0-9零一二两三四五六七八九十]+)\s*(个?\s*月|年)")


def _to_int(s: str) -> int:
    """将中文数字或阿拉伯数字转为 int"""
    if s.isdigit():
        return int(s)
    # 中文数字转换（支持简单格式：三、十二、二十五等）
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + NUMERAL_MAP.get(s[1], 0)
    if s.endswith("十"):
        return NUMERAL_MAP.get(s[0], 1) * 10
    if "十" in s:
        parts = s.split("十")
        return NUMERAL_MAP.get(parts[0], 1) * 10 + NUMERAL_MAP.get(parts[1], 0)
    return NUMERAL_MAP.get(s, 0)


def parse_time_filter(query: str) -> Dict[str, Dict[str, str]]:
    """从查询中提取时间范围，返回 metadata filter dict

    支持格式: "最近N个月", "最近N年", "YYYY年"
    N 支持中文数字（三、十二）和阿拉伯数字
    """
    today = datetime.today()
    filter_dict = {}

    # "最近N个月/年" / "近N个月/年"
    m = NUMERAL_PATTERN.search(query)
    if m:
        n = _to_int(m.group(1))
        unit = "月" if "月" in m.group(2) else "年"
        days = n * 30 if unit == "月" else n * 365
        start = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        filter_dict["published"] = {"$gte": start}
        return filter_dict

    # "YYYY年" / "YYYY"
    m = re.search(r"(20\d{2})\s*年?", query)
    if m:
        year = m.group(1)
        filter_dict["published"] = {
            "$gte": f"{year}-01-01",
            "$lte": f"{year}-12-31",
        }
        return filter_dict

    return filter_dict


async def kb_chat(query: str = Body(..., description="用户输入", examples=["你好"]),
                mode: Literal["local_kb", "temp_kb", "search_engine"] = Body("local_kb", description="知识来源"),
                kb_name: str = Body("", description="mode=local_kb时为知识库名称；temp_kb时为临时知识库ID，search_engine时为搜索引擎名称", examples=["samples"]),
                top_k: int = Body(Settings.kb_settings.VECTOR_SEARCH_TOP_K, description="匹配向量数"),
                score_threshold: float = Body(
                    Settings.kb_settings.SCORE_THRESHOLD,
                    description="知识库匹配相关度阈值，取值范围在0-1之间，SCORE越小，相关度越高，取到1相当于不筛选，建议设置在0.5左右",
                    ge=0,
                    le=2,
                ),
                history: List[History] = Body(
                    [],
                    description="历史对话",
                    examples=[[
                        {"role": "user",
                        "content": "我们来玩成语接龙，我先来，生龙活虎"},
                        {"role": "assistant",
                        "content": "虎头虎脑"}]]
                ),
                stream: bool = Body(True, description="流式输出"),
                model: str = Body(get_default_llm(), description="LLM 模型名称。"),
                temperature: float = Body(Settings.model_settings.TEMPERATURE, description="LLM 采样温度", ge=0.0, le=2.0),
                max_tokens: Optional[int] = Body(
                    Settings.model_settings.MAX_TOKENS,
                    description="限制LLM生成Token数量，默认None代表模型最大值"
                ),
                prompt_name: str = Body(
                    "default",
                    description="使用的prompt模板名称(在prompt_settings.yaml中配置)"
                ),
                return_direct: bool = Body(False, description="直接返回检索结果，不送入 LLM"),
                request: Request = None,
                ):
    if mode == "local_kb":
        kb = KBServiceFactory.get_service_by_name(kb_name)
        if kb is None:
            return BaseResponse(code=404, msg=f"未找到知识库 {kb_name}")
    
    async def knowledge_base_chat_iterator() -> AsyncIterable[str]:
        try:
            nonlocal history, prompt_name, max_tokens

            history = [History.from_data(h) for h in history]

            if mode == "local_kb":
                kb = KBServiceFactory.get_service_by_name(kb_name)
                ok, msg = kb.check_embed_model()
                if not ok:
                    raise ValueError(msg)
                time_filter = parse_time_filter(query)
                docs = await run_in_threadpool(search_docs,
                                                query=query,
                                                knowledge_base_name=kb_name,
                                                top_k=top_k,
                                                score_threshold=score_threshold,
                                                file_name="",
                                                metadata=time_filter)
                source_documents = format_reference(kb_name, docs, api_address(is_public=True))
            elif mode == "temp_kb":
                ok, msg = check_embed_model()
                if not ok:
                    raise ValueError(msg)
                docs = await run_in_threadpool(search_temp_docs,
                                                kb_name,
                                                query=query,
                                                top_k=top_k,
                                                score_threshold=score_threshold)
                source_documents = format_reference(kb_name, docs, api_address(is_public=True))
            elif mode == "search_engine":
                result = await run_in_threadpool(search_engine, query, top_k, kb_name)
                docs = [x.dict() for x in result.get("docs", [])]
                source_documents = [f"""出处 [{i + 1}] [{d['metadata']['filename']}]({d['metadata']['source']}) \n\n{d['page_content']}\n\n""" for i,d in enumerate(docs)]
            else:
                docs = []
                source_documents = []
            # import rich
            # rich.print(dict(
            #     mode=mode,
            #     query=query,
            #     knowledge_base_name=kb_name,
            #     top_k=top_k,
            #     score_threshold=score_threshold,
            # ))
            # rich.print(docs)
            if return_direct:
                yield OpenAIChatOutput(
                    id=f"chat{uuid.uuid4()}",
                    model=None,
                    object="chat.completion",
                    content="",
                    role="assistant",
                    finish_reason="stop",
                    docs=source_documents,
                ) .model_dump_json()
                return

            callback = AsyncIteratorCallbackHandler()
            callbacks = [callback]

            # Enable langchain-chatchat to support langfuse
            import os
            langfuse_secret_key = os.environ.get('LANGFUSE_SECRET_KEY')
            langfuse_public_key = os.environ.get('LANGFUSE_PUBLIC_KEY')
            langfuse_host = os.environ.get('LANGFUSE_HOST')
            if langfuse_secret_key and langfuse_public_key and langfuse_host :
                from langfuse import Langfuse
                from langfuse.callback import CallbackHandler
                langfuse_handler = CallbackHandler()
                callbacks.append(langfuse_handler)

            if max_tokens in [None, 0]:
                max_tokens = Settings.model_settings.MAX_TOKENS

            llm = get_ChatOpenAI(
                model_name=model,
                temperature=temperature,
                max_tokens=max_tokens,
                callbacks=callbacks,
            )

            # Reranker: 使用 Cross-Encoder 对检索结果二次排序
            if mode == "local_kb" and Settings.kb_settings.USE_RERANKER:
                try:
                    from chatchat.server.reranker.reranker import LangchainReranker
                    from chatchat.server.utils import embedding_device

                    # docs 是 List[Dict]，需转为 List[Document] 供 reranker 处理
                    from langchain.docstore.document import Document as LCDocument
                    lc_docs = [LCDocument(page_content=d["page_content"], metadata=d["metadata"]) for d in docs]

                    reranker = LangchainReranker(
                        top_n=Settings.kb_settings.RERANKER_TOP_N,
                        device=embedding_device(),
                        max_length=Settings.kb_settings.RERANKER_MAX_LENGTH,
                        model_name_or_path=Settings.kb_settings.RERANKER_MODEL,
                    )
                    lc_docs = reranker.compress_documents(documents=lc_docs, query=query)
                    # 将 reranked 结果回写到 docs dict 列表
                    docs = [{"page_content": d.page_content, "metadata": d.metadata} for d in lc_docs]
                    source_documents = format_reference(kb_name, docs, api_address(is_public=True))
                except ImportError:
                    logger.warning("Reranker 启用但 sentence-transformers 未安装，跳过重排序")
                except Exception as e:
                    logger.warning(f"Reranker 失败: {e}，使用原始检索结果")

            context = "\n\n".join([doc["page_content"] for doc in docs])

            if len(docs) == 0:  # 如果没有找到相关文档，使用empty模板
                prompt_name = "empty"
            prompt_template = get_prompt_template("rag", prompt_name)
            input_msg = History(role="user", content=prompt_template).to_msg_template(False)
            chat_prompt = ChatPromptTemplate.from_messages(
                [i.to_msg_template() for i in history] + [input_msg])

            chain = chat_prompt | llm

            # Begin a task that runs in the background.
            task = asyncio.create_task(wrap_done(
                chain.ainvoke({"context": context, "question": query}),
                callback.done),
            )

            if len(source_documents) == 0:  # 没有找到相关文档
                source_documents.append(f"<span style='color:red'>未找到相关文档,该回答为大模型自身能力解答！</span>")

            if stream:
                # yield documents first
                ret = OpenAIChatOutput(
                    id=f"chat{uuid.uuid4()}",
                    object="chat.completion.chunk",
                    content="",
                    role="assistant",
                    model=model,
                    docs=source_documents,
                )
                yield ret.model_dump_json()

                async for token in callback.aiter():
                    ret = OpenAIChatOutput(
                        id=f"chat{uuid.uuid4()}",
                        object="chat.completion.chunk",
                        content=token,
                        role="assistant",
                        model=model,
                    )
                    yield ret.model_dump_json()
            else:
                answer = ""
                async for token in callback.aiter():
                    answer += token
                ret = OpenAIChatOutput(
                    id=f"chat{uuid.uuid4()}",
                    object="chat.completion",
                    content=answer,
                    role="assistant",
                    model=model,
                )
                yield ret.model_dump_json()
            await task
        except asyncio.exceptions.CancelledError:
            logger.warning("streaming progress has been interrupted by user.")
            return
        except Exception as e:
            logger.error(f"error in knowledge chat: {e}")
            yield {"data": json.dumps({"error": str(e)})}
            return

    if stream:
        return EventSourceResponse(knowledge_base_chat_iterator())
    else:
        result = await knowledge_base_chat_iterator().__anext__()
        return json.loads(result)
