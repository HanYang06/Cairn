# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核异常声明。

异常层只做一件事：把"哪一层在什么情况下退出"写成一个类型，调用方按类型分流、
日志按类型定级。此处只声明当前确有抛出点的异常；尚无抛出点的层不得预先占位。
"""

from __future__ import annotations


class CairnError(Exception):
    """内核异常基类：跨层兜底只认这一个。"""


class InvalidIdError(CairnError, ValueError):
    """标识符格式非法：唯一标识凭证或内容摘要凭证不满足各自的形态约束。"""


class AttrTypeError(CairnError, ValueError):
    """属性声明非法：缺省值给重了或没给，或类型不在词表里。

    判据与配置共用（`core.conf.types`），异常分开只为报错时说得准是哪一侧。
    """


class BlockShapeError(CairnError, ValueError):
    """块形状立不起来：载荷声明非法，或这个类型的 `__init__` 没法零参探针。

    参见 `core/storage/format/block.py`：形状是**在 `__init__` 里声明、由零参探针现算**的，
    故"探不动"与"声明写歪了"都算这一类。
    """


class StorageError(CairnError):
    """存储侧异常的基类：调用方按它兜住整层，再按子类分流。"""


class RecordFormatError(StorageError):
    """载体记录非法：长度自框定不符、校验和不符、截断或 ID 段不可解析。"""


class SlotError(StorageError):
    """槽区间非法：槽长不合法、末格与记录长度不符，或读越界。"""


class HubNotFoundError(StorageError):
    """hub 目录或载体不存在。**读路径不建东西**：不在就报错，不悄悄建一个空的顶上。"""


class HubShapeError(StorageError):
    """hub 的形状或内容不合规：目录缺 `packs/`，或 `packs/` 里混着不是载体的文件。"""


class TableDeclarationError(StorageError):
    """表声明非法：未知项、非法标识符或类型、重复、缺必填项，或重建档与来源不匹配。"""


class IndexNotFoundError(StorageError):
    """索引库文件不存在。**读路径不建库**：不在就报错，只有显式建立才创建文件。"""


class IndexSchemaError(StorageError):
    """库内结构与声明不一致，且该差异不允许自动处置（默认拒绝，须显式授权重建）。"""


class ObjectNotFoundError(StorageError):
    """对象不在存储里：索引没有这一行，或行指向的字节已经读不出来。"""


class BlockTooLargeError(StorageError):
    """块超出它声明的体积上限。

    上限由类型声明给出（`__max_block_*__`）。**分片尚未接线**，故此刻的处置是拒绝写入，
    而不是切开——切分是存储的活，落地时这条异常会变成"切完再写"。
    """


class BudgetExhaustedError(StorageError):
    """配额用完，且该类型的档位声明为拒绝（`over_budget = deny`）。

    声明为 `notify` 或 `extend` 的类型不会抛它：那两档都自动续一份，前者另发一条通知。
    """


class ConfigError(CairnError, ValueError):
    """配置侧异常的基类：调用方按它兜住整层，再按子类分流。"""


class ConfigTypeError(ConfigError):
    """类型与值对不上：声明的类型不是允许的写法，或默认值 / 写进来的值与该键的类型不符。"""


class ConfigDuplicateError(ConfigError):
    """重复声明：这个键已经有值（文件里、或本会话已声明过），代码不许再给它赋值。

    **写入方向只有一个：代码 → 文件**。改值只能从配置文件改回来，除非显式 `force=True`。
    """


class ConfigKeyError(ConfigError):
    """配置项没有值可读：键不在值文件里，而声明处也没有默认值。"""


class ConfigFileError(ConfigError):
    """值文件读不成配置：不是合法 JSON，或根不是对象。"""


class ConfigReferenceError(ConfigError):
    """文件引用不成立：引用名指向仓根之外，或被引用的文件不存在。"""


class CallError(CairnError, ValueError):
    """命令面异常：方法名不认识，或参数缺了 / 多了 / 类型不对。"""


class UnknownMethodError(CallError):
    """方法名不在命令面那张表里——错的是调用方，不是内核。"""


class InvalidParamsError(CallError):
    """参数不合规：缺了必需的、不是要的类型，或值本身解不出来。"""


__all__ = [
    "AttrTypeError",
    "BlockShapeError",
    "BlockTooLargeError",
    "BudgetExhaustedError",
    "CairnError",
    "CallError",
    "ConfigDuplicateError",
    "ConfigError",
    "ConfigFileError",
    "ConfigKeyError",
    "ConfigReferenceError",
    "ConfigTypeError",
    "HubNotFoundError",
    "HubShapeError",
    "IndexNotFoundError",
    "IndexSchemaError",
    "InvalidIdError",
    "InvalidParamsError",
    "ObjectNotFoundError",
    "RecordFormatError",
    "SlotError",
    "StorageError",
    "TableDeclarationError",
    "UnknownMethodError",
]
