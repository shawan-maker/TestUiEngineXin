"""
Element UI Dialog 容器检测问题验证

问题：detect_visible_containers 检查 .el-dialog 的尺寸，但 Element UI 的 dialog
结构是 wrapper 控制显示/隐藏，dialog 本身尺寸可能为 0。

修复：改为检查 .el-dialog__wrapper 的 display 属性。
"""
import sys
sys.path.insert(0, r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools')

from playwright.sync_api import sync_playwright

def test_dialog_detection():
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()

    # 创建模拟 Element UI dialog 结构
    page.set_content("""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            .el-dialog__wrapper {
                position: fixed;
                top: 0;
                right: 0;
                bottom: 0;
                left: 0;
                overflow: auto;
                margin: 0;
            }
            .el-dialog {
                margin: 15vh auto 50px;
                background: #fff;
                border-radius: 2px;
                box-shadow: 0 1px 3px rgba(0,0,0,.3);
                box-sizing: border-box;
                width: 50%;
            }
            .el-dialog__body {
                padding: 30px 20px;
            }
        </style>
    </head>
    <body>
        <!-- 隐藏的 dialog -->
        <div class="el-dialog__wrapper" style="display: none;">
            <div class="el-dialog">
                <div class="el-dialog__body">隐藏的 Dialog</div>
            </div>
        </div>

        <!-- 可见的 dialog -->
        <div class="el-dialog__wrapper" style="display: block;">
            <div class="el-dialog">
                <div class="el-dialog__body">可见的 Dialog</div>
            </div>
        </div>
    </body>
    </html>
    """)

    print("=" * 80)
    print("Element UI Dialog 检测验证")
    print("=" * 80)

    # 原始方法：检测 .el-dialog
    original = page.evaluate("""
        (() => {
            const visible = [];
            const dialogs = document.querySelectorAll('.el-dialog');
            console.log('Found dialogs:', dialogs.length);
            for (let i = 0; i < dialogs.length; i++) {
                const dialog = dialogs[i];
                const rect = dialog.getBoundingClientRect();
                const style = window.getComputedStyle(dialog);
                const wrapper = dialog.parentElement;
                const wrapperStyle = window.getComputedStyle(wrapper);

                console.log(`Dialog ${i}:`, {
                    rect: { width: rect.width, height: rect.height },
                    display: style.display,
                    visibility: style.visibility,
                    wrapperDisplay: wrapperStyle.display
                });

                if (rect.width > 0 && rect.height > 0 &&
                    style.display !== 'none' && style.visibility !== 'hidden') {
                    visible.push('dialog');
                    console.log(`Dialog ${i} passed check`);
                } else {
                    console.log(`Dialog ${i} failed check`);
                }
            }
            return visible;
        })()
    """)
    print(f"\n原始方法 (检测 .el-dialog):")
    print(f"  结果: {original}")
    print(f"  检测逻辑: rect.width > 0 && rect.height > 0 && display !== 'none'")

    # 修复方法：检测 .el-dialog__wrapper
    fixed = page.evaluate("""
        (() => {
            const visible = [];
            const wrappers = document.querySelectorAll('.el-dialog__wrapper');
            console.log('Found wrappers:', wrappers.length);
            for (let i = 0; i < wrappers.length; i++) {
                const wrapper = wrappers[i];
                const style = window.getComputedStyle(wrapper);

                console.log(`Wrapper ${i}:`, {
                    display: style.display,
                    visibility: style.visibility
                });

                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    visible.push('dialog');
                    console.log(`Wrapper ${i} passed check`);
                } else {
                    console.log(`Wrapper ${i} failed check`);
                }
            }
            return visible;
        })()
    """)
    print(f"\n修复方法 (检测 .el-dialog__wrapper):")
    print(f"  结果: {fixed}")
    print(f"  检测逻辑: display !== 'none' && visibility !== 'hidden'")

    # 详细分析
    analysis = page.evaluate("""
        (() => {
            const dialogs = document.querySelectorAll('.el-dialog');
            const wrappers = document.querySelectorAll('.el-dialog__wrapper');

            return {
                dialogs: Array.from(dialogs).map((d, i) => ({
                    index: i,
                    rect: {
                        width: Math.round(d.getBoundingClientRect().width),
                        height: Math.round(d.getBoundingClientRect().height)
                    },
                    style: {
                        display: window.getComputedStyle(d).display,
                        visibility: window.getComputedStyle(d).visibility
                    },
                    wrapperDisplay: window.getComputedStyle(d.parentElement).display
                })),
                wrappers: Array.from(wrappers).map((w, i) => ({
                    index: i,
                    style: {
                        display: window.getComputedStyle(w).display,
                        visibility: window.getComputedStyle(w).visibility
                    }
                }))
            };
        })()
    """)

    print(f"\n详细分析:")
    print(f"\n  .el-dialog 元素:")
    for d in analysis['dialogs']:
        status = "✓ 可见" if (d['rect']['width'] > 0 and d['rect']['height'] > 0) else "✗ 不可见"
        print(f"    [{d['index']}] {d['rect']['width']}x{d['rect']['height']} - {status}")
        print(f"        dialog.display={d['style']['display']}")
        print(f"        wrapper.display={d['wrapperDisplay']}")

    print(f"\n  .el-dialog__wrapper 元素:")
    for w in analysis['wrappers']:
        status = "✓ 可见" if w['style']['display'] != 'none' else "✗ 隐藏"
        print(f"    [{w['index']}] wrapper.display={w['style']['display']} - {status}")

    print(f"\n结论:")
    print(f"  原始方法检测到 {len(original)} 个 dialog")
    print(f"  修复方法检测到 {len(fixed)} 个 dialog")

    if len(original) < len(fixed):
        print(f"\n  ✓ 修复方案有效！改为检测 wrapper 可以正确识别可见的 dialog")
    elif len(original) == len(fixed):
        print(f"\n  ⚠ 两种方法结果相同，问题可能在其他地方")
    else:
        print(f"\n  ✗ 异常情况：原始方法检测到的更多")

    browser.close()
    pw.stop()

if __name__ == '__main__':
    test_dialog_detection()
