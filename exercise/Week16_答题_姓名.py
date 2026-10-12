"""Week16 技能答题文件。

姓名：__________  班级：__________

使用说明：
1. 第1题30分，第2题30分，共60分。
2. 不要修改“固定代码区”和“公开检查区”。
3. 只在三个标有“学生作答区”的函数中编写代码：
   - build_book_app()
   - encode_sse()
   - build_poem_app()
4. 如果需要，可以在作答区附近增加自己的辅助函数。
5. 完成后直接运行本文件，查看公开检查结果。

完整题意、输入输出合同和评分点见 Week16_周考题.md。
"""

# asyncio 用于第2题：以非阻塞方式控制相邻诗句的发送间隔。
import asyncio
# json 用于第2题：在 Python 数据和 JSON 文本之间转换。
import json

# 下面的 FastAPI 类和函数用于两道技能题。
# Depends：在路由中复用 require_client 请求头检查。
# Header：声明 X-Client-Id 来自 HTTP 请求头。
# Path / Query：给路径参数和查询参数添加范围规则。
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query
# StreamingResponse 用于第2题持续返回 SSE 事件文本。
from fastapi.responses import StreamingResponse
# TestClient 只在文件末尾的公开检查中调用 API，学生不需要修改它。
from fastapi.testclient import TestClient
# BaseModel 用于定义 API 对外返回的图书结构。
from pydantic import BaseModel


# ==================== 第1题：固定代码区（不要修改） ====================

class BookOut(BaseModel):
    """API 对外返回的图书字段。

    这里故意不包含 internal_note，用于检查 response_model
    能否将内部字段从响应中过滤掉。
    """

    id: int
    title: str
    category: str
    price: float


# 本题的固定图书数据。
# 数据库尚未加入考试，因此接口直接查询这个列表。
# 不得修改列表或其中的字典。
BOOKS = [
    {"id": 1, "title": "Python入门", "category": "programming", "price": 59.0, "internal_note": "不对外展示"},
    {"id": 2, "title": "Web API基础", "category": "programming", "price": 79.0, "internal_note": "不对外展示"},
    {"id": 3, "title": "产品思维", "category": "business", "price": 45.0, "internal_note": "不对外展示"},
    {"id": 4, "title": "Agent工程实战", "category": "programming", "price": 99.0, "internal_note": "不对外展示"},
]


# ==================== 第2题：固定古诗数据（不要修改） ====================

# 字典键是接口使用的 poem_id；每首诗包含标题、作者和按顺序排列的诗句。
POEMS = {
    "jingyesi": {
        "title": "静夜思",
        "author": "李白",
        "lines": ["床前明月光，", "疑是地上霜。", "举头望明月，", "低头思故乡。"],
    },
    "dengguanquelou": {
        "title": "登鹳雀楼",
        "author": "王之涣",
        "lines": ["白日依山尽，", "黄河入海流。", "欲穷千里目，", "更上一层楼。"],
    },
}


def require_client(x_client_id: str | None = Header(default=None)) -> str:
    """检查调用方提供的 X-Client-Id 请求头。

    FastAPI 会把参数名 x_client_id 转换为请求头 X-Client-Id。
    只有值为 classroom 时允许继续调用接口；其他情况返回 401。
    第1题的两个路由都要通过 Depends(require_client) 使用本函数。
    """

    if x_client_id != "classroom":
        raise HTTPException(status_code=401, detail="无效客户端")
    return x_client_id


# ==================== 第1题：学生作答区开始 ====================

def build_book_app() -> FastAPI:
    """创建并返回图书目录 FastAPI 应用。

    需要在本函数中完成：
    1. 创建 FastAPI() 对象；
    2. 定义 GET /books 列表查询接口；
    3. 定义 GET /books/{book_id} 详情查询接口；
    4. 返回 FastAPI 应用对象。

    两个接口的参数、response_model、依赖和错误规则见正式试卷。
    """

    # TODO：删除下一行，在这里完成第1题。
    app = FastAPI()

    @app.get("/books")
    def get_books(
            category: str | None = None,
            max_price: float | None = Query(default=None, gt=0),
            limit: int = Query(default=10, ge=1, le=20),
            client: str = Depends(require_client),
    ) -> list[BookOut]:
        books = BOOKS
        if category is not None:
            books = [book for book in books if book["category"] == category]

        if max_price is not None:
            books = [book for book in books if book["price"] <= max_price]

        books = books[:limit]
        books = [BookOut(**book) for book in books]
        return books

    @app.get("/books/{book_id}", response_model=BookOut)
    def get_book(
            book_id: int,
            client: str = Depends(require_client),
    ) -> dict:
        if book_id <= 0:
            raise HTTPException(
                status_code=422,
            )

        for i, book in enumerate(BOOKS):
            if book["id"] == book_id:
                return book

        raise HTTPException(status_code=404,
                            detail="图书不存在")
    return app


# ==================== 第1题：学生作答区结束 ====================

# ==================== 第2题第一问：学生作答区开始 ====================

def encode_sse(event, data, event_id=None):
    """把一份 Python 数据编码成一条完整的 SSE 事件字符串。

    参数：
        event：事件名，例如 "progress" 或 "done"。
        data：事件携带的 Python 数据，例如 {"percent": 50}。
        event_id：可选事件编号；为 None 时不输出 id 行。

    返回：
        str：按 id（可选）、event、data 顺序组成，并以 \n\n 结束。

    异常：
        事件名为空或含换行时，抛出 ValueError("无效的事件名")。
    """

    # TODO：删除下一行，在这里完成第2题第一问。
    if isinstance(event, str):
        event = event.strip()
        if not event or "\r" in event or "\n" in event:
            raise ValueError("无效的事件名")

    data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    if event_id is None:
        return f"event: {event}\ndata: {data}\n\n"
    else:
        return f"id: {event_id}\nevent: {event}\ndata: {data}\n\n"


# ==================== 第2题第一问：学生作答区结束 ====================

# ==================== 第2题第二问：学生作答区开始 ====================

def build_poem_app() -> FastAPI:
    """创建并返回逐句发送古诗的 FastAPI SSE 应用。

    需要在本函数中完成：
    1. 创建 FastAPI() 对象；
    2. 定义 GET /poems/{poem_id}/stream 路由；
    3. 声明 poem_id 和 interval_ms 参数及其校验规则；
    4. 在事件流开始前检查古诗是否存在；
    5. 在路由内部定义异步生成器 poem_stream()；
    6. 复用 encode_sse()，依次 yield metadata、line、done 事件；
    7. 使用 asyncio.sleep() 控制相邻诗句的发送间隔；
    8. 使用 StreamingResponse 返回生成器，并设置 SSE 媒体类型和缓存头；
    9. 返回 FastAPI 应用对象。

    每类事件的数据字段、ID、顺序及参数边界见正式试卷。
    """

    # TODO：删除下一行，在这里完成第2题第二问。
    app = FastAPI(
        title="第二题第二问"
    )

    @app.get("/poems/{poem_id}/stream")
    def stream_chat(
            poem_id: str,
            interval_ms: int = Query(default=500, ge=0, le=2000),
    ) -> StreamingResponse:
        if poem_id not in POEMS:
            raise HTTPException(status_code=404,
                                detail="古诗不存在")

        poem = POEMS[poem_id]
        lines = poem["lines"]
        total = len(lines)

        async def poem_stream():
            yield encode_sse(
                "metadata",
                {"poem_id": poem_id, "title": poem["title"], "author": poem["author"], "total": total},
                event_id=0,
            )

            for line_no, text in enumerate(lines, start=1):
                yield encode_sse(
                    "line",
                    {"poem_id": poem_id, "line_no": line_no, "text": text},
                    event_id=line_no,
                )
                if line_no < total:
                    await asyncio.sleep(interval_ms / 1000)

            yield encode_sse(
                "done",
                {"poem_id": poem_id, "status": "completed", "sent_lines": total},
                event_id=total + 1,
            )

        return StreamingResponse(
            poem_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    return app


# ==================== 第2题第二问：学生作答区结束 ====================

# ==================== 公开检查区（不要修改） ====================

def check_question_1():
    """检查第1题的请求头、过滤、参数边界、详情、错误和输入不变。"""

    original = [dict(book) for book in BOOKS]
    client = TestClient(build_book_app())
    headers = {"X-Client-Id": "classroom"}
    assert client.get("/books").status_code == 401
    assert len(client.get("/books", headers=headers).json()) == 4
    filtered = client.get("/books?category=programming&max_price=80&limit=1", headers=headers)
    assert filtered.status_code == 200
    assert filtered.json() == [{"id": 1, "title": "Python入门", "category": "programming", "price": 59.0}]
    assert client.get("/books?category=missing", headers=headers).json() == []
    assert client.get("/books?limit=0", headers=headers).status_code == 422
    assert client.get("/books?limit=21", headers=headers).status_code == 422
    assert client.get("/books?max_price=0", headers=headers).status_code == 422
    assert client.get("/books/2", headers=headers).json() == {"id": 2, "title": "Web API基础", "category": "programming", "price": 79.0}
    missing = client.get("/books/99", headers=headers)
    assert missing.status_code == 404 and missing.json() == {"detail": "图书不存在"}
    assert client.get("/books/0", headers=headers).status_code == 422
    assert BOOKS == original


def check_question_2():
    """检查第2题的编码格式、古诗查询、参数边界和逐句事件流。"""

    assert encode_sse(" progress ", {"percent": 50}, event_id=2) == 'id: 2\nevent: progress\ndata: {"percent":50}\n\n'
    assert encode_sse("done", {"text": "完成"}) == 'event: done\ndata: {"text":"完成"}\n\n'
    for invalid_event in ("", "   ", "bad\nname", "bad\rname"):
        try:
            encode_sse(invalid_event, {})
        except ValueError as error:
            assert str(error) == "无效的事件名"
        else:
            raise AssertionError("无效事件名应抛出 ValueError")
    client = TestClient(build_poem_app())
    response = client.get("/poems/jingyesi/stream?interval_ms=0")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    blocks = [block for block in response.text.split("\n\n") if block]
    events = []
    for block in blocks:
        fields = {}
        for line in block.splitlines():
            name, separator, value = line.partition(":")
            assert separator == ":"
            fields[name] = value.lstrip()
        events.append({
            "id": fields.get("id"),
            "event": fields.get("event"),
            "data": json.loads(fields["data"]),
        })
    assert events == [
        {"id": "0", "event": "metadata", "data": {"poem_id": "jingyesi", "title": "静夜思", "author": "李白", "total": 4}},
        {"id": "1", "event": "line", "data": {"poem_id": "jingyesi", "line_no": 1, "text": "床前明月光，"}},
        {"id": "2", "event": "line", "data": {"poem_id": "jingyesi", "line_no": 2, "text": "疑是地上霜。"}},
        {"id": "3", "event": "line", "data": {"poem_id": "jingyesi", "line_no": 3, "text": "举头望明月，"}},
        {"id": "4", "event": "line", "data": {"poem_id": "jingyesi", "line_no": 4, "text": "低头思故乡。"}},
        {"id": "5", "event": "done", "data": {"poem_id": "jingyesi", "status": "completed", "sent_lines": 4}},
    ]
    missing = client.get("/poems/not-found/stream?interval_ms=0")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "古诗不存在"}
    assert client.get("/poems/jingyesi/stream?interval_ms=-1").status_code == 422
    assert client.get("/poems/jingyesi/stream?interval_ms=2001").status_code == 422
    second_poem = client.get("/poems/dengguanquelou/stream?interval_ms=0")
    assert second_poem.status_code == 200
    assert second_poem.text.count("event: line") == 4
    assert '"text":"更上一层楼。"' in second_poem.text


if __name__ == "__main__":
    # 直接运行本文件时，依次执行两道题的公开检查。
    # 尚未完成的题显示“尚未作答”；断言失败会显示具体出错位置。
    for name, check in [("技能1", check_question_1), ("技能2", check_question_2)]:
        try:
            check()
        except NotImplementedError:
            print(name + "：尚未作答")
        else:
            print(name + "：公开检查通过（仍需人工核对全部题目要求）")
