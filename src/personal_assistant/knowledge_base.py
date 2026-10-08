"""知识库解析、切分、Embedding、权限元数据与 Chroma 写入。

阶段分工（本文件按 Day06 执行计划 v2 的分阶段门禁推进）：

* **P2（阶段 2）** —— K1 七条 `parser_mode` 分流解析、K6 OCR/多模态标注、K7 失败保留；
* **P3（阶段 2）** —— K2 `allow_<role>` 展开、K3 切分、K4 元数据继承、Chroma 持久化、
  写 `vector_store/index_manifest.json`；
* **P4（阶段 3）** —— K8 检索期角色过滤（`search_knowledge`），本文件届时补上。

设计要点（Day06 执行计划 v2 §4.1）：

* 解析路径**按清单的 `parser_mode` 分流**，不用一个通用 Loader 硬套十份文件；
* 权限只读清单的 `allowed_roles`，**不从目录名 `public/` `hr/` 推断**；
* Chroma 元数据只接受标量，因此 `allowed_roles` 展开成 `allow_employee` / `allow_hr`
  两个布尔字段（K2），检索时用 `where={"allow_<role>": True}`，缺键即被排除（fail-closed）；
* 解析失败**不静默丢弃**，记入索引清单的 `failures`（K7）。
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from .paths import ENV_PATH, KNOWLEDGE_DIR, PROJECT_ROOT, VECTOR_STORE_DIR

# 必须在导入 huggingface_hub / sentence-transformers 之前加载 .env：
# huggingface_hub 在 import 时读取 HF_ENDPOINT，晚设置就不生效了。
load_dotenv(ENV_PATH, override=False)

from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_huggingface import HuggingFaceEmbeddings  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402
from langchain.tools import ToolRuntime, tool  # noqa: E402

# --------------------------------------------------------------------------
# 路径与常量
# --------------------------------------------------------------------------

MANIFEST_PATH = KNOWLEDGE_DIR / "day05_knowledge_manifest.json"
INDEX_MANIFEST_PATH = VECTOR_STORE_DIR / "index_manifest.json"

COLLECTION_NAME = "day05_knowledge"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# K3：中文分隔符序列与初始切分参数（工程估计，P3 抽查后定值）
CHUNK_SIZE = 600
CHUNK_OVERLAP = 120
CHINESE_SEPARATORS = ["\n\n", "\n", "。", "；", "！", "？", "，", " ", ""]
# 中文用 "end"：句号留在上一块末尾，而不是跑到下一块开头
KEEP_SEPARATOR: str = "end"

# 支持过滤的角色（RunContext 只会产生这两个值）
FILTERABLE_ROLES = ("employee", "hr")

OCR_NOTICE = "【本段为机器识别（OCR）结果，不是原始文档文本，请勿作为原文引用】"
VISION_NOTICE = (
    "【本段为视觉模型对图片的机器识别描述，不是原始文档文本，请勿作为原文引用】"
)

# OCR 渲染倍率（pypdfium2 渲染扫描件用；2.0 在本项目扫描件上识别置信度已足够）
OCR_RENDER_SCALE = 2.0

# 视觉模型提示词：导览图要求方位关系（K5），海报要求分组与颜色语义。
# 两条都要求"只依据图中实际可见内容"，避免模型补充图中没有的设施。
MAP_VISION_PROMPT = """你在为一份办公区导览图生成可检索的文字说明。请只依据图中**实际可见**的内容作答，
不要推测、不要补充图中没有的设施。按下面四条逐条列出，每条用短句：

1. 图中出现的全部文字标签（逐个列出）；
2. 各区域之间的相对方位关系，用"东/西/南/北"或"左/右/上/下"明确表述，
   例如"X 位于 Y 的东侧"（至少给出六组这样的关系）；
3. 箭头与推荐路线的起点、终点和方向；
4. 颜色标记及其对应的区域或含义。

最后单独一行写明"上方为北"。"""

POSTER_VISION_PROMPT = """你在为公司内部宣传海报生成可检索的文字说明。请只依据图中**实际可见**的内容作答，
不要推测、不要补充图中没有的内容。按下面四条逐条列出：

1. 海报标题与全部可见文字（按版面顺序逐个列出，保留编号）；
2. 编号条目及其各自的分点内容（每条编号下有几个要点，分别是什么）；
3. 颜色标记及其对应的分组或含义；
4. 版面结构（共几个分区、如何排列、每个分区内部如何组织）。"""


# --------------------------------------------------------------------------
# 环境适配：临时目录
#
# 本模块**不自行修改**进程全局状态：`ensure_writable_tempdir()` 由入口脚本
# （build_index.py / main.py）显式调用。库侧只做检查，不可用时抛出可操作的错误。
# --------------------------------------------------------------------------

TEMP_WORKAROUND_DIR = PROJECT_ROOT / ".tmp"


def _probe_writable(directory: Path) -> str | None:
    """可写则返回 None，否则返回**失败原因**（写不进去 / 删不掉要分开说）。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write_probe_{os.getpid()}"
        probe.write_text("x", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"创建探测文件失败：{type(exc).__name__}: {exc}"
    try:
        probe.unlink()
    except Exception as exc:  # noqa: BLE001
        # 能写但删不掉：chromadb 的 SQLite 需要建/删临时文件，所以同样算不可用
        return f"能写但删不掉探测文件：{type(exc).__name__}: {exc}"
    return None


def _is_writable_dir(directory: Path) -> bool:
    return _probe_writable(directory) is None


def _unwritable_tempdir() -> tuple[str, str] | None:
    """返回第一个不可写的 `TEMP`/`TMP` 值及其原因；都可用则返回 None。"""
    for key in ("TEMP", "TMP"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        reason = _probe_writable(Path(raw))
        if reason is not None:
            return raw, reason
    return None


def ensure_writable_tempdir() -> str | None:
    """入口脚本调用：挑一个**确实可写**的临时目录；都不行就在入口直接失败。

    **为什么需要**：chromadb 1.5.9 的 Rust SQLite 在建立连接时使用操作系统
    临时目录（Windows 上是 `GetTempPathW`）。若该目录不可写，建库与检索都会失败：

        chromadb.errors.InternalError:
        error returned from database: (code: 14) unable to open database file

    注意 `tempfile.gettempdir()` **不能**用来判断：它发现 `%TEMP%` 不可写时会静默
    回落到当前目录，于是看起来"临时目录没问题"，而 chroma 拿到的仍是 `%TEMP%`。
    所以这里直接探测 `TEMP`/`TMP` 指向的目录。

    候选顺序（**每个都要真的写进去再删掉**，不靠"目录存在"就当作可用）：

    1. `%TEMP%` / `%TMP%` —— 正常机器直接命中，本函数什么都不做也不打印；
    2. 项目内的 `.tmp/`（跨运行复用）；
    3. 由**本进程新建**的目录 —— 创建者一定拥有写权限，用于绕开历史遗留的异常权限。

    正常机器上 `%TEMP%` 可写，本函数**什么都不做、什么都不打印**（返回 None）。
    """
    if _unwritable_tempdir() is None:
        return None

    tried: list[str] = []
    for candidate in (TEMP_WORKAROUND_DIR,):
        reason = _probe_writable(candidate)
        if reason is None:
            return _use_tempdir(candidate, tried)
        tried.append(f"{candidate} —— {reason}")

    # 兜底：新建一个属于本进程的目录（创建者必然可写）
    import tempfile

    try:
        fresh = Path(tempfile.mkdtemp(prefix="day06_tmp_", dir=str(PROJECT_ROOT)))
    except Exception as exc:  # noqa: BLE001
        tried.append(f"mkdtemp(dir=PROJECT_ROOT) —— {type(exc).__name__}: {exc}")
    else:
        reason = _probe_writable(fresh)
        if reason is None:
            return _use_tempdir(fresh, tried)
        tried.append(f"{fresh}（新建后仍不可用）—— {reason}")

    raise RuntimeError(
        "找不到可写的临时目录，chromadb 无法工作。已尝试：\n  - "
        + "\n  - ".join(tried)
        + f"\n当前 TEMP={os.environ.get('TEMP')!r} TMP={os.environ.get('TMP')!r}\n"
        "请把 TEMP / TMP 指向一个可写目录，或用 `uv run python build_index.py` / "
        "`uv run python main.py` 这类入口脚本运行（它们会调用本函数）。\n"
        "提示：用 `icacls <目录>` 看权限，若出现 "
        "'Mandatory Label\\Low Mandatory Level' 说明该目录带低完整性标签，"
        "普通进程可能无法写入。"
    )


def _use_tempdir(directory: Path, tried: list[str]) -> str:
    resolved = str(directory)
    os.environ["TEMP"] = resolved
    os.environ["TMP"] = resolved
    os.environ.setdefault("TMPDIR", resolved)
    print(f"[环境] 系统临时目录 %TEMP% 不可写，本次运行改用：{resolved}")
    return resolved


def _require_usable_tempdir() -> None:
    """库侧检查：临时目录不可写时给出可操作的错误，而不是让 chroma 抛晦涩异常。"""
    broken = _unwritable_tempdir()
    if broken is None:
        return
    bad, reason = broken
    raise RuntimeError(
        f"系统临时目录不可写（{bad}）：{reason}\n"
        f"chromadb 会报 (code: 14) unable to open database file。"
        f"请通过入口脚本运行（build_index.py 建库、main.py 对话，"
        f"两者启动时都会调用 ensure_writable_tempdir()），"
        f"或先把 TEMP / TMP 指向一个可写目录。"
    )


# --------------------------------------------------------------------------
# 解析层（K1）：每种 parser_mode 一条独立路径
# --------------------------------------------------------------------------


@dataclass
class Block:
    """解析出的一个语义块。表格独立成块，不与正文混切（K3）。"""

    text: str
    kind: str = "prose"  # "prose" | "table"


@dataclass
class ParsedDocument:
    """一份文档的解析结果。"""

    blocks: list[Block] = field(default_factory=list)
    parser_mode_actual: str = ""
    is_machine_extracted: bool = False
    # 机器识别的来源证据（用了哪个模型、是否降级），写入索引清单供核对
    provenance: dict[str, str] = field(default_factory=dict)


def _read_text(path: Path) -> str:
    # 知识文件是 UTF-8；用 utf-8-sig 顺带吃掉可能的 BOM
    return path.read_text(encoding="utf-8-sig")


def _collapse_blank_lines(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if not line.strip() and (not out or not out[-1].strip()):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _ensure_nonempty(text: str, path: Path) -> str:
    """解析结果为空必须报错，不能当作"空文档"静默丢弃（K7）。"""
    if not text or not text.strip():
        raise ValueError(
            f"{path.name} 解析结果为空：该格式的解析路径可能未生效"
            f"（扫描件应走 ocr_required，请检查清单 parser_mode）"
        )
    return text


def _parse_text(path: Path) -> ParsedDocument:
    """markdown / txt：直接读文本，保留标题层级供切分使用。"""
    return ParsedDocument(
        blocks=[Block(_ensure_nonempty(_read_text(path), path))],
        parser_mode_actual="text",
    )


def _parse_docx(path: Path) -> ParsedDocument:
    """docx：段落与表格分别取，表格独立成块。"""
    import docx  # python-docx

    document = docx.Document(str(path))
    blocks: list[Block] = []

    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    if paragraphs:
        blocks.append(Block("\n".join(paragraphs)))

    for index, table in enumerate(document.tables, start=1):
        rows: list[str] = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        if rows:
            blocks.append(Block(f"【表格 {index}】\n" + "\n".join(rows), kind="table"))

    if not blocks:
        raise ValueError(f"{path.name} 解析结果为空：python-docx 未取到段落或表格")
    return ParsedDocument(blocks=blocks, parser_mode_actual="document_text")


def _parse_pdf_text(path: Path) -> ParsedDocument:
    """普通 PDF：pypdf 抽文本层。"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(page for page in pages if page)
    return ParsedDocument(
        blocks=[
            Block(
                _ensure_nonempty(
                    _collapse_blank_lines(text),
                    path,
                )
            )
        ],
        parser_mode_actual="pdf_text",
    )


def _parse_html(path: Path) -> ParsedDocument:
    """html：去脚本与样式后取正文。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_read_text(path), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    body = soup.get_text(separator="\n")
    text = _collapse_blank_lines(body)
    if title and not text.startswith(title):
        text = f"{title}\n{text}"
    return ParsedDocument(
        blocks=[Block(_ensure_nonempty(text, path))],
        parser_mode_actual="html_text",
    )


def _ocr_lines(result: Any) -> list[str]:
    """把 RapidOCR 的 [[box, text, score], ...] 还原成按阅读顺序排列的行。"""
    if not result:
        return []

    items: list[tuple[float, float, float, str]] = []
    for entry in result:
        try:
            box, text, _score = entry[0], entry[1], entry[2]
        except (IndexError, TypeError):
            continue
        text = str(text).strip()
        if not text:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append((sum(ys) / len(ys), min(xs), max(xs), text))

    if not items:
        return []

    items.sort(key=lambda item: item[0])
    heights = [abs(items[i + 1][0] - items[i][0]) for i in range(len(items) - 1)]
    line_gap = max(12.0, (min(heights) if heights else 20.0) * 0.6)

    lines: list[str] = []
    current: list[tuple[float, float, str]] = []
    anchor = items[0][0]
    for y_center, x_min, x_max, text in items:
        if current and abs(y_center - anchor) > line_gap:
            lines.append(_join_line(current))
            current = []
            anchor = y_center
        current.append((x_min, x_max, text))
    if current:
        lines.append(_join_line(current))
    return lines


def _join_line(parts: list[tuple[float, float, str]]) -> str:
    """同一行内按 x 排序拼接；中文之间不加空格，其余情况加空格。"""
    parts = sorted(parts, key=lambda part: part[0])
    out = ""
    for _x_min, _x_max, text in parts:
        if not out:
            out = text
            continue
        prev, nxt = out[-1], text[0]
        cjk = lambda ch: "\u3000" <= ch <= "\u9fff"  # noqa: E731
        out += "" if (cjk(prev) and cjk(nxt)) else " "
        out += text
    return out


def _run_ocr(image: Any) -> list[str]:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    result, _elapse = engine(image)
    return _ocr_lines(result)


def _parse_ocr_pdf(path: Path) -> ParsedDocument:
    """无文本层的扫描 PDF：pypdfium2 渲染成位图 → RapidOCR（K6）。"""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        pages: list[str] = []
        for page in pdf:
            image = page.render(scale=OCR_RENDER_SCALE).to_pil()
            lines = _run_ocr(image)
            if lines:
                pages.append(f"【第 {len(pages) + 1} 页】\n" + "\n".join(lines))
    finally:
        pdf.close()

    text = _ensure_nonempty("\n\n".join(pages), path)
    return ParsedDocument(
        blocks=[Block(f"{OCR_NOTICE}\n{text}")],
        parser_mode_actual="ocr",
        is_machine_extracted=True,
    )


def _parse_image_ocr(path: Path) -> ParsedDocument:
    """图片：RapidOCR 取可见文字（`ocr_or_multimodal` 的默认路径）。"""
    lines = _ensure_nonempty_lines(_run_ocr(str(path)), path)
    return ParsedDocument(
        blocks=[Block(f"{OCR_NOTICE}\n" + "\n".join(lines))],
        parser_mode_actual="ocr",
        is_machine_extracted=True,
    )


def _ensure_nonempty_lines(lines: list[str], path: Path) -> list[str]:
    if not lines:
        raise ValueError(f"{path.name} OCR 结果为空：OCR 未生效或图片无文字")
    return lines


def new_session_id() -> str:
    """生成一个用于网关 `x-opencode-session` 的会话 ID（每次会话一个，保持稳定）。"""
    return f"day06-{uuid.uuid4().hex[:16]}"


# 进程级默认会话 ID：同一次运行内的多次模型调用共用它，避免把一次会话拆成多个会话。
PROCESS_SESSION_ID = new_session_id()


def _extra_headers_for(base_url: str, session_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    raw = (os.getenv("EXTRA_HEADERS_JSON") or "").strip()
    if raw:
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError("EXTRA_HEADERS_JSON 必须是 JSON 对象")
        headers.update({str(k): str(v) for k, v in loaded.items()})

    # opencode Go 网关要求每会话一个稳定 ID，缺了直接 400 MissingSessionID。
    # 这里按 BASE_URL 判定，只对该网关补头；其它 OpenAI 兼容服务不受影响。
    if "opencode.ai" in base_url:
        headers.setdefault("x-opencode-session", session_id or PROCESS_SESSION_ID)
        headers.setdefault("user-agent", "day06-multi-agent/1.0")
    return headers


def resolve_model_config(prefix: str = "") -> tuple[str, str, str]:
    """解析模型配置，返回 `(provider, model_name, source)`。

    * `prefix=""` → 聊天模型（`MODEL_PROVIDER` / `MODEL_NAME`）；
    * `prefix="VISION_"` → 多模态接口（`VISION_MODEL_PROVIDER` / `VISION_MODEL_NAME`）。

    **多模态用单独接口**：导览图与海报走 `VISION_*`。若没有单独配置，则回落到
    聊天模型，并把 `source` 标成 `vision_fallback` —— 让 manifest 如实记录到底用了谁。
    """
    provider = (os.getenv(f"{prefix}MODEL_PROVIDER") or "").strip()
    name = (os.getenv(f"{prefix}MODEL_NAME") or "").strip()

    if prefix and (not provider or not name):
        fallback_provider, fallback_name, _ = resolve_model_config("")
        return fallback_provider, fallback_name, "vision_fallback"

    if not provider or not name:
        raise RuntimeError(
            f"请在 .env 中配置 {prefix}MODEL_PROVIDER 和 {prefix}MODEL_NAME"
        )
    return provider, name, "vision" if prefix else "chat"


def build_model_options(
    prefix: str = "", session_id: str | None = None
) -> dict[str, Any]:
    """构造 `init_chat_model` 的通用参数（含本机网关要求的会话头）。

    `multi_agent.build_model()` 复用 `prefix=""` 这一路，避免两处各写一遍。
    """
    options: dict[str, Any] = {"timeout": 120, "max_retries": 2}
    api_key = (os.getenv(f"{prefix}API_KEY") or "").strip()
    base_url = (os.getenv(f"{prefix}BASE_URL") or "").strip()
    if not api_key and prefix:
        api_key = (os.getenv("API_KEY") or "").strip()
    if not base_url and prefix:
        base_url = (os.getenv("BASE_URL") or "").strip()
    if api_key:
        options["api_key"] = api_key
    if base_url:
        options["base_url"] = base_url

    headers = _extra_headers_for(base_url, session_id)
    if headers:
        options["default_headers"] = headers
    return options


def build_chat_model(prefix: str = "", session_id: str | None = None) -> tuple[Any, str, str]:
    """按配置构造模型，返回 `(model, model_name, source)`。"""
    from langchain.chat_models import init_chat_model

    provider, name, source = resolve_model_config(prefix)
    model = init_chat_model(
        name,
        model_provider=provider,
        **build_model_options(prefix, session_id=session_id),
    )
    return model, name, source


def _describe_image(
    path: Path, prompt: str, mode_label: str
) -> ParsedDocument:
    """把图片交给多模态接口，生成可检索的文字说明（K5）。"""
    import base64

    model, model_name, source = build_chat_model("VISION_")
    encoded = base64.b64encode(path.read_bytes()).decode()
    suffix = path.suffix.lower().lstrip(".") or "png"
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/{suffix};base64,{encoded}"},
            },
        ],
    }
    reply = model.invoke([message])
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    text = _ensure_nonempty(text, path)
    return ParsedDocument(
        blocks=[Block(f"{VISION_NOTICE}\n{text}")],
        parser_mode_actual=mode_label,
        is_machine_extracted=True,
        provenance={
            "machine_reader": "vision_model",
            "model_name": model_name,
            "config_source": source,
        },
    )


def _parse_map_vision(path: Path) -> ParsedDocument:
    """导览图（`multimodal_required`）：版面、方位、箭头、颜色（K5）。"""
    return _vision_or_ocr_fallback(path, MAP_VISION_PROMPT)


def _parse_poster_vision(path: Path) -> ParsedDocument:
    """海报（`ocr_or_multimodal`）：实测视觉输出是 OCR 的严格超集（含全部分组、
    颜色语义与版面结构），故按 K1「可升级为视觉模型」升级。"""
    return _vision_or_ocr_fallback(path, POSTER_VISION_PROMPT)


def _vision_or_ocr_fallback(path: Path, prompt: str) -> ParsedDocument:
    """先走多模态接口；不成立时按 K5 降级为 OCR，并如实记 `ocr_fallback`。

    降级不是静默：`parser_mode_actual` 与 provenance 都会记进索引清单，
    验收时能看出这条内容其实只有 OCR 水平（例如导览图会丢掉全部空间关系，
    §8 第 18 条届时必须记为「无法完成」而不是「通过」）。
    """
    try:
        return _describe_image(path, prompt, "vision_multimodal")
    except Exception as exc:  # noqa: BLE001 —— 降级路径，异常要记下来而不是吞掉
        degraded = _parse_image_ocr(path)
        degraded.parser_mode_actual = "ocr_fallback"
        degraded.provenance = {
            "machine_reader": "ocr",
            "config_source": "vision_failed",
            "vision_error": f"{type(exc).__name__}: {exc}"[:300],
        }
        return degraded


PARSERS: dict[str, Callable[[Path], ParsedDocument]] = {
    "text": _parse_text,
    "document_text": _parse_docx,
    "pdf_text": _parse_pdf_text,
    "html_text": _parse_html,
    "ocr_required": _parse_ocr_pdf,
    "multimodal_required": _parse_map_vision,
    "ocr_or_multimodal": _parse_poster_vision,
}


# --------------------------------------------------------------------------
# 切分（K3）与元数据（K4 + K2）
# --------------------------------------------------------------------------


def _make_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        separators=CHINESE_SEPARATORS,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        keep_separator=KEEP_SEPARATOR,
    )


def _split_blocks(
    blocks: list[Block], splitter: RecursiveCharacterTextSplitter
) -> list[str]:
    """正文按分隔符递归切分；表格整块保留，不与正文混切（K3）。"""
    chunks: list[str] = []
    for block in blocks:
        if block.kind == "table":
            chunks.append(block.text.strip())
        else:
            chunks.extend(splitter.split_text(block.text))
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _chunk_metadata(
    entry: dict[str, Any],
    parsed: ParsedDocument,
    index: int,
    allowed_roles: list[str],
) -> dict[str, Any]:
    document_id = entry["document_id"]
    metadata: dict[str, Any] = {
        "document_id": document_id,
        "title": entry.get("title", ""),
        "path": entry["path"],
        "version": str(entry.get("version", "")),
        "status": str(entry.get("status", "")),
        "parser_mode": entry.get("parser_mode", ""),
        "parser_mode_actual": parsed.parser_mode_actual,
        # 以下是展示/排错字段，**不用于过滤**
        "access_scope": entry.get("access_scope", ""),
        "allowed_roles_csv": ",".join(allowed_roles),
        "is_machine_extracted": bool(parsed.is_machine_extracted),
        "chunk_index": index,
        "chunk_id": f"{document_id}#{index:03d}",
    }
    # K2：Chroma 元数据只接受标量，权限展开为每角色一个布尔字段
    for role in FILTERABLE_ROLES:
        metadata[f"allow_{role}"] = role in allowed_roles
    return metadata


# --------------------------------------------------------------------------
# 建库
# --------------------------------------------------------------------------


def _build_embeddings() -> tuple[HuggingFaceEmbeddings, str]:
    model_name = (os.getenv("EMBEDDING_MODEL") or "").strip() or DEFAULT_EMBEDDING_MODEL
    embeddings = HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    return embeddings, model_name


def _reset_collection() -> None:
    """删除本项目的 Chroma collection，避免重建时重复入库。

    做法（与原计划不同，见汇报里的偏离说明）：

    1. 只删 `COLLECTION_NAME` 这一个 collection，**不碰 `vector_store/` 里
       用户自己放的任何文件**；
    2. `delete_collection()` 不会清理 Chroma 自己生成的 HNSW 段目录，放任不管会
       每次重建堆积一套孤儿目录。所以**只在库中已无任何 collection 时**清扫这些
       段目录 —— 库里还有别的 collection 就一律不动；
    3. 每一步都打印，不留静默的破坏性操作。
    """
    import chromadb

    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))

    names = {getattr(item, "name", str(item)) for item in client.list_collections()}
    if COLLECTION_NAME in names:
        client.delete_collection(COLLECTION_NAME)
        print(f"[索引] 已删除旧的 collection：{COLLECTION_NAME}")

    if client.list_collections():
        return  # 库里还有别人的 collection，孤儿清扫跳过

    for child in sorted(VECTOR_STORE_DIR.iterdir()):
        if child.is_dir():  # Chroma 的 HNSW 段目录（UUID 命名）
            shutil.rmtree(child)
            print(f"[索引] 已清理孤儿索引段：{child.name}")


def build_vector_store() -> dict[str, Any]:
    """解析 → 切分 → Embedding → 写 Chroma，并保存索引清单。

    返回 `build_index.py` 需要的四个键（另有 `failures` 供调用方打印）。
    """
    # 临时目录由入口脚本负责适配；库侧只检查，不可用就给可操作的错误
    _require_usable_tempdir()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = manifest["documents"]

    splitter = _make_splitter()
    documents: list[Document] = []
    document_summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for entry in entries:
        relative = entry["path"]
        source = KNOWLEDGE_DIR / relative
        parser_mode = entry.get("parser_mode", "")

        try:
            if not source.exists():
                raise FileNotFoundError(f"清单里的文件不存在：{relative}")
            parser = PARSERS.get(parser_mode)
            if parser is None:
                raise ValueError(f"未知的 parser_mode：{parser_mode!r}")

            # 逐份打印进度：视觉/OCR 调用可能很慢，没有进度就无法判断卡在哪里
            print(
                f"[解析] {entry['document_id']}  {relative}  ({parser_mode}) ...",
                flush=True,
            )

            # 权限一律读清单，不从目录名推断；缺失即报错，不能默认放开
            allowed_roles = entry.get("allowed_roles")
            if not allowed_roles:
                raise ValueError(
                    f"{relative} 缺少 allowed_roles，拒绝入库（否则权限会静默放开）"
                )

            parsed = parser(source)
            chunks = _split_blocks(parsed.blocks, splitter)
            if not chunks:
                raise ValueError(f"{relative} 切分后没有 chunk")
            print(
                f"[解析]   -> {parsed.parser_mode_actual}  {len(chunks)} 个 chunk",
                flush=True,
            )

            for index, text in enumerate(chunks):
                documents.append(
                    Document(
                        page_content=text,
                        metadata=_chunk_metadata(entry, parsed, index, allowed_roles),
                    )
                )

            document_summaries.append(
                {
                    "document_id": entry["document_id"],
                    "title": entry.get("title", ""),
                    "path": relative,
                    "parser_mode": parser_mode,
                    "parser_mode_actual": parsed.parser_mode_actual,
                    "is_machine_extracted": parsed.is_machine_extracted,
                    "provenance": parsed.provenance,
                    "allowed_roles": allowed_roles,
                    "chunk_count": len(chunks),
                }
            )
        except Exception as exc:  # noqa: BLE001 —— 单份失败不阻断其余文档（K7）
            print(f"[解析]   -> 失败 {type(exc).__name__}: {str(exc)[:120]}", flush=True)
            failures.append(
                {
                    "path": relative,
                    "document_id": entry.get("document_id", ""),
                    "parser_mode": parser_mode,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:600],
                }
            )

    if not documents:
        raise RuntimeError(
            "没有生成任何 chunk，索引未构建。失败明细："
            + json.dumps(failures, ensure_ascii=False)
        )

    embeddings, embedding_model = _build_embeddings()
    print(f"[向量化] {len(documents)} 个 chunk 写入 Chroma（{embedding_model}）...", flush=True)
    _reset_collection()
    Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(VECTOR_STORE_DIR),
    )

    index_manifest = {
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "embedding_model": embedding_model,
        "collection_name": COLLECTION_NAME,
        "vector_store_path": str(VECTOR_STORE_DIR),
        "chunking": {
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "keep_separator": KEEP_SEPARATOR,
            "separators": CHINESE_SEPARATORS,
            "note": "chunk_size / chunk_overlap 是本计划的工程估计，不是课件规定值",
        },
        "document_count": len(document_summaries),
        "chunk_count": len(documents),
        "documents": document_summaries,
        "failures": failures,
    }
    INDEX_MANIFEST_PATH.write_text(
        json.dumps(index_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "document_count": len(document_summaries),
        "chunk_count": len(documents),
        "vector_store_path": str(VECTOR_STORE_DIR),
        "embedding_model": embedding_model,
        # 以下是调用方打印用的附加信息（不影响上面四个契约键）
        "documents": document_summaries,
        "failures": failures,
    }


# --------------------------------------------------------------------------
# K8 检索：search_company_knowledge（P4 —— 安全边界）
#
# 权限闸门在**检索阶段**执行：Chroma 的 where 是「必须匹配」语义，
# 用 {"allow_<role>": True} 过滤后，**元数据缺该键的 chunk 不会进入候选集**
# （fail-closed）。绝不能「先无过滤召回、再在 Python 里剔除」—— 课件 D5§9.2：
# 无权正文一旦进入模型上下文，边界就已经被突破。
# --------------------------------------------------------------------------

SEARCH_K = 5

# 向量库句柄缓存：Embedding 模型加载较慢，一次会话内复用。
# 注意这是**只读索引**（不是 B3 所说的业务 JSON），重建索引后需新进程才生效。
_vector_store_cache: Chroma | None = None


def _open_vector_store() -> Chroma:
    """打开只读的 Chroma 索引（懒加载并复用）。"""
    global _vector_store_cache
    if _vector_store_cache is None:
        # 临时目录由入口脚本适配；库侧只检查，不可用就给可操作的错误
        _require_usable_tempdir()
        embeddings, _model_name = _build_embeddings()
        _vector_store_cache = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(VECTOR_STORE_DIR),
        )
    return _vector_store_cache


def _evidence_of(hit: Document, score: float, rank: int) -> dict[str, Any]:
    """把一条检索命中整理成结构化证据（来源由程序生成，不让模型编）。"""
    metadata = hit.metadata or {}
    return {
        "rank": rank,
        "document_id": metadata.get("document_id", ""),
        "title": metadata.get("title", ""),
        "path": metadata.get("path", ""),
        "chunk_id": metadata.get("chunk_id", ""),
        "access_scope": metadata.get("access_scope", ""),
        "score": round(float(score), 4),
        "content": hit.page_content,
    }


@tool("search_company_knowledge")
def search_knowledge(query: str, runtime: ToolRuntime) -> str:
    """检索公司知识库，返回当前登录角色有权访问的文档证据。

    只返回与问题相关的资料片段与来源；如果知识库里没有可依据的资料，
    会明确返回「无依据」，不要用常识编造公司制度。
    """
    context = getattr(runtime, "context", None)
    role = str(getattr(context, "role", "") or "").strip()

    # 身份只来自 Runtime Context（B2）；角色不在已知集合内一律拒绝
    if role not in FILTERABLE_ROLES:
        return json.dumps(
            {
                "ok": False,
                "error": "permission_denied",
                "message": f"当前角色 {role!r} 不能检索公司知识库",
            },
            ensure_ascii=False,
        )

    query = (query or "").strip()
    if not query:
        return json.dumps(
            {"ok": False, "error": "invalid_argument", "message": "query 不能为空"},
            ensure_ascii=False,
        )

    # K2 + K8：按角色在**检索阶段**过滤；缺该键的 chunk 不会进入候选集
    hits = _open_vector_store().similarity_search_with_score(
        query, k=SEARCH_K, filter={f"allow_{role}": True}
    )
    if not hits:
        return json.dumps(
            {
                "ok": False,
                "error": "no_evidence",
                "message": "当前知识库中没有可依据的资料，无法确认该问题",
            },
            ensure_ascii=False,
        )

    evidence = [
        _evidence_of(hit, score, rank)
        for rank, (hit, score) in enumerate(hits, start=1)
    ]
    return json.dumps(
        {
            "ok": True,
            "data": {
                "role": role,
                "query": query,
                "count": len(evidence),
                "evidence": evidence,
            },
        },
        ensure_ascii=False,
    )
