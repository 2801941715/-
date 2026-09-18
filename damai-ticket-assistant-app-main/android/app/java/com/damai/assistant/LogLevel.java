package com.damai.assistant;

import org.json.JSONException;
import org.json.JSONObject;

/** 日志级别常量（与 Python 侧 LogLevel 对齐）。 */
public final class LogLevel {
    public static final String STEP = "step";
    public static final String INFO = "info";
    public static final String SUCCESS = "success";
    public static final String WARNING = "warning";
    public static final String ERROR = "error";

    private LogLevel() {
    }

    /** 与 Python 侧 _infer_log_level 的映射保持一致的 emoji 前缀。 */
    public static String prefix(String level) {
        if (STEP.equals(level)) return "\uD83E\uDDED";      // 🧭
        if (SUCCESS.equals(level)) return "\u2705";          // ✅
        if (WARNING.equals(level)) return "\u26A0\uFE0F";    // ⚠️
        if (ERROR.equals(level)) return "\u274C";            // ❌
        return "\u2139\uFE0F";                               // ℹ️
    }
}
