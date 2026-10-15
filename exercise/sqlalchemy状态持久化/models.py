import os
from pathlib import Path
from typing import Annotated, List

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, status, HTTPException
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pydantic import BaseModel, ConfigDict, Field


class Base(DeclarativeBase):
    """ORM模型共同的基类"""

class User(Base):
    __tablename__ = 'user'

    id: Mapped[int] = mapped_column(primary_key=True,autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

# 创建Engine，理解连接池
load_dotenv()
DATABASE_URL = (os.getenv('DATABASE_URL') or "").strip()
if not DATABASE_URL:
    raise ValueError("请在 .env中配置 DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    # 取出连接时先检查它是否能用
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    bind=engine,
    # 关闭查询前的自动同步，
    autoflush=False,
    expire_on_commit=False
)

statement = select(User).where(User.username == 'zhang_wei')

# 创建或关闭一个session
with SessionLocal() as session:
    user = session.scalar(statement)
    if user is None:
        print("未找到预置用户 zhang_wei")
    else:
        print(
            "查询结果：",
            user.id,
            user.name,
            user.display_name,
            user.active
        )

def create_demo_user():
    with SessionLocal() as db:
        existing_user = db.scalar(select(User).where(User.username == 'crud_demo'))
        if existing_user is not None:
            print("Create: 教学用户已经存在", existing_user.id)
            return

        user = User(
            username="crud_demo",
            display_name="CRUD 教学用户",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print("Create：",user.id,user.username,user.display_name)

# 查询单个用户
def read_one_user():
    with SessionLocal() as db:
        statement = select(User).where(User.username == 'crud_demo')
        user = db.scalar(statement)
        if user is None:
            print("Read one: 用户不存在")
        else:
            print(
                "Read one",
                user.id,
                user.username,
                user.display_name,
                user.active
            )

# 查询多个用户
def read_al_user():
    with SessionLocal() as db:
        statement = select(User).order_by(User.id)
        users = db.scalar(statement).all()

        print("Read List")
        for user in users:
            print(user.id,user.username,user.display_name)

# 构造查询
statement = select(User).where(User.username == 'crud_demo').order_by(User.id).limit(1).offset(1)

# 手动管理事务
with SessionLocal() as db:
    try:
        user = db.scalar(select(User).where(User.username == 'transaction_demo'))
        if user is None:
            user = User(
                username="transaction_demo",
                display_name="transaction_demo",
                active=True,
            )
            db.add(user)
        else:
            user.display_name="事务教学用户"
        db.commit()
        print("事务提交成功")
    except SQLAlchemyError:
        db.rollback()
        print("事务执行失败，已经回滚")
        raise

# 提交失败后回滚
with SessionLocal() as db:
    duplicated_user = User(
        username="zhang_wei",
        display_name="重复用户",
        active=True,
    )
    db.add(duplicated_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        print("用户名重复，事务已回滚")
    user_count = db.scalar(select(func.count()).select_from(User))
    print("回滚后仍可查询，当前用户数：", user_count)

with SessionLocal.begin() as db:
    user = db.scalar(select(User).where(User.username == 'transaction_demo'))
    if user is None:
        raise ValueError("用户不存在")

    db.delete(user)


from collections.abc import Generator
from sqlalchemy.orm import Session

def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        yield db

class APIModel(BaseModel):
    """本项目请求和响应模型的基类"""

    #所有继承他的模型都会取出字符串首尾空格
    model_config = ConfigDict(str_strip_whitespace=True)

class UserCreate(APIModel):
    username: str = Field(min_length=3, max_length=50)
    display_name: str = Field(min_length=1, max_length=50)

class UserResponse(APIModel):
    """允许Pydantic从User ORM对象属性中读取数据"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    active: bool


# 完成用户查询列表接口
app = FastAPI(title="SQLALchemy持久化基础")
DbSession = Annotated[Session,Depends(get_db)]

# 增加列表查询接口
@app.get("/users",response_model=List[UserResponse])
def list_Users(db: DbSession) -> List[User]:
    statement = select(User).order_by(User.id)
    return list(db.scalars(statement).all())

# 完成数据创建接口，并解决数据冲突
@app.post("/users",response_model=UserResponse,status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession) -> User:
    user = User(
        username=payload.username,
        display_name=payload.display_name,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已经存在"
        ) from e
    except SQLAlchemyError as e:
        db.rollback()
        raise

    return user

# 使用AsyncSqliteSaver完成跨重启恢复
PROJECT_DIR = Path(__file__).resolve().parent

# 从项目目录读取.env,避免启动位置不同导致找不到位置
load_dotenv(PROJECT_DIR / ".env",override=False)




