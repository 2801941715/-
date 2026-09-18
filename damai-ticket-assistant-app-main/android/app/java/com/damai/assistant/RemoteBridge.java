package com.damai.assistant;

import android.accessibilityservice.AccessibilityService;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.Charset;

/**
 * 远程调试桥（Windows 侧调试入口）。
 *
 * 手机端在 127.0.0.1:8710 监听，只绑定回环地址；
 * Windows 侧通过 USB/无线 adb 建立端口转发即可访问：
 *
 *     adb forward tcp:8710 tcp:8710
 *     python tools/damai_remote.py --status
 *
 * 协议：一行一个 JSON 请求，一行一个 JSON 响应（换行分隔）。
 * 请求示例：  {"cmd":"start","config":{...}}
 * 响应示例：  {"ok":true,"state":"running"}
 *
 * 之所以只绑定回环地址：避免在局域网内被其它设备访问，
 * 远程访问必须经由开发者主动建立的 adb 转发通道。
 */
public class RemoteBridge {

    private static final String TAG = "DamaiRemoteBridge";

    /** 与 Windows 侧 tools/damai_remote.py 约定的端口。 */
    public static final int PORT = 8710;
    private static final Charset UTF8 = Charset.forName("UTF-8");

    private final AccessibilityService service;
    private ServerSocket serverSocket;
    private Thread acceptThread;
    private volatile boolean running;

    public RemoteBridge(AccessibilityService service) {
        this.service = service;
    }

    public void start() {
        if (running) {
            return;
        }
        running = true;
        acceptThread = new Thread(new Runnable() {
            @Override
            public void run() {
                acceptLoop();
            }
        }, "damai-remote-bridge");
        acceptThread.setDaemon(true);
        acceptThread.start();
        Log.i(TAG, "remote bridge listening on 127.0.0.1:" + PORT);
    }

    public void stop() {
        running = false;
        try {
            if (serverSocket != null) {
                serverSocket.close();
            }
        } catch (Exception ignored) {
            // 忽略关闭异常
        }
        serverSocket = null;
    }

    private void acceptLoop() {
        try {
            serverSocket = new ServerSocket(PORT, 8, InetAddress.getByName("127.0.0.1"));
            while (running) {
                Socket socket = null;
                try {
                    socket = serverSocket.accept();
                    handle(socket);
                } catch (Exception e) {
                    if (running) {
                        Log.w(TAG, "accept failed: " + e);
                    }
                } finally {
                    closeQuietly(socket);
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "bridge server stopped: " + e);
        }
    }

    private void handle(Socket socket) throws Exception {
        socket.setSoTimeout(120000);
        BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream(), UTF8));
        BufferedWriter out = new BufferedWriter(new OutputStreamWriter(socket.getOutputStream(), UTF8));

        String line;
        while ((line = in.readLine()) != null) {
            if (line.trim().isEmpty()) {
                continue;
            }
            JSONObject response;
            try {
                JSONObject request = new JSONObject(line);
                response = dispatch(request);
            } catch (Exception e) {
                response = new JSONObject();
                response.put("ok", false);
                response.put("error", String.valueOf(e.getMessage()));
            }
            out.write(response.toString());
            out.write("\n");
            out.flush();
        }
    }

    private JSONObject dispatch(JSONObject request) throws Exception {
        String cmd = request.optString("cmd", "ping");
        RunController controller = RunController.get();

        if ("ping".equals(cmd)) {
            JSONObject r = ok();
            r.put("pong", true);
            r.put("version", BuildConfig.VERSION_NAME);
            return r;
        }
        if ("status".equals(cmd)) {
            return controller.statusJson();
        }
        if ("getConfig".equals(cmd)) {
            return ok().put("config", controller.getConfig().toJson());
        }
        if ("setConfig".equals(cmd)) {
            JSONObject cfg = request.optJSONObject("config");
            if (cfg == null) {
                return error("缺少 config 字段");
            }
            return controller.applyConfig(cfg);
        }
        if ("start".equals(cmd)) {
            JSONObject cfg = request.optJSONObject("config");
            if (cfg != null) {
                JSONObject applied = controller.applyConfig(cfg);
                if (!applied.optBoolean("ok", false)) {
                    return applied;
                }
            }
            return controller.start();
        }
        if ("stop".equals(cmd)) {
            return controller.stop();
        }
        if ("logs".equals(cmd)) {
            return controller.logsJson(request.optInt("since", 0));
        }
        if ("tap".equals(cmd)) {
            // 调试探针：直接派发一次原生手势点击，返回派发与回调结果
            int x = request.optInt("x");
            int y = request.optInt("y");
            int duration = request.optInt("duration", 50);
            NodeFinder finder = new NodeFinder(service);
            int outcome = finder.probeClick(x, y, (long) duration);
            // outcome: 0=完成 1=取消 2=超时 3=未派发
            return ok().put("outcome", outcome).put("x", x).put("y", y).put("duration", duration);
        }
        if ("actionClickAt".equals(cmd)) {
            // 探针：按坐标找「最内层可点击节点」并用 ACTION_CLICK 点击，
            // 用于测试无 id / 无文本的自定义控件能否走无障碍动作通道。
            int x = request.optInt("x");
            int y = request.optInt("y");
            NodeFinder f = new NodeFinder(service);
            android.view.accessibility.AccessibilityNodeInfo root = f.root();
            if (root == null) {
                return error("无法获取根节点");
            }
            android.view.accessibility.AccessibilityNodeInfo hit = null;
            android.view.accessibility.AccessibilityNodeInfo cur = root;
            // 自上而下深入，找到包含该点且仍可继续深入的子节点
            for (int depth = 0; depth < 30; depth++) {
                android.view.accessibility.AccessibilityNodeInfo next = null;
                int n = cur.getChildCount();
                for (int i = 0; i < n; i++) {
                    android.view.accessibility.AccessibilityNodeInfo c = cur.getChild(i);
                    if (c == null) continue;
                    android.graphics.Rect r = NodeFinder.boundsOf(c);
                    if (r.contains(x, y)) { next = c; break; }
                }
                if (next == null) break;
                cur = next;
                if (cur.isClickable()) hit = cur;   // 记录最内层可点击节点
            }
            if (hit == null) {
                return ok().put("hit", false).put("note", "该坐标下无 clickable 节点");
            }
            boolean okc = false;
            try { okc = hit.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK); }
            catch (Exception e) { return error("performAction 异常: " + e); }
            JSONObject r = ok();
            r.put("hit", true);
            r.put("cls", String.valueOf(hit.getClassName()));
            r.put("id", String.valueOf(hit.getViewIdResourceName()));
            r.put("bounds", NodeFinder.boundsOf(hit).toShortString());
            r.put("performed", okc);
            return r;
        }
        if ("actionClick".equals(cmd)) {
            // 诊断探针：用无障碍 ACTION_CLICK 直接作用于节点（不派发手势），
            // 用于判断「大麦是否同时过滤无障碍动作点击」。
            // 若该通道有效，则悬浮球可完全脱离电脑运行。
            String rid = request.optString("id", "");
            String text = request.optString("text", "");
            NodeFinder f = new NodeFinder(service);
            NodeFinder.Selector sel = rid.isEmpty()
                    ? NodeFinder.Selector.textContains(text)
                    : NodeFinder.Selector.id(rid);
            android.view.accessibility.AccessibilityNodeInfo node = f.findFirst(sel);
            if (node == null) {
                return error("未找到节点");
            }
            boolean clickableSelf = node.isClickable();
            android.view.accessibility.AccessibilityNodeInfo target = clickableSelf
                    ? node
                    : NodeFinder.clickableAncestor(node);
            boolean ok = false;
            if (target != null) {
                try {
                    ok = target.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK);
                } catch (Exception e) {
                    return error("performAction 异常: " + e);
                }
            }
            JSONObject r = ok();
            r.put("bound", clickableSelf ? "self" : (target != null ? "ancestor" : "none"));
            r.put("performed", ok);
            return r;
        }
        if ("caps".equals(cmd)) {
            // 调试探针：回报无障碍服务的能力与手势可用性
            android.accessibilityservice.AccessibilityServiceInfo info = service.getServiceInfo();
            JSONObject r = ok();
            r.put("capabilities", info == null ? -1 : info.getCapabilities());
            r.put("canPerformGestures", NodeFinder.canPerformGestures(service));
            return r;
        }
        if ("dump".equals(cmd)) {
            String dump;
            synchronized (RemoteBridge.class) {
                dump = NodeDumper.dump(service.getRootInActiveWindow());
            }
            return ok().put("xml", dump);
        }
        return error("未知命令: " + cmd);
    }

    private static JSONObject ok() throws Exception {
        JSONObject o = new JSONObject();
        o.put("ok", true);
        return o;
    }

    private static JSONObject error(String message) throws Exception {
        JSONObject o = new JSONObject();
        o.put("ok", false);
        o.put("error", message);
        return o;
    }

    private static void closeQuietly(Socket s) {
        try {
            if (s != null) {
                s.close();
            }
        } catch (Exception ignored) {
            // 忽略
        }
    }
}
