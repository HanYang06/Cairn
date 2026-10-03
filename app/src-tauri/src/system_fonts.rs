// SPDX-FileCopyrightText: 2026 HanYang06
// SPDX-License-Identifier: Apache-2.0

//! 系统字体枚举：给前端的"字体替换"机制（`docs/architecture/ui_design/ui-theme.md` §3.8）。
//!
//! 归"窗口与系统"那一摊，**不是业务进壳**——壳只报告本机装了什么字体，
//! 不挑字体、不复制字体文件、不缓存字体文件（那正是 §3.8 的红线）。
//!
//! 返回面刻意收窄：只给名字与样式。底层 `tauri-plugin-system-fonts` 的
//! `SystemFont` 还带 `path` / `id`（字体文件路径），**不往外给**——
//! `ui-boundary.md` §四不许把壳的本机路径与存储细节漏给前端。

use tauri_plugin_system_fonts::{get_system_fonts, SystemFontStyle};

/// 枚举得到的一个系统字体面孔（一个字体族可有多条：不同字形 / 字重）。
///
/// 序列化后字段为 `name` / `postscriptName` / `style` / `weight` / `monospaced`。
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SystemFontInfo {
    /// 字体族名——写进令牌 `--font-sans` / `--font-mono` / `--font-read` 的就是它。
    pub name: String,
    /// PostScript 名：同族多面孔时用来区分（如 `SourceHanSansSC-Regular`）。
    pub postscript_name: String,
    /// 字形：`normal` / `italic` / `oblique`。
    pub style: String,
    /// 字重（OpenType usWeightClass；常见 `400` = Regular、`700` = Bold）。
    pub weight: u16,
    /// 字体自带元数据里的等宽标记，**只是提示、不是判据**：§3.8 第 3 条要求
    /// "等宽靠支撑计算"——中文字体常有拉丁等宽字形但中文并不等宽，
    /// 故这个布尔值不能单独用来判定"适合当等宽字体"。
    pub monospaced: bool,
}

/// 列出本机已安装的字体。
///
/// 调用名：`list_system_fonts`；无入参；返回 `Vec<SystemFontInfo>`。
#[tauri::command]
pub async fn list_system_fonts() -> Vec<SystemFontInfo> {
    get_system_fonts()
        .await
        .into_iter()
        .map(|font| SystemFontInfo {
            name: font.name,
            postscript_name: font.font_name,
            style: match font.style {
                SystemFontStyle::Normal => "normal",
                SystemFontStyle::Italic => "italic",
                SystemFontStyle::Oblique => "oblique",
            }
            .to_owned(),
            weight: font.weight,
            monospaced: font.monospaced,
        })
        .collect()
}
