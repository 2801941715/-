package com.damai.assistant;

import org.json.JSONException;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** 单条运行日志（对应 Python 侧 TicketRunLogEntry）。 */
public class LogEntry {

    public final long timestamp;
    public final String level;
    public final String message;
    public final String phase;
    public final JSONObject context;

    public LogEntry(long timestamp, String level, String message, String phase, JSONObject context) {
        this.timestamp = timestamp;
        this.level = level;
        this.message = message;
        this.phase = phase;
        this.context = context == null ? new JSONObject() : context;
    }

    public JSONObject toJson() throws JSONException {
        JSONObject o = new JSONObject();
        o.put("timestamp", timestamp);
        o.put("time", formatTime(timestamp));
        o.put("level", level);
        o.put("phase", phase);
        o.put("message", message);
        o.put("context", context);
        return o;
    }

    public String toDisplayLine() {
        return "[" + formatTime(timestamp) + "] " + LogLevel.prefix(level) + " " + message;
    }

    public static String formatTime(long epochMillis) {
        SimpleDateFormat f = new SimpleDateFormat("HH:mm:ss", Locale.US);
        return f.format(new Date(epochMillis));
    }
}
