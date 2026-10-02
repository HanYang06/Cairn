# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""全局夹具。

**原本这里有一份"把表声明文件挡在仓外"的补丁**（旧版每次装配内核都会把
`config/tables.yaml` 由代码写出来，于是跑一次测试就改一次入库产物）。

该机制已取消：库的结构只有一条来路——**用了 ID 就在库里有一张身份表**，
不由文件声明，故系统不再读写那份文件。补丁随之删除，而不是留着空跑。
"""
