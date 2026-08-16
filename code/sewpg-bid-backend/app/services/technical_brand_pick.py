from __future__ import annotations

"""按本项目投的品牌，从部件认证候选里选出该插哪一份。

部件认证在素材库里按部件分目录，同一个部件常有多家厂商的证书（主轴承 SKF 和 LYC 各一份，
变流器阳光和禾望各一份）。选哪份取决于本项目对业主承诺投什么品牌——那写在项目短名单下的
大部件品牌 xlsx 上，左半边是业主给的空表（优秀/良好两档允许范围），右半边是我方按机型
逐列填好的选定品牌。业务方口径：投什么品牌就放什么品牌的证，投一个放一个投多个放多个，
库里没有的空着提示缺少交人工。

这一步交给 AI 而不是写规则，因为那张表规则读不了：合并单元格导致同一列在不同行错位、
第 17 行之后嵌了结构不同的第二张表、部件是三级嵌套（「主轴承」挂在「主轴（含联轴节）」
下面）、品牌名写法在两处对不上（品牌表「德力佳」素材名「德利佳」、品牌表「中车电机（株洲）」
证书上是生产厂「江苏中车电机有限公司」）。任何一条正则化的匹配规则都是对着这批数据调出来的，
换项目换供应商就不够用。

AI 的自由度被框死在「从给定候选里选 0 或 1 份 + 给理由」：工具全关，它搜不了库；候选由
脚本列目录给出；选不出来必须明说 not_available，不许编。结果落项目状态，人能改能重跑。
"""

import io
import json
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.minio_client import minio_client
from app.services.opencode_client import OpencodeClient

# 品牌清单固定放在项目定制的短名单目录下（业务方已确认这是约定位置），
# 同目录还有一份内部采购短名单，按文件名里的「大部件品牌」区分。
BRAND_LIST_FOLDER_KEYWORD = "短名单"
BRAND_LIST_NAME_KEYWORD = "大部件品牌"

PICK_STATUS_OK = "ok"
PICK_STATUS_NOT_AVAILABLE = "not_available"


class BrandPickError(RuntimeError):
    """品牌选取失败：找不到品牌清单、读不出内容、或 AI 未给出可用结果。"""


def _norm(value: Any) -> str:
    """比对用归一化：与 technical_gap_ai_fill._embed_norm 同口径，两边都只做去噪不做猜测。"""
    return re.sub(r"[\s（）()、/\\:：；;，,。\-_—×*\[\]【】]+", "", str(value or "").strip().lower())


def find_brand_list_material(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """项目素材范围里的大部件品牌清单；没有返回 None（业主不要求部件认证时可以没有）。"""
    for material in candidates:
        name = str(material.get("name") or "")
        if not name.lower().endswith((".xlsx", ".xls", ".xlsm")):
            continue
        if BRAND_LIST_NAME_KEYWORD not in name:
            continue
        if BRAND_LIST_FOLDER_KEYWORD not in str(material.get("folderPath") or ""):
            continue
        return material
    return None


def dump_brand_list_text(material: dict[str, Any], download_content) -> str:
    """品牌清单 xlsx → 纯文本，逐行逐格照抄。

    不做任何结构化预处理：合并单元格造成的列错位、嵌在后面的第二张表，都原样交给 AI，
    脚本先猜一遍反而会把错位固化下来。
    """
    import openpyxl

    payload = download_content(str(material.get("id") or ""))
    content = minio_client.client.get_object(str(payload["bucket"]), str(payload["key"])).read()
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    lines: list[str] = []
    for sheet in workbook.worksheets:
        lines.append(f"### sheet: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if cell is None else str(cell).strip().replace("\n", " / ") for cell in row]
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def build_prompt(turbine_model: str, brand_list_text: str, components: dict[str, list[str]]) -> str:
    """一次问清所有部件，答案要能被人对着文件名和品牌清单逐条核对。"""
    blocks = []
    for component, names in components.items():
        listed = "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1))
        blocks.append(f"### {component}\n{listed}")
    candidate_text = "\n".join(blocks)
    return f"""你在为一份投标文件挑选部件型式认证证书。只做选择，不要做别的事。

本项目投标机型：{turbine_model or "（未指定）"}

## 本项目的大部件品牌清单（原样摘录，左半是业主允许的品牌范围，右半是按机型分列的我方选定品牌）

{brand_list_text}

## 素材库里各部件已有的认证候选（你只能从这里面选）

{candidate_text}

## 要求

1. 对每个部件：先在品牌清单里找到**本项目投标机型那一列**写的品牌，再在候选里找厂家对得上的那份。
2. 只能从上面给出的候选里原样照抄文件名，不许编造、不许改写、不许选未列出的东西。
3. **品牌清单里这个部件写了几个品牌，就选几份证书**（业务规则：投一个放一个、投多个放多个）。
   materialNames 是数组，按品牌清单里的先后顺序放。
4. 候选里没有厂家对得上的，status 填 "{PICK_STATUS_NOT_AVAILABLE}"，materialNames 留空数组，
   reason 写清楚品牌清单要的是什么、候选里只有什么。**不要为了凑数硬选一份。**
   部分品牌有、部分没有时，有的照选，reason 里写明少了哪个。
5. reason 必须让人能对着文件名和品牌清单核对，一句话说明你依据的是哪一处。厂家名两边写法
   常常不一致（简称与全称、个别错别字、证书上「制造商」与「生产厂」是两个字段），
   说清楚你比对的是哪个词。
6. 只输出 JSON，前后不要有任何解释文字。

## 输出格式

{{"picks": [{{"component": "部件名", "brand": "本项目投的品牌（多个用顿号分隔）", "materialNames": ["选中的候选文件名"], "reason": "判断依据", "status": "{PICK_STATUS_OK}"}}]}}
"""


def normalize_material_names(item: dict[str, Any]) -> list[str]:
    """取出一条 pick 里的素材名列表，兼容单值写法。

    AI 偶尔会退回旧的 materialName 单值（prompt 改过、模型没跟上），页面上人工改写也
    可能只给一个，这里统一收成数组，下游只认数组。
    """
    raw = item.get("materialNames")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []
    names = [str(name or "").strip() for name in raw]
    single = str(item.get("materialName") or "").strip()
    if single and single not in names:
        names.append(single)
    return [name for name in names if name]


def _coerce_picks(parsed: dict[str, Any], components: dict[str, list[str]]) -> list[dict[str, Any]]:
    """AI 输出 → 规范化 picks，并把编造的文件名挡在门外。

    只信「原样出现在候选里」的文件名：模型偶尔会把两份候选拼在一起或补全省略号，
    放过去就等于往标书里插了一份不存在的证书。品牌清单一格写了几个品牌就该选几份，
    所以这里保留多个，但每一个都要过同一道校验。
    """
    raw = parsed.get("picks")
    if not isinstance(raw, list):
        raise BrandPickError("AI 未返回 picks 列表。")
    allowed = {component: {_norm(name): name for name in names} for component, names in components.items()}
    picks: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        component = str(item.get("component") or "").strip()
        names = allowed.get(component) or allowed.get(next((c for c in allowed if _norm(c) == _norm(component)), ""))
        if names is None:
            continue
        picked: list[str] = []
        for candidate in normalize_material_names(item):
            resolved = names.get(_norm(candidate))
            if resolved and resolved not in picked:
                picked.append(resolved)
        status = str(item.get("status") or "").strip() or PICK_STATUS_OK
        reason = str(item.get("reason") or "").strip()
        if not picked:
            status = PICK_STATUS_NOT_AVAILABLE
            if not reason:
                reason = "AI 未从候选里选出可用的证书。"
        picks.append(
            {
                "component": component,
                "brand": str(item.get("brand") or "").strip(),
                "materialNames": picked,
                "reason": reason,
                "status": PICK_STATUS_OK if picked and status == PICK_STATUS_OK else PICK_STATUS_NOT_AVAILABLE,
                "source": "ai",
            }
        )
    if not picks:
        raise BrandPickError("AI 未给出任何可用的部件选择。")
    return picks


def request_brand_picks(
    turbine_model: str,
    brand_list_text: str,
    components: dict[str, list[str]],
    *,
    client: OpencodeClient | None = None,
) -> list[dict[str, Any]]:
    """一次问答拿到所有部件的选择；工具全关，AI 只能依据 prompt 里给的东西作答。"""
    if not components:
        return []
    client = client or OpencodeClient()
    response = client.send_text_prompt(
        "技术标·部件认证品牌选取",
        build_prompt(turbine_model, brand_list_text, components),
        tools={"read": False, "write": False, "edit": False, "bash": False, "glob": False, "grep": False},
    )
    reply = str(response.get("reply") or "").strip()
    if not reply:
        raise BrandPickError("AI 未返回内容。")
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", reply)
    cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise BrandPickError(f"AI 返回内容里没有可解析的 JSON：{reply[:200]}") from None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise BrandPickError(f"AI 返回的 JSON 无法解析：{exc}") from exc
    if not isinstance(parsed, dict):
        raise BrandPickError("AI 返回的不是 JSON 对象。")
    return _coerce_picks(parsed, components)


def picks_by_component(picks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """部件名归一 → pick，供备料时按部件查。人工改过的优先于 AI 的。"""
    index: dict[str, dict[str, Any]] = {}
    for pick in picks:
        key = _norm(pick.get("component"))
        if not key:
            continue
        if key in index and index[key].get("source") == "manual":
            continue
        index[key] = pick
    return index
