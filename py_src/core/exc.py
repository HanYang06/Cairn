# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""内核异常声明.

异常层只做一件事:把"哪一层在什么情况下退出"写成一个类型,调用方按类型分流,
日志按类型定级.此处只声明当前确有抛出点的异常;尚无抛出点的层不得预先占位.
"""

from __future__ import annotations


class CairnError(Exception):
    """内核异常基类:跨层兜底只认这一个."""


class InvalidIdError(CairnError, ValueError):
    """标识符格式非法:唯一标识凭证或内容摘要凭证不满足各自的形态约束."""


class StorageError(CairnError):
    """存储侧异常的基类:调用方按它兜住整层,再按子类分流."""


class AttrTypeError(StorageError, ValueError):
    """块属性或内容编不进载荷:值不是 CBOR 认得的写法(如 `Path`,自定义对象)."""


class SlotFormatError(StorageError):
    """槽的字节不合规:槽头读不满,内容长度越出格长,或校验和不符."""


class SlotError(StorageError):
    """槽号或格长非法:格号越界,格号写歪,或载体尾部不是整格."""


class SlotTooLargeError(SlotError):
    """一格装不下:内容的字节数超过"格长减槽头".**当场报错,不得静默截断.**"""


class SlotSizeError(StorageError):
    """格长配置不成立:两档一个都没写(等于零),或写成负数.

    格长是**格式事实**:它写进载体文件头,改一次配置即改变后续载体的布局.故配置写空
    不是"取个默认值"了事,而是当场报错——否则每一次定位都会算在错的基础上.
    """


class HubNotFoundError(StorageError):
    """hub 目录或载体不存在.**读路径不建东西**:不在就报错,不悄悄建一个空的顶上."""


class HubShapeError(StorageError):
    """hub 的形状或内容不合规:目录缺 `packs/`,或 `packs/` 里混着不是载体的文件."""


class IndexNotFoundError(StorageError):
    """索引库文件不存在.**读路径不建库**:不在就报错,只有显式建立才创建文件."""


class IndexSchemaError(StorageError):
    """这个文件不是本程序的索引库(缺 `meta`):**不把它人的 sqlite 当本库用**.

    索引库是可整份重建的投影,但"重建"要显式下令;认不出形状时先拒绝,不做推断.
    """


class ObjectNotFoundError(StorageError):
    """对象不在存储里:索引没有这一行,或行指向的字节已经读不出来."""


class ConfigError(CairnError, ValueError):
    """配置侧异常的基类:调用方按它兜住整层,再按子类分流."""


class ConfigTypeError(ConfigError):
    """类型与值对不上:声明的类型不是允许的写法,或默认值 / 写进来的值与该键的类型不符."""


class ConfigDuplicateError(ConfigError):
    """重复声明:这个键已经有值(文件里,或本会话已声明过),代码不许再给它赋值.

    **写入方向只有一个:代码 → 文件**.改值只能从配置文件改回来,除非显式 `force=True`.
    """


class ConfigKeyError(ConfigError):
    """配置项没有值可读:键不在值文件里,而声明处也没有默认值."""


class ConfigFileError(ConfigError):
    """值文件读不成配置:不是合法 JSON,或根不是对象."""


class ConfigReferenceError(ConfigError):
    """文件引用不成立:引用名指向仓根之外,或被引用的文件不存在."""


class CallError(CairnError, ValueError):
    """命令面异常:方法名不认识,或参数缺了 / 多了 / 类型不对."""


class UnknownMethodError(CallError):
    """方法名不在命令面那张表里——错的是调用方,不是内核."""


class InvalidParamsError(CallError):
    """参数不合规:缺了必需的,不是要的类型,或值本身解不出来."""


__all__ = [
    "AttrTypeError",
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
    "SlotError",
    "SlotFormatError",
    "SlotSizeError",
    "SlotTooLargeError",
    "StorageError",
    "UnknownMethodError",
]
