package com.damai.assistant;

import android.accessibilityservice.AccessibilityService;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 运行控制与状态中心（进程内单例）。
 *
 * 负责：
 *   - 持有当前配置（Config）
 *   - 启动/停止抢票流程（含重试），在后台线程执行 TicketRunner
 *   - 汇总运行指标与日志，供本地界面与远程调试桥读取
 *
 * 与 Python 侧 DamaiAppTicketRunner.run() + TicketRunReport 的职责对应。
 */
public class RunController {

    private static final String TAG = "DamaiRunController";
    private static final int MAX_LOG_ENTRIES = 2000;

    private static final RunController INSTANCE = new RunController();

    public static RunController get() {
        return INSTANCE;
    }

    public interface Listener {
        void onStateChanged();

        void onLog(LogEntry entry);
    }

    private final List<Listener> listeners = Collections.synchronizedList(new ArrayList<Listener>());
    private final List<LogEntry> logs = Collections.synchronizedList(new ArrayList<LogEntry>());

    private volatile Config config = Config.defaults();
    private volatile boolean running;
    private volatile boolean stopRequested;
    private volatile String phase = Phase.INIT;
    private volatile String failureCode;
    private volatile String failureReason;
    private volatile int attempts;
    private volatile long startTimeMs;
    private volatile long endTimeMs;
    private volatile int lastMaxRetries = 6;
    private Thread worker;

    private RunController() {
    }

    public void addListener(Listener l) {
        if (l != null && !listeners.contains(l)) {
            listeners.add(l);
        }
    }

    public void removeListener(Listener l) {
        listeners.remove(l);
    }

    // ------------------------------------------------------------------
    // 配置
    // ------------------------------------------------------------------

    public Config getConfig() {
        return config;
    }

    public synchronized JSONObject applyConfig(JSONObject payload) {
        if (running) {
            return errorJson("流程运行中，无法修改配置");
        }
        try {
            Config parsed = Config.fromJson(payload);
            List<String> errors = parsed.validate();
            if (!errors.isEmpty()) {
                JSONObject o = errorJson("配置校验失败");
                JSONArray arr = new JSONArray();
                for (String e : errors) {
                    arr.put(e);
                }
                o.put("errors", arr);
                return o;
            }
            config = parsed;
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("config", config.toJson());
            notifyState();
            return o;
        } catch (Exception e) {
            return errorJson("配置解析失败: " + e.getMessage());
        }
    }

    // ------------------------------------------------------------------
    // 生命周期
    // ------------------------------------------------------------------

    public boolean isRunning() {
        return running;
    }

    public String getPhase() {
        return phase;
    }

    /** 请求停止（等价 stop_signal）。 */
    public synchronized JSONObject stop() {
        JSONObject o = new JSONObject();
        try {
            if (!running) {
                o.put("ok", true);
                o.put("state", "idle");
                o.put("message", "当前没有正在运行的流程");
                return o;
            }
            stopRequested = true;
            appendLog(LogLevel.WARNING, "收到停止请求，正在中止流程…", null);
            o.put("ok", true);
            o.put("state", "stopping");
            return o;
        } catch (Exception e) {
            return errorJson(e.getMessage());
        }
    }

    /** 启动抢票流程（异步）。 */
    public synchronized JSONObject start() {
        JSONObject o = new JSONObject();
        try {
            if (running) {
                o.put("ok", false);
                o.put("error", "流程已在运行中");
                return o;
            }
            AccessibilityService service = DamaiAutomationService.getInstance();
            if (service == null) {
                o.put("ok", false);
                o.put("error", "无障碍服务未开启，请先在系统设置中启用本应用的无障碍权限");
                return o;
            }
            List<String> errors = config.validate();
            if (!errors.isEmpty()) {
                o.put("ok", false);
                o.put("error", "配置校验失败: " + joinErrors(errors));
                return o;
            }

            resetRunState();
            running = true;
            stopRequested = false;
            lastMaxRetries = Math.max(1, config.maxRetries);

            final AccessibilityService svc = service;
            worker = new Thread(new Runnable() {
                @Override
                public void run() {
                    executeRun(svc);
                }
            }, "damai-ticket-runner");
            worker.setDaemon(true);
            worker.start();

            o.put("ok", true);
            o.put("state", "running");
            notifyState();
            appendLog(LogLevel.INFO, "抢票流程已启动", null);
            return o;
        } catch (Exception e) {
            return errorJson(e.getMessage());
        }
    }

    /** 实际执行：带重试的流程循环（等价 DamaiAppTicketRunner.run）。 */
    private void executeRun(AccessibilityService service) {
        startTimeMs = System.currentTimeMillis();
        int maxRetries = Math.max(1, lastMaxRetries);
        boolean success = false;

        try {
            for (int attempt = 1; attempt <= maxRetries; attempt++) {
                if (stopRequested) {
                    failureCode = FailureReason.USER_STOP;
                    failureReason = "用户已停止流程";
                    break;
                }
                attempts = attempt;
                appendLog(LogLevel.INFO, "第 " + attempt + " 次尝试（最多 " + maxRetries + " 次）", null);

                TicketRunner runner = new TicketRunner(service, config, new TicketRunner.Logger() {
                    @Override
                    public void log(String level, String message, JSONObject ctx) {
                        appendLog(level, message, ctx);
                    }
                }, new TicketRunner.StopSignal() {
                    @Override
                    public boolean shouldStop() {
                        return stopRequested;
                    }
                });

                try {
                    runner.runOnce();
                    success = true;
                    phase = Phase.COMPLETED;
                    appendLog(LogLevel.SUCCESS, "抢票流程执行完成", null);
                    break;
                } catch (TicketRunner.StoppedException se) {
                    phase = Phase.STOPPED;
                    failureCode = FailureReason.USER_STOP;
                    failureReason = se.getMessage();
                    appendLog(LogLevel.WARNING, failureReason, null);
                    break;
                } catch (TicketRunner.FlowException fe) {
                    phase = Phase.FAILED;
                    failureCode = FailureReason.FLOW_FAILURE;
                    failureReason = fe.getMessage();
                    appendLog(LogLevel.ERROR, failureReason, null);
                } catch (Exception e) {
                    phase = Phase.FAILED;
                    failureCode = FailureReason.UNEXPECTED;
                    failureReason = "未预期的异常: " + e;
                    appendLog(LogLevel.ERROR, failureReason, null);
                    Log.e(TAG, "unexpected", e);
                }

                if (attempt < maxRetries && !stopRequested) {
                    appendLog(LogLevel.INFO, "准备重试…", null);
                    long delay = (long) Math.max(config.retryDelay, 0d) * 1000L;
                    sleep(delay);
                }
            }

            if (!success && failureCode == null) {
                if (stopRequested) {
                    failureCode = FailureReason.USER_STOP;
                    failureReason = "流程被请求停止";
                } else {
                    failureCode = FailureReason.MAX_RETRIES;
                    failureReason = "达到最大重试次数仍未成功";
                }
            }
        } finally {
            endTimeMs = System.currentTimeMillis();
            running = false;
            stopRequested = false;
            try {
                JSONObject stats = new JSONObject();
                stats.put("attempts", attempts);
                stats.put("retries", Math.max(attempts - 1, 0));
                stats.put("duration", (endTimeMs - startTimeMs) / 1000.0d);
                stats.put("success", success);
                if (failureCode != null) {
                    stats.put("failure_code", failureCode);
                }
                appendLog(LogLevel.INFO, "执行统计", stats);
            } catch (Exception ignored) {
                // 忽略统计写入异常
            }
            notifyState();
        }
    }

    private void resetRunState() {
        attempts = 0;
        failureCode = null;
        failureReason = null;
        phase = Phase.INIT;
        startTimeMs = 0L;
        endTimeMs = 0L;
        synchronized (logs) {
            logs.clear();
        }
    }

    // ------------------------------------------------------------------
    // 日志与状态
    // ------------------------------------------------------------------

    private void appendLog(String level, String message, JSONObject context) {
        LogEntry entry = new LogEntry(System.currentTimeMillis(), level, message,
                phase, context);
        synchronized (logs) {
            logs.add(entry);
            if (logs.size() > MAX_LOG_ENTRIES) {
                logs.remove(0);
            }
        }
        synchronized (listeners) {
            for (Listener l : listeners) {
                try {
                    l.onLog(entry);
                } catch (Exception ignored) {
                    // 忽略单个监听器异常
                }
            }
        }
    }

    private void notifyState() {
        synchronized (listeners) {
            for (Listener l : listeners) {
                try {
                    l.onStateChanged();
                } catch (Exception ignored) {
                    // 忽略单个监听器异常
                }
            }
        }
    }

    public List<LogEntry> snapshotLogs() {
        synchronized (logs) {
            return new ArrayList<LogEntry>(logs);
        }
    }

    /** 生成运行报告（等价 TicketRunReport），供本地界面与远程调试读取。 */
    public JSONObject reportJson() throws JSONException {
        JSONObject o = new JSONObject();
        JSONObject metrics = new JSONObject();
        metrics.put("attempts", attempts);
        metrics.put("retries", Math.max(attempts - 1, 0));
        metrics.put("start_time", startTimeMs);
        metrics.put("end_time", endTimeMs);
        metrics.put("duration", Math.max(endTimeMs - startTimeMs, 0L) / 1000.0d);
        metrics.put("success", Phase.COMPLETED.equals(phase));
        metrics.put("final_phase", phase);
        metrics.put("failure_reason", failureReason == null ? JSONObject.NULL : (Object) failureReason);
        metrics.put("failure_code", failureCode == null ? JSONObject.NULL : (Object) failureCode);
        o.put("metrics", metrics);

        JSONArray arr = new JSONArray();
        synchronized (logs) {
            for (LogEntry e : logs) {
                arr.put(e.toJson());
            }
        }
        o.put("logs", arr);
        return o;
    }

    public JSONObject statusJson() throws JSONException {
        JSONObject o = new JSONObject();
        o.put("ok", true);
        o.put("running", running);
        o.put("phase", phase);
        o.put("attempts", attempts);
        o.put("service_connected", DamaiAutomationService.getInstance() != null);
        o.put("failure_code", failureCode == null ? JSONObject.NULL : (Object) failureCode);
        o.put("failure_reason", failureReason == null ? JSONObject.NULL : (Object) failureReason);
        JSONObject metrics = new JSONObject();
        metrics.put("duration", Math.max(endTimeMs - startTimeMs, 0L) / 1000.0d);
        o.put("metrics", metrics);
        return o;
    }

    public JSONObject logsJson(int since) throws JSONException {
        JSONObject o = new JSONObject();
        JSONArray arr = new JSONArray();
        synchronized (logs) {
            for (int i = Math.max(0, since); i < logs.size(); i++) {
                arr.put(logs.get(i).toJson());
            }
            o.put("next", logs.size());
        }
        o.put("ok", true);
        o.put("logs", arr);
        return o;
    }

    /** 手写拼接错误信息（避免 String.join，其需要 API 26）。 */
    private static String joinErrors(List<String> errors) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < errors.size(); i++) {
            if (i > 0) {
                sb.append("; ");
            }
            sb.append(errors.get(i));
        }
        return sb.toString();
    }

    private static JSONObject errorJson(String message) {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", false);
            o.put("error", message == null ? "未知错误" : message);
        } catch (Exception ignored) {
            // 忽略
        }
        return o;
    }

    private static void sleep(long ms) {
        if (ms <= 0) {
            return;
        }
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
