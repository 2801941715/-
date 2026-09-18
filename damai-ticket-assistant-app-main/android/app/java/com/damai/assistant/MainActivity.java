package com.damai.assistant;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.List;

/**
 * 手机端主界面：编辑配置、开启无障碍、启动/停止抢票、查看运行日志与统计。
 *
 * 界面完全使用系统控件构建（不依赖 AppCompat / Material 等外部库），
 * 以便在无网络环境下使用命令行工具链直接离线构建。
 */
public class MainActivity extends Activity implements RunController.Listener {

    private EditText keywordField;
    private EditText cityField;
    private EditText priceField;
    private EditText priceIndexField;
    private EditText usersField;
    private CheckBox commitOrderCheck;
    private TextView serviceStatusView;
    private TextView phaseView;
    private TextView logView;
    private Button startButton;
    private Button stopButton;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private RunController controller;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        controller = RunController.get();
        setContentView(buildLayout());
        controller.addListener(this);
        refreshServiceStatus();
        refreshState();
        renderAllLogs();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshServiceStatus();
        refreshState();
    }

    @Override
    protected void onDestroy() {
        controller.removeListener(this);
        super.onDestroy();
    }

    // ------------------------------------------------------------------
    // 界面
    // ------------------------------------------------------------------

    private View buildLayout() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);

        root.addView(title("大麦抢票助手 v" + BuildConfig.VERSION_NAME));
        TextView hint = new TextView(this);
        hint.setText("本应用通过系统无障碍服务在手机本地自动完成抢票，无需连接电脑。"
                + "首次使用请先开启无障碍权限。");
        hint.setTextSize(13);
        hint.setPadding(0, dp(4), 0, dp(12));
        root.addView(hint);

        // ---- 无障碍状态 ----
        LinearLayout serviceCard = card(root, "无障碍服务");
        serviceStatusView = new TextView(this);
        serviceCard.addView(serviceStatusView);
        Button openSettings = new Button(this);
        openSettings.setText("开启无障碍权限");
        openSettings.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openAccessibilitySettings();
            }
        });
        serviceCard.addView(openSettings);

        // ---- 运行参数 ----
        LinearLayout params = card(root, "抢票参数");
        keywordField = addField(params, "关键词（演出/歌手）");
        cityField = addField(params, "城市");
        priceField = addField(params, "票价文本（可选）");
        priceIndexField = addField(params, "票价索引（从 0 开始，可留空）");
        usersField = addField(params, "观演人（每行一个，或用逗号分隔）");

        commitOrderCheck = new CheckBox(this);
        commitOrderCheck.setText("自动提交订单（谨慎使用）");
        params.addView(commitOrderCheck);

        // ---- 控制按钮 ----
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setPadding(0, dp(12), 0, dp(12));
        startButton = new Button(this);
        startButton.setText("开始抢票");
        startButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onStartClicked();
            }
        });
        stopButton = new Button(this);
        stopButton.setText("停止");
        stopButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                controller.stop();
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        actions.addView(startButton, lp);
        actions.addView(stopButton, lp);
        root.addView(actions);

        // ---- 运行状态 ----
        LinearLayout statusCard = card(root, "运行状态");
        phaseView = new TextView(this);
        statusCard.addView(phaseView);
        Button exportLogs = new Button(this);
        exportLogs.setText("导出日志到文件");
        exportLogs.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                exportLogs();
            }
        });
        statusCard.addView(exportLogs);

        // ---- 日志 ----
        LinearLayout logCard = card(root, "运行日志");
        logView = new TextView(this);
        logView.setTextSize(12);
        logView.setVerticalScrollBarEnabled(true);
        logView.setPadding(dp(6), dp(6), dp(6), dp(6));
        logCard.addView(logView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(280)));

        loadConfigIntoForm();
        return scroll;
    }

    private TextView title(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextSize(20);
        v.setGravity(Gravity.CENTER_HORIZONTAL);
        return v;
    }

    private LinearLayout card(LinearLayout parent, String heading) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(10), dp(10), dp(10), dp(10));
        TextView h = new TextView(this);
        h.setText(heading);
        h.setTextSize(15);
        h.setPadding(0, 0, 0, dp(6));
        box.addView(h);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(6), 0, dp(6));
        parent.addView(box, lp);
        return box;
    }

    private EditText addField(LinearLayout parent, String label) {
        TextView l = new TextView(this);
        l.setText(label);
        l.setTextSize(13);
        l.setPadding(0, dp(6), 0, dp(2));
        parent.addView(l);
        EditText e = new EditText(this);
        e.setSingleLine(false);
        parent.addView(e);
        return e;
    }

    private int dp(int value) {
        float density = getResources().getDisplayMetrics().density;
        return (int) (value * density + 0.5f);
    }

    // ------------------------------------------------------------------
    // 配置读写
    // ------------------------------------------------------------------

    private void loadConfigIntoForm() {
        Config c = controller.getConfig();
        keywordField.setText(c.keyword);
        cityField.setText(c.city);
        priceField.setText(c.price);
        priceIndexField.setText(c.priceIndex == null ? "" : String.valueOf(c.priceIndex));
        usersField.setText(TextUtils.join("\n", c.users));
        commitOrderCheck.setChecked(c.ifCommitOrder);
    }

    private boolean collectConfigFromForm() {
        JSONObject payload = new JSONObject();
        try {
            payload.put("keyword", keywordField.getText().toString().trim());
            payload.put("city", cityField.getText().toString().trim());
            payload.put("price", priceField.getText().toString().trim());

            String idxText = priceIndexField.getText().toString().trim();
            if (idxText.isEmpty()) {
                payload.put("price_index", JSONObject.NULL);
            } else {
                try {
                    payload.put("price_index", Integer.parseInt(idxText));
                } catch (NumberFormatException e) {
                    toast("票价索引必须是整数");
                    return false;
                }
            }

            org.json.JSONArray users = new org.json.JSONArray();
            List<String> parsed = Config.parseUsers(usersField.getText().toString());
            for (String u : parsed) {
                users.put(u);
            }
            payload.put("users", users);
            payload.put("if_commit_order", commitOrderCheck.isChecked());
        } catch (JSONException e) {
            toast("配置组装失败: " + e.getMessage());
            return false;
        }

        JSONObject result = controller.applyConfig(payload);
        if (!result.optBoolean("ok", false)) {
            toast(result.optString("error", "配置无效"));
            return false;
        }
        return true;
    }

    // ------------------------------------------------------------------
    // 交互
    // ------------------------------------------------------------------

    private void onStartClicked() {
        if (DamaiAutomationService.getInstance() == null) {
            toast("请先开启本应用的无障碍权限");
            openAccessibilitySettings();
            return;
        }
        if (!collectConfigFromForm()) {
            return;
        }
        JSONObject result = controller.start();
        if (!result.optBoolean("ok", false)) {
            toast(result.optString("error", "启动失败"));
        }
    }

    private void openAccessibilitySettings() {
        try {
            Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
            toast("请在列表中找到「大麦抢票助手」并开启");
        } catch (ActivityNotFoundException e) {
            toast("无法打开无障碍设置，请手动前往：设置 → 无障碍");
        }
    }

    private void refreshServiceStatus() {
        boolean connected = DamaiAutomationService.getInstance() != null;
        serviceStatusView.setText(connected
                ? "状态：已开启（自动化引擎可用）"
                : "状态：未开启 —— 请点击下方按钮开启无障碍权限");
    }

    private void refreshState() {
        ui.post(new Runnable() {
            @Override
            public void run() {
                boolean running = controller.isRunning();
                startButton.setEnabled(!running);
                stopButton.setEnabled(running);

                StringBuilder sb = new StringBuilder();
                sb.append("阶段：").append(controller.getPhase()).append("\n");
                sb.append("状态：").append(running ? "运行中" : "空闲");
                phaseView.setText(sb.toString());
            }
        });
    }

    private void renderAllLogs() {
        List<LogEntry> entries = controller.snapshotLogs();
        StringBuilder sb = new StringBuilder();
        for (LogEntry e : entries) {
            sb.append(e.toDisplayLine()).append('\n');
        }
        logView.setText(sb.toString());
    }

    private void exportLogs() {
        try {
            JSONObject report = controller.reportJson();
            java.io.File dir = getExternalFilesDir(null);
            if (dir == null) {
                dir = getFilesDir();
            }
            java.io.File out = new java.io.File(dir, "damai_run_report.json");
            java.io.FileOutputStream fos = new java.io.FileOutputStream(out);
            try {
                fos.write(report.toString(2).getBytes("UTF-8"));
            } finally {
                fos.close();
            }
            toast("已导出: " + out.getAbsolutePath());
        } catch (Exception e) {
            toast("导出失败: " + e.getMessage());
        }
    }

    private void toast(final String message) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                Toast.makeText(MainActivity.this, message, Toast.LENGTH_SHORT).show();
            }
        });
    }

    // ------------------------------------------------------------------
    // RunController.Listener
    // ------------------------------------------------------------------

    @Override
    public void onStateChanged() {
        refreshState();
    }

    @Override
    public void onLog(final LogEntry entry) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                logView.append(entry.toDisplayLine() + "\n");
                int scroll = logView.getLayout() == null ? 0
                        : logView.getLayout().getLineTop(logView.getLineCount()) - logView.getHeight();
                logView.scrollTo(0, Math.max(scroll, 0));
            }
        });
    }
}
