# SPDX-FileCopyrightText: 2026 HanYang06
# SPDX-License-Identifier: Apache-2.0
"""Python 侧的入口层：边车。

它**不是内核**，而是把内核接到一条传输上的那一层：内核保持 Qt-free、传输无关，
语言无关的接线（长度头分帧、序列化、子进程生命周期）落在 `app/`。

当前只有一件东西：:mod:`app.sidecar` —— 壳把 Python 当子进程起，走 stdin/stdout 收发。
"""
