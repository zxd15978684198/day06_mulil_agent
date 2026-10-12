import uuid

from fastapi import FastAPI, Path, Query, Form, UploadFile, File, HTTPException, status, Depends
import json
import pathlib

from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

from starlette.staticfiles import StaticFiles

app = FastAPI(
    title="学习写接口",
    version="1.0.0",
    description=""
)

# 创建一个 Path 对象 DATA_FILE，指向当前 Python 脚本所在目录下的 users.json 文件
DATA_FILE = pathlib.Path(__file__).with_name("users.json")

# 收到 GET /users 时，FastAPI 才会调用 list_users()。
# @app.get("/users")
# async def list_users() -> list[dict]:
#     # 读取 JSON文本，再转换成python列表
#     text = DATA_FILE.read_text(encoding="utf-8")
#     return json.loads(text)

# 路径参数
@app.get("/users/{user_id}")
async def get_user(user_id: Annotated[int,Path(ge=1,description="用户ID")]) -> dict:
    return {"user_id": user_id}

# upload_dir
UPLOAD_DIR = pathlib.Path(__file__).with_name("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# 根据允许的图片的类型决定扩展名
IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 最大 5 MB。

# 把服务器本地某个文件夹（UPLOAD_DIR）暴露成可通过 URL 访问的静态资源。
"""
逐行解释：

app.mount(...)：把一个“子应用”或静态文件处理器挂载到某个 URL 路径下。

"/uploads"：URL 前缀。访问 http://你的域名/uploads/... 时会进入这个静态文件服务。

StaticFiles(directory=UPLOAD_DIR)：创建一个静态文件服务，文件来源是本地目录 UPLOAD_DIR。

name="uploads"：给这个挂载点起个名字，主要用于反向生成 URL，比如 request.url_for("uploads", path="xxx.jpg")。
"""
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

user_path = pathlib.Path(__file__).parent / "users.json"

@app.get("/users")
def users(
    keyword: Annotated[
            str | None,
            Query(min_length=1, max_length=20, description="按用户名搜索"),
        ] = None,
    role: str | None = None,
    page: int = 1,
    pagesize: int = 5,
) -> list[dict]:

    users_data = json.loads(user_path.read_text(encoding="utf-8"))
    results = users_data.copy()
    print("keyword", keyword)
    print("roel", role)

    if keyword is not None:
        results = [user for user in results if keyword in user["full_name"]]

    if role is not None:
        results = [user for user in results if user["role"] == role]

    start = (page-1) * pagesize
    end = start + pagesize
    return results[start:end]

# 定义请求体类型
class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=20)
    full_name: str
    role: str
    active: bool = True

# 定义post接口
@app.post("/messages", response_model=UserCreate)
def create_message(payload: UserCreate) -> dict[str, str]:
    print("接收json格式参数", payload.model_dump())
    return {"message": "success"}

@app.post("users/create")
async def create_message(payload: UserCreate) -> dict[str, str]:
    print("接收json格式参数", payload)
    user_data = json.loads(user_path.read_text(encoding="utf-8"))

    user_data.append({
        "id":user_data[-1]["id"] + 1,
        **payload.model_dump()
    })
    user_path.write_text(json.dumps(user_data,indent=4,ensure_ascii=False), encoding="utf-8")
    return {"message": "创建成功"}

class loginResponse(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    message: str

"""
1.接受表单格式数据
2.约束接口的返回字段response_model=loginResponse
"""
@app.post("/login",response_model=loginResponse,status_code=status.HTTP_403_FORBIDDEN)
async def login_form(
        username: Annotated[str, Form()],
        remember: Annotated[bool, Form()] = False
) -> dict:
    print("username", username)
    print("remember", remember)

    return {
        "username": username,
        "message": "登录成功",
        "age":11
    }


@app.post("/profile")
async def upload_profile_file(
    display_name: Annotated[str, Form()],
    avatar: Annotated[UploadFile, File()],
) -> dict:
    # content_type表示客户端声明的文件类型
    suffix=IMAGE_TYPES.get(avatar.content_type or "")
    if suffix is None:
        raise HTTPException(
            status_code=400,
            detail="只允许上传JPG和PNG格式的图片"
        )

    # 多读一字节，判断图片是否超过大小限制
    content = await avatar.read(MAX_IMAGE_SIZE+1)
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="图片不能超过5 MB"
        )

    # 使用随即名称保存，防止重命名，也不信任用户提供的原始文件名
    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = UPLOAD_DIR / filename
    file_path.write_bytes(content)
    return {
        "message": "上传成功",
        "display_name": display_name,
        "original_filename": avatar.filename,
        "size": avatar.size,
        "content_type": avatar.content_type,
        "saved_filename": filename,
        "image_url":f"/uploads/{filename}"
    }

# 接收表单格式数据
@app.post("/remove/user")
async def remove_user(
    id: int
) -> dict:
    if id < 0 or id > 20:
        raise HTTPException(
            status_code=404,
            detail="此用户id不存在"
        )

    return {"message": "删除成功"}

def get_user_or_404(user_id: int) -> dict:
    user_data=json.loads(user_path.read_text(encoding="utf-8"))

    user = [user for user in user_data if user["id"] == user_id]
    if not user:
        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )

    return user[0], user_data

# 定义接口
@app.put("/users/{user_id}")
async def update_user(user_info: Annotated[UserCreate,Depends(get_user_or_404)],payload: UserCreate) -> dict:
    print("user_info", user_info)
    print("payload", payload)

    user,user_data=user_info
    user.update(**payload.model_dump())

    user_path.write_text(json.dumps(user_data,indent=4,ensure_ascii=False), encoding="utf-8")
    return {
        "message":"更新成功"
    }


# 定义请求体类型
class UserUpdate(BaseModel):
    # 校验前自动清理所有字段的前后空格
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str| None = Field(default=None,min_length=3, max_length=20)
    full_name: str | None = None
    role: str | None = None
    active: bool | None = None

@app.patch("/users/{user_id}")
async def update_user(
    user_info: Annotated[UserUpdate,Depends(get_user_or_404)],
    payload: UserUpdate,
) -> dict[str, str]:
    # 读取数据库,按照id查找用户是否存在
    user,user_data=user_info

    # 把参数中没有值的属性剔除,如果剔除后没有数据就报错
    changes = payload.model_dump(
        exclude_unset=True, # 排除客户端没有提交的字段
        exclude_none=True,  #
    )

    if not changes:
        raise HTTPException(
            status_code=400,
            detail="至少提交一个需要修改的字段"
        )

    # 修改数据库,
    user.update(**payload.model_dump())
    user_path.write_text(json.dumps(user_data,indent=4,ensure_ascii=False), encoding="utf-8")

    return {"message":"修改成功"}
