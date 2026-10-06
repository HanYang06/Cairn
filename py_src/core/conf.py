# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置面:内核不再自带引擎,声明与取值都走 OnConf(`onconf`).

本模块只做**两件事**,配置语义一律由 OnConf 承担:

1. **定配置根**:`CAIRN_CONFIG` 指的目录,不给就用仓根下的 `config/`;
2. **把引擎指到那里**,然后把 `conf` 原样交出去——`from core.conf import conf` 之后
   任何地方都能用,与换引擎之前的调用形逐字一致:

   ```python
   conf("core.log.level", "WARNING", type=str, doc="内核日志级别")  # 声明
   level = conf("core.log.level")                                  # 取值
   ```

**为什么要在这一层转一手**:OnConf 的引擎是**单例**且"起来之后不能就地改配置"
(`AutoConf` 的 v1 限制),而配置根由环境旋钮定——故必须在**第一次 `conf()` 之前**
把 `home` 定下来.这一层就是那个时机:它一被导入就把引擎指好,消除"谁先调用谁定根"的顺序
依赖(内核的声明模块正是在导入期调 `conf()` 的).

**与旧引擎的语义差异(按事实记,不按旧口径)**:

- **重复声明不再报错**:同一进程里对同一键再声明一次,OnConf 只把新默认值记进词表,
  值文件里已有的值**不动**(`op=skip`,理由"尊重文件"),不抛异常.旧引擎那种"重复声明
  在启动时炸"的看门能力**随引擎一起没了**——将来要它,得另找地方做(如 AST 门禁);
- **读期不做类型转换**:`type=` 只在声明期校验默认值;值文件里的值原样读回,
  人手改错类型不再当场报错,由取用处的 `int(...)` / `str(...)` 自己收口;
- **`conf(k, v)` 返回当前生效值**(文件里已有的优先),不再是"那一处写下的默认值";
- **落盘默认即时**:OnConf 的 `flush_window` 默认为 `0`(每次调用即提交),
  旧引擎的"攒到退出"不再成立;进程退出时 OnConf 自己 `sync()` 兜底.

日志去向:`log=` 是 OnConf 的引擎参数,它**每次读都留一行**;默认的 `stderr` 会淹掉命令行
与测试输出,故这里改去 `<root>/logs/config.log`——该日志口自带"建父目录"的行为,
第一次写就把 `logs/` 建出来,不留"目录不在就退回 stderr"那种看运气的分支.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, overload

from onconf import AutoConf
from onconf import conf as _onconf

__all__ = ["CONFIG_DIRNAME", "ROOT_ENV", "conf", "sync"]

#: 配置根:值文件(`settings.json`)与词表(`schema/settings.json`)都落在这里
CONFIG_DIRNAME = "config"

#: 环境旋钮:只给测试与部署重定向,**不进配置**(它不是配置项,是找到配置的办法)
ROOT_ENV = "CAIRN_CONFIG"

#: OnConf 自己的日志去向(相对配置根);它是运行期簿记,不是配置数据
LOG_DIRNAME = "logs"
LOG_FILENAME = "config.log"

_LOGGER = logging.getLogger("cairn.conf")


def config_root() -> Path:
    """配置根目录:环境旋钮 `CAIRN_CONFIG` 指的,不给就用仓根下的 `config/`."""
    from_env = os.environ.get(ROOT_ENV)
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[2] / CONFIG_DIRNAME


def _log_destination(root: Path) -> str:
    """OnConf 的日志落点:配置根下的 `logs/config.log`.

    不预先探测目录**是否存在**:那个日志口自己会建父目录
    (`onconf._audit._append_file` 里 `mkdir(parents=True)`),而"先探测再退回 stderr"
    会让第一次运行把记录倒进 stderr——正是这里要避开的噪声.
    """
    return str(root / LOG_DIRNAME / LOG_FILENAME)


@overload
def conf[T](
    key: str,
    value: T,
    *,
    doc: str | None = ...,
    type: type | None = ...,
    force: bool = ...,
    **engine: object,
) -> T: ...


@overload
def conf(
    key: str,
    *,
    doc: str | None = ...,
    type: type | None = ...,
) -> Any: ...


def conf(
    key: str,
    *args: Any,
    doc: str | None = None,
    type: type | None = None,
    force: bool = False,
    **engine: object,
) -> Any:
    """读 / 写 / 登记一个配置项:OnConf 那个 `conf` 的原样转发.

    参数与语义见 OnConf 的文档(`onconf.conf`);本层只保证"调用之前引擎已经指向
    :func:`config_root`".**不自行增加参数**——多出来的参数会撞上 OnConf 的引擎参数
    校验(`UnknownEngineParamError`),转发的形参表因此与它逐字对齐.

    **为什么不把 `value` 写成一个带哨兵默认值的形参**:OnConf 判"读还是写"靠的是
    `value` 位拿到的**是不是它自己那个 `MISSING` 哨兵**(`onconf._core.MISSING`),而
    那个哨兵不在它的公开面上——转抄一个自己的哨兵,OnConf 只当它是"一个普通的值",
    于是 `conf("k")` 会变成"把哨兵写进去".故这里**按位置透传**:给没给第二个参数,
    就是那一条判据本身,不依赖上游任何私有符号.

    静态类型按声明处绑定(与 OnConf 的公开签名一致):`conf(k, v)` 返回 `v` 的类型,
    `conf(k)` 无注解即 `Any`.声明处由此能拿住默认值的类型,取值处由调用方自己收口
    (`int(conf(k))` 那种写法把"这里做了转换"摆在明处).
    """
    root = config_root()
    if Path(AutoConf().home) != root.resolve():
        _LOGGER.debug("配置根与引擎已绑定的那一处不一致: %s", root)
    return _onconf(key, *args, doc=doc, type=type, force=force, **engine)


def sync() -> None:
    """把攒着的声明交出去(OnConf 的完整提交点),供工具与测试要"文件此刻是对的"时用.

    日常写法里不出现它:OnConf 默认**每次调用即提交**,不像旧引擎那样攒到进程退出.
    取引擎只能走 `AutoConf()`——`onconf.conf` 是一个**函数**,没有 `.sync`,故旧写法
    `conf.sync()` 在换引擎之后不再成立.
    """
    AutoConf().sync()


# 导入即把引擎指到仓里的 `config/`:内核的声明模块在导入期就会调 `conf()`,
# 故这一步必须发生在它们之前——写在本模块里,就是这个保证.
AutoConf(home=config_root(), log=_log_destination(config_root()))
