// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

//! 壳的入口：建窗口、装插件、注册转发口。
//!
//! **这一层不写业务**。判断句：换掉界面之后仍然该存在的逻辑，不属于壳。
//! 前端与 Python 内核之间只有**一个转发口**（`kernel_call(method, payload)` 那一形），
//! 壳负责把帧转过去再转回来，**不解构领域字段**——一旦这里开始认 `title` / `notedata`
//! 这类字眼，业务就漏进壳了。契约的形状在 Python 侧声明、生成给 TS。
//!
//! 与边车之间的协议是 stdio 上的长度头分帧 JSON（与 LSP 同款），与
//! `py_src/app/sidecar.py` 那一侧严格对称：**长度按字节算**，故中文不会算错。
//!
//! 现状：
//!
//! - **请求 → 回答已接线**（本文件）；
//! - **通知（内核 → 前端）尚未接线**——事件总线那条扇出还没接到这儿，
//!   故此处不假装它存在；
//! - 边车的解释器与模块路径目前靠 `CAIRN_PYTHON` / `CAIRN_PYTHONPATH` 两个环境变量给，
//!   **打包后的落法待定**。

use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;

use serde_json::{Value, json};
use tauri::Manager;
use tauri::State;

/// 库根的环境变量名：不给就用工作目录下的 `vault/`（开发期的默认位置）。
const VAULT_ENV: &str = "CAIRN_VAULT";

/// 边车解释器的环境变量名。
const PYTHON_ENV: &str = "CAIRN_PYTHON";

/// 边车模块搜索路径的环境变量名（开发期指向 `py_src/`）。
const PYTHONPATH_ENV: &str = "CAIRN_PYTHONPATH";

/// 一条跑着的边车：子进程加它的两根管道。
struct Sidecar {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

impl Sidecar {
    /// 起一个边车：`python -m app.sidecar <库根>`。
    ///
    /// 边车的日志走它的 stderr，这里选择**继承**——壳的控制台直接看得见，
    /// 而 stdout 那条流留给帧、一个字都不许掺。
    fn start(vault: &str) -> Result<Self, String> {
        let python = std::env::var(PYTHON_ENV).unwrap_or_else(|_| "python".to_string());
        let mut command = Command::new(python);
        command.args(["-m", "app.sidecar", vault]);
        if let Ok(path) = std::env::var(PYTHONPATH_ENV) {
            command.env("PYTHONPATH", path);
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| format!("起边车失败: {error}"))?;
        let stdin = child.stdin.take().ok_or("拿不到边车的 stdin")?;
        let stdout = child.stdout.take().ok_or("拿不到边车的 stdout")?;
        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            next_id: 1,
        })
    }

    /// 发一条请求、等一条回答。**一问一答**：调用方持锁串行化。
    fn call(&mut self, method: &str, params: Value) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id += 1;
        self.write_frame(&json!({ "id": id, "method": method, "params": params }))?;
        let reply = self.read_frame()?;
        if reply.get("ok").and_then(Value::as_bool) == Some(true) {
            return Ok(reply.get("result").cloned().unwrap_or(Value::Null));
        }
        let kind = reply
            .pointer("/error/kind")
            .and_then(Value::as_str)
            .unwrap_or("Error");
        let message = reply
            .pointer("/error/message")
            .and_then(Value::as_str)
            .unwrap_or("边车回了失败，但没有说明");
        Err(format!("{kind}: {message}"))
    }

    /// 写一帧：`Content-Length: <字节数>\r\n\r\n<正文>`。
    fn write_frame(&mut self, payload: &Value) -> Result<(), String> {
        let body = serde_json::to_vec(payload).map_err(|error| format!("编帧失败: {error}"))?;
        write!(self.stdin, "Content-Length: {}\r\n\r\n", body.len())
            .map_err(|error| format!("写帧头失败: {error}"))?;
        self.stdin
            .write_all(&body)
            .map_err(|error| format!("写帧正文失败: {error}"))?;
        self.stdin
            .flush()
            .map_err(|error| format!("刷帧失败: {error}"))
    }

    /// 读一帧。头读到空行为止，再按声明的**字节数**精确读正文。
    fn read_frame(&mut self) -> Result<Value, String> {
        let mut length: Option<usize> = None;
        loop {
            let mut line = String::new();
            let read = self
                .stdout
                .read_line(&mut line)
                .map_err(|error| format!("读帧头失败: {error}"))?;
            if read == 0 {
                return Err("边车关了管道".to_string());
            }
            let header = line.trim_end_matches(['\r', '\n']);
            if header.is_empty() {
                break;
            }
            if let Some((name, value)) = header.split_once(':') {
                if name.trim().eq_ignore_ascii_case("content-length") {
                    length = Some(
                        value
                            .trim()
                            .parse()
                            .map_err(|error| format!("帧头的长度不是整数: {error}"))?,
                    );
                }
            }
        }
        let size = length.ok_or("帧头里没有 Content-Length")?;
        let mut body = vec![0u8; size];
        self.stdout
            .read_exact(&mut body)
            .map_err(|error| format!("正文读不满: {error}"))?;
        serde_json::from_slice(&body).map_err(|error| format!("正文不是 JSON: {error}"))
    }
}

impl Drop for Sidecar {
    /// 壳退出时收掉边车：管道一断它自己也会收工，这里再补一刀免得留孤儿进程。
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// 边车的共享状态：一把锁，保证一问一答串行。
struct SidecarState(Mutex<Sidecar>);

/// **转发口**：壳里唯一通向前端的那道门。
///
/// `method` 与 `payload` 原样转给边车，回答原样带回——壳不认识其中的任何领域字段。
#[tauri::command]
fn kernel_call(
    sidecar: State<'_, SidecarState>,
    method: String,
    payload: Option<Value>,
) -> Result<Value, String> {
    let mut sidecar = sidecar
        .0
        .lock()
        .map_err(|_| "边车状态被别的线程弄坏了".to_string())?;
    sidecar.call(&method, payload.unwrap_or(Value::Null))
}

/// 启动桌面外壳。
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let vault = std::env::var(VAULT_ENV).unwrap_or_else(|_| "vault".to_string());
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            let sidecar =
                Sidecar::start(&vault).map_err(|error| std::io::Error::other(error))?;
            app.manage(SidecarState(Mutex::new(sidecar)));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![kernel_call])
        .run(tauri::generate_context!())
        .expect("启动 Tauri 应用失败");
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 真起一个边车、真走一遍帧。
    ///
    /// 这是**两侧协议唯一的交叉验证**：帧的头、长度、正文编码各写了一遍，
    /// 只靠各自的单测证明不了它们对得上。
    ///
    /// 需要边车能被 `python -m app.sidecar` 找到，故把 `PYTHONPATH` 指回仓库的
    /// `py_src/`（测试的工作目录是 `app/src-tauri/`）。
    #[test]
    fn talks_to_a_real_sidecar() {
        std::env::set_var(PYTHONPATH_ENV, "../../py_src");
        let vault = std::env::temp_dir().join("cairn-sidecar-protocol-test");
        let _ = std::fs::remove_dir_all(&vault);
        let path = vault.to_str().expect("临时路径不是 UTF-8");

        let mut sidecar = Sidecar::start(path).expect("起边车失败");
        let stored = sidecar
            .call("store", json!({ "data": "aGVsbG8=", "kind": "notedata" }))
            .expect("store 失败");
        assert!(stored.get("uuid").is_some());

        let listed = sidecar.call("blocks", json!({})).expect("blocks 失败");
        assert_eq!(listed["blocks"].as_array().map(Vec::len), Some(1));

        let loaded = sidecar.call("load", json!({ "uuid": stored["uuid"] })).expect("load 失败");
        assert_eq!(loaded["data"], json!("aGVsbG8="));

        let _ = std::fs::remove_dir_all(&vault);
    }
}
