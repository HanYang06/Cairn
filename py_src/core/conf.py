# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""配置面的**装配**:定配置根,把引擎指过去.调用形与语义一律是 OnConf 自己的.

本模块**不转发 `conf`**:OnConf 的 `conf` 就是模块级函数,声明点与取用点直接
`from onconf import conf`——中间再放一个同名函数,只是多一层要读,要对的代码.

这里只剩必须在**第一次 `conf()` 之前**发生的那件事:把引擎装配好.OnConf 的引导层参数
(`home` / `log_console` 这类)"起来之后不能就地改",而内核的声明发生在**导入期**,
故 `core/__init__.py` 先导入本模块,再导入声明模块:导入 `core` 即完成装配.

两处装配决定:

- **配置根**:`CAIRN_CONFIG` 指的目录,不给就用仓根下的 `config/`.这是本仓的部署口径
  (引擎自己的缺省是 `ONCONF_HOME` 或 `./conf`,与 `config/` 的位置不同);
- **控制台出口关掉**:引擎的日志有两个出口——文件那个没有开关(缺省落 `<root>/audit.log`),
  控制台那个由 `log_console` 开关.内核是被命令行与测试嵌入的一方,一次导入要读十几条键,
  照缺省走会把 `stderr` 淹掉,故用它的开关关掉.`audit.log` 照旧留全量记录.
"""

from __future__ import annotations

import os
from pathlib import Path

from onconf import AutoConf

__all__ = ["CONFIG_DIRNAME", "ROOT_ENV", "config_root"]

#: 配置根:值文件(`settings.json`)与词表(`schema/settings.json`)都落在这里
CONFIG_DIRNAME = "config"

#: 环境旋钮:只给测试与部署重定向,**不进配置**(它不是配置项,是找到配置的办法)
ROOT_ENV = "CAIRN_CONFIG"


def config_root() -> Path:
    """配置根目录:环境旋钮 `CAIRN_CONFIG` 指的,不给就用仓根下的 `config/`."""
    from_env = os.environ.get(ROOT_ENV)
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[2] / CONFIG_DIRNAME


# 导入即装配:内核的声明模块在导入期就调 `conf()`,故这一步必须发生在它们之前.
# `home=` 这里**内联**而不调 `config_root()`:OnConf 2.1 的引导层求值只认白名单节点,
# 被调函数的 docstring 会解析成 `ast.Expr` 而遭拒;内联后无需摘取任何函数.
AutoConf(
    home=str(os.environ.get(ROOT_ENV) or (Path(__file__).resolve().parents[2] / CONFIG_DIRNAME)),
    log_console=False,
)
