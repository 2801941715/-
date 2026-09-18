package com.damai.assistant;

import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;

/**
 * 将当前无障碍节点树序列化为 XML，用于 Windows 侧远程调试
 * （对应原项目脚本 scripts/dump_current_page.py 的 dump 能力）。
 *
 * 输出格式与 `uiautomator dump` 保持一致：
 *   - 元素标签名 = 控件类名（如 android.widget.FrameLayout）
 *   - 父子层级嵌套，叶子节点自闭合
 *   - 属性名与其含义对齐原 dump（resource-id / bounds / clickable / checked ...）
 *
 * 这样项目原有基于 page_dump.xml 的分析脚本可以直接读取本 dump。
 */
public final class NodeDumper {

    private static final int MAX_DEPTH = 60;

    private NodeDumper() {
    }

    public static String dump(AccessibilityNodeInfo root) {
        if (root == null) {
            return "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n<hierarchy>\n</hierarchy>\n";
        }
        StringBuilder sb = new StringBuilder(8192);
        sb.append("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n");
        Rect bounds = new Rect();
        root.getBoundsInScreen(bounds);
        // 与 uiautomator dump 的根节点形式对齐
        sb.append("<hierarchy index=\"0\" class=\"hierarchy\" rotation=\"0\" width=\"")
          .append(bounds.width())
          .append("\" height=\"")
          .append(bounds.height())
          .append("\">\n");
        dumpNode(root, sb, 1);
        sb.append("</hierarchy>\n");
        return sb.toString();
    }

    private static void dumpNode(AccessibilityNodeInfo node, StringBuilder sb, int depth) {
        if (node == null || depth > MAX_DEPTH) {
            return;
        }
        String indent = indent(depth);
        String tag = tagName(node);
        Rect r = new Rect();
        node.getBoundsInScreen(r);

        CharSequence text = node.getText();
        CharSequence desc = node.getContentDescription();
        CharSequence cls = node.getClassName();
        CharSequence pkg = node.getPackageName();

        sb.append(indent)
          .append('<').append(tag)
          .append(" index=\"").append(depth).append('"')
          .append(" package=\"").append(escape(pkg)).append('"')
          .append(" class=\"").append(escape(cls)).append('"')
          .append(" text=\"").append(escape(text)).append('"')
          .append(" resource-id=\"").append(escape(node.getViewIdResourceName())).append('"')
          .append(" content-desc=\"").append(escape(desc)).append('"')
          .append(" checkable=\"").append(node.isCheckable()).append('"')
          .append(" checked=\"").append(node.isChecked()).append('"')
          .append(" clickable=\"").append(node.isClickable()).append('"')
          .append(" enabled=\"").append(node.isEnabled()).append('"')
          .append(" focusable=\"").append(node.isFocusable()).append('"')
          .append(" focused=\"").append(node.isFocused()).append('"')
          .append(" scrollable=\"").append(node.isScrollable()).append('"')
          .append(" selected=\"").append(node.isSelected()).append('"')
          .append(" bounds=\"[").append(r.left).append(',').append(r.top).append("][")
          .append(r.right).append(',').append(r.bottom).append("]\"");

        int childCount = 0;
        try {
            childCount = node.getChildCount();
        } catch (Exception ignored) {
            // 节点可能已失效，按叶子处理
        }

        if (childCount == 0) {
            sb.append(" />\n");
            return;
        }

        sb.append(">\n");
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = null;
            try {
                child = node.getChild(i);
            } catch (Exception ignored) {
                // 单个子节点失效不影响整体 dump
            }
            dumpNode(child, sb, depth + 1);
        }
        sb.append(indent).append("</").append(tag).append(">\n");
    }

    /**
     * 生成合法 XML 标签名。
     * 类名形如 android.widget.FrameLayout（点号在 XML 名称中合法），
     * 为空或非法时退回 "node"。
     */
    private static String tagName(AccessibilityNodeInfo node) {
        CharSequence cls = node.getClassName();
        if (cls == null) {
            return "node";
        }
        String name = cls.toString().trim();
        if (name.isEmpty()) {
            return "node";
        }
        // 去掉可能存在的内部类 $ 与空格，保证是合法名称
        name = name.replace('$', '_').replaceAll("\\s+", "_");
        if (!name.matches("[A-Za-z_][A-Za-z0-9_.-]*")) {
            return "node";
        }
        return name;
    }

    private static String indent(int depth) {
        StringBuilder sb = new StringBuilder(depth * 2);
        for (int i = 0; i < depth; i++) {
            sb.append("  ");
        }
        return sb.toString();
    }

    private static String escape(CharSequence value) {
        if (value == null) {
            return "";
        }
        String s = value.toString();
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '&': sb.append("&amp;"); break;
                case '<': sb.append("&lt;"); break;
                case '>': sb.append("&gt;"); break;
                case '"': sb.append("&quot;"); break;
                case '\'': sb.append("&apos;"); break;
                case '\n': sb.append("&#10;"); break;
                case '\r': sb.append("&#13;"); break;
                case '\t': sb.append("&#9;"); break;
                default:
                    // 丢弃控制字符，避免生成非法 XML
                    if (c < 0x20 && c != '\n' && c != '\r' && c != '\t') {
                        break;
                    }
                    sb.append(c);
            }
        }
        return sb.toString();
    }
}
