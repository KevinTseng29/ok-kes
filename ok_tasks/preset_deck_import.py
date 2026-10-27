"""Official share code import, decoded offline, with local Chinese OCR text.

Codes are decoded locally by the bundled czn-deckcode SDK (src/czn_deckcode,
MIT); nothing is sent over the network. Unreadable whole codes fail without
replacing presets, and parts of a code the SDK cannot read become warnings.
Local conversion preserves usable fields and attaches per-card notes for fields
that need manual completion.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from opencc import OpenCC

from src.czn_deckcode import DeckCodeError, decode_best_effort


class DeckImportError(ValueError):
    """An import failed without changing the caller's preset."""


def validate_code(code):
    code = str(code).strip()
    if not re.fullmatch(r"v6l[78][A-Za-z0-9_-]{12,4092}", code) or len(code) % 4 == 1:
        raise DeckImportError("请粘贴完整的官方卡组码（以 v6l7 或 v6l8 开头），不要包含角色名或说明文字。")
    return code


_WARNING_FIELDS = {"cardId": "卡牌 ID", "epiphany": "灵光", "divine": "神闪", "talents": "复制标记"}
_WARNING_ACTIONS = {"skipped_card": "已跳过这张卡", "dropped_option": "已忽略这一项",
                    "stopped": "之后的卡牌未能读取"}


def _decode_warning_text(warning):
    where = "卡组码" if warning.card_index is None else f"卡组码第 {warning.card_index + 1} 张卡"
    if warning.card_id:
        where += f"（{warning.card_id}）"
    field = _WARNING_FIELDS.get(warning.field, "卡牌记录")
    return f"{where}的{field}无法识别，{_WARNING_ACTIONS.get(warning.action, '已忽略')}。"


def decode_share_code(code):
    """Decode locally into the preset dict (charId/cards) convert_preset expects;
    parts that could not be read are listed under decodeWarnings."""
    code = validate_code(code)
    try:
        result = decode_best_effort(code)
    except DeckCodeError as exc:
        raise DeckImportError("卡组码无法解析，请检查是否复制完整，原预设已保留。") from exc
    preset = result.deck.to_dict()
    if result.warnings:
        preset["decodeWarnings"] = [_decode_warning_text(w) for w in result.warnings]
    return preset


@lru_cache(maxsize=1)
def load_catalog():
    try:
        path = Path(__file__).parent / "assets" / "preset_card_texts.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeckImportError("卡牌中文映射文件缺失或损坏，请重新安装实验版。") from exc


def _compact(text):
    return re.sub(r"[\W_]+", "", text).lower()


def _keywords(text, min_length=4):
    # Placeholders and unresolved references are never written into OCR config.
    if not isinstance(text, str):
        return []
    fragments = re.split(r"#[^#\n]+#|\^[^\^\n]+\^|\n", text)
    return [part.strip(" ，。、：:；;").lstrip("%+-") for part in fragments
            if len(_compact(part)) >= min_length and not re.search(r"[#^<>]", part)
            and re.search(r"[^\W\d_]", part)]


def convert_preset(preset, language="简体中文", catalog=None):
    """Return (records, warnings, character_name); do not mutate input/config."""
    if language not in ("简体中文", "繁体中文"):
        raise DeckImportError("卡组码导入目前支持简体中文和繁体中文，请先设置本模式的游戏语言。")
    catalog = load_catalog() if catalog is None else catalog
    cards = preset.get("cards")
    if not isinstance(cards, list) or not cards or len(cards) > 100:
        raise DeckImportError("解析结果中的卡牌列表无效，原预设已保留。")
    converter = OpenCC("t2s")
    translate = converter.convert if language == "简体中文" else str
    records, warnings = [], [str(w) for w in preset.get("decodeWarnings") or []]
    for index, entry in enumerate(cards, 1):
        if not isinstance(entry, dict) or type(entry.get("removed", False)) is not bool:
            warnings.append(f"第 {index} 条卡牌记录格式异常，已跳过；其他卡牌继续导入。")
            continue
        if entry.get("removed"):
            continue
        base_id = entry.get("cardId")
        variant = entry.get("variantCardId") or base_id
        notes = []
        if not isinstance(base_id, str) or not base_id.strip():
            if isinstance(variant, str) and variant.strip():
                base_id = variant
                notes.append("基础卡牌 ID 缺失，已按变体保留可识别内容。")
            else:
                warnings.append(f"第 {index} 条卡牌缺少有效 ID，已跳过；其他卡牌继续导入。")
                continue
        if not isinstance(variant, str):
            variant = base_id
            notes.append("变体字段格式异常，请检查卡牌效果。")
        card = catalog["cards"].get(variant)
        base = catalog["cards"].get(base_id)
        named_card = base or card
        if named_card and named_card.get("name"):
            name = translate(named_card["name"]).replace("\u200b", "").strip()
        else:
            name = f"未识别卡牌（{base_id}）"
            notes.append(f"卡牌名称待补充：缺少 {base_id} 的中文映射。")
        if not card:
            notes.append(f"卡牌效果待补充：缺少 {variant} 的效果映射。")
        candidates = _keywords(card.get("text", "") if card else "", min_length=3)
        siblings = [value.get("text", "") for key, value in catalog["cards"].items()
                    if key != variant and (key == base_id or key.startswith(str(base_id) + "_rsp"))]
        def matches(keyword):
            return sum(_compact(keyword) in _compact(text) for text in siblings)
        # One keyword, because the existing preset matcher treats multiple lines as OR.
        candidates.sort(key=lambda text: (matches(text), -len(_compact(text))))
        effect = candidates[0] if candidates else ""
        epiphany_id = entry.get("epiphanyId")
        if epiphany_id:
            # The same game table contains general epiphanies and god effects.
            # Generic epiphanies have their own text rather than an rsp variant.
            template = catalog["divine"].get(epiphany_id) if isinstance(epiphany_id, str) else None
            parts = _keywords(template, min_length=2)
            if parts:
                modifier = max(parts, key=len)
                if variant == base_id:
                    # Name + modifier identifies the chosen general epiphany.
                    # Do not OR it with the common base description, which would
                    # accept all other epiphanies of the same card.
                    effect = modifier
                else:
                    notes.append(f"此卡同时含变体和附加灵光「{translate(modifier)}」；已保留变体效果，请检查并补充附加灵光。")
                if re.search(r"#[^#]+#|\^[^\^]+\^", template):
                    notes.append("普通灵光含动态数值，已导入固定文字，请检查关键字。")
            else:
                notes.append(f"普通灵光待补充（{epiphany_id}），已保留卡牌与可识别效果。")
        if not effect:
            notes.append("卡牌效果待补充；效果留空时仅按卡牌名匹配。")
        elif not epiphany_id and variant != base_id and siblings and matches(effect):
            notes.append("效果可能无法区分所有同名变体，请检查效果关键字。")
        divine_id = entry.get("divineId")
        divine = ""
        if divine_id:
            divine_template = catalog["divine"].get(divine_id) if isinstance(divine_id, str) else None
            divine_parts = _keywords(divine_template, min_length=2)
            if divine_parts:
                divine = max(divine_parts, key=len)
                if re.search(r"#[^#]+#|\^[^\^]+\^", divine_template):
                    notes.append("神闪含动态数值，已导入固定文字，请检查神闪关键字。")
            else:
                notes.append(f"神闪效果待补充（{divine_id}），已保留卡牌与普通效果。")
        record = {"name": name, "effects": [translate(effect)] if effect else [],
                  "divine_text": [translate(divine)] if divine else [], "reject_divine": False}
        if notes:
            record["import_notes"] = list(dict.fromkeys(notes))
            warnings.extend(f"第 {len(records) + 1} 张「{name}」：{note}" for note in record["import_notes"])
        records.append(record)
    if not records:
        raise DeckImportError("卡组中没有可导入的保留卡牌，原预设已保留。")
    character = catalog.get("characters", {}).get(str(preset.get("charId")), "")
    return records, list(dict.fromkeys(warnings)), translate(character)
