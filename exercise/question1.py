import fastapi
from fastapi import FastAPI
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query
# StreamingResponse 用于第2题持续返回 SSE 事件文本。
from fastapi.responses import StreamingResponse
# TestClient 只在文件末尾的公开检查中调用 API，学生不需要修改它。
from fastapi.testclient import TestClient
# BaseModel 用于定义 API 对外返回的图书结构。
from pydantic import BaseModel, Field

# 图书目录查询app

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
            limit: int = Query(default=1, le=20),
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


client = TestClient(build_book_app())
headers = {"X-Client-Id": "classroom"}
response = client.get(
    "/books?category=programming&max_price=60&limit=1",
    headers=headers,
)
print(response.status_code)
# 200
print(response.json())
# [{"id": 1, "title": "Python入门", "category": "programming", "price": 59.0}]

print(client.get("/books/99", headers=headers).json())
# {"detail": "图书不存在"}

print(client.get("/books?category=missing", headers=headers).json())
# []

print(client.get("/books?limit=0", headers=headers).status_code)
# 422