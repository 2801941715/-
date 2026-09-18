package com.damai.assistant;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * 抢票运行参数（对应 Python 侧 AppTicketConfig 的字段子集）。
 *
 * 在设备内运行时不再需要 Appium server_url / device_caps，
 * 因为自动化直接由本应用的 AccessibilityService 执行。
 */
public class Config {

    public String keyword = "";
    public String city = "";
    public String date = "";
    public String price = "";
    /** 票价索引，从 0 开始（按票价升序）；null 表示不按索引选择 */
    public Integer priceIndex = null;
    public final List<String> users = new ArrayList<String>();
    public boolean ifCommitOrder = false;
    public double waitTimeout = 1.5d;
    public double retryDelay = 1.2d;
    public int maxRetries = 6;

    public Config() {
    }

    public static Config defaults() {
        Config c = new Config();
        c.priceIndex = 0;
        c.ifCommitOrder = false;
        return c;
    }

    /** 返回校验错误列表；为空表示配置可用。 */
    public List<String> validate() {
        List<String> errors = new ArrayList<String>();
        if (priceIndex != null && priceIndex < 0) {
            errors.add("price_index: 票价索引不能为负数");
        }
        if (waitTimeout < 0) {
            errors.add("wait_timeout: 等待超时不能为负数");
        }
        if (retryDelay < 0) {
            errors.add("retry_delay: 重试间隔不能为负数");
        }
        if (maxRetries < 1) {
            errors.add("max_retries: 最大重试次数至少为 1");
        }
        return errors;
    }

    public static Config fromJson(JSONObject o) throws JSONException {
        Config c = new Config();
        c.keyword = clean(o.optString("keyword", ""));
        c.city = clean(o.optString("city", ""));
        c.date = clean(o.optString("date", ""));
        c.price = clean(o.optString("price", ""));

        if (o.has("price_index") && !o.isNull("price_index")) {
            Object raw = o.get("price_index");
            if (raw instanceof Number) {
                c.priceIndex = ((Number) raw).intValue();
            } else {
                String text = String.valueOf(raw).trim();
                c.priceIndex = text.isEmpty() ? null : Integer.valueOf(text);
            }
        }

        c.ifCommitOrder = parseBool(o.opt("if_commit_order"), false);
        c.waitTimeout = parseDouble(o.opt("wait_timeout"), 1.5d);
        c.retryDelay = parseDouble(o.opt("retry_delay"), 1.2d);
        c.maxRetries = (int) parseDouble(o.opt("max_retries"), 6d);

        JSONArray arr = o.optJSONArray("users");
        if (arr != null) {
            for (int i = 0; i < arr.length(); i++) {
                String u = clean(String.valueOf(arr.opt(i)));
                if (!u.isEmpty()) {
                    c.users.add(u);
                }
            }
        }
        return c;
    }

    public JSONObject toJson() throws JSONException {
        JSONObject o = new JSONObject();
        o.put("keyword", keyword);
        o.put("city", city);
        o.put("date", date);
        o.put("price", price);
        o.put("price_index", priceIndex == null ? JSONObject.NULL : (Object) priceIndex);
        JSONArray arr = new JSONArray();
        for (String u : users) {
            arr.put(u);
        }
        o.put("users", arr);
        o.put("if_commit_order", ifCommitOrder);
        o.put("wait_timeout", waitTimeout);
        o.put("retry_delay", retryDelay);
        o.put("max_retries", maxRetries);
        return o;
    }

    /** 与 Python 侧 _clean_users 等价的清洗：去空白，空串丢弃。 */
    public static String clean(String s) {
        return s == null ? "" : s.trim();
    }

    /** 解析 users 文本域：按换行/逗号/分号切分。 */
    public static List<String> parseUsers(String content) {
        List<String> out = new ArrayList<String>();
        if (content == null) {
            return out;
        }
        String[] parts = content.split("[\\n,;]");
        for (String p : parts) {
            String t = p.trim();
            if (!t.isEmpty()) {
                out.add(t);
            }
        }
        return out;
    }

    private static boolean parseBool(Object raw, boolean def) {
        if (raw == null) {
            return def;
        }
        if (raw instanceof Boolean) {
            return (Boolean) raw;
        }
        String t = String.valueOf(raw).trim().toLowerCase();
        if (t.isEmpty()) {
            return def;
        }
        return t.equals("true") || t.equals("1") || t.equals("yes") || t.equals("是");
    }

    private static double parseDouble(Object raw, double def) {
        if (raw == null) {
            return def;
        }
        if (raw instanceof Number) {
            return ((Number) raw).doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }
}
