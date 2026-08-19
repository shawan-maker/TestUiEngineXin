"""运行 Phase 6 验证（项目管理模块-新增项目用例）"""
import sys
import os

sys.path.insert(0, r"D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools")
sys.stdout.reconfigure(encoding='utf-8')

from verification.verify_orchestrator import verify_project

PROJECT_DIR = r"D:\PyProject\TestUiEngineXin\examples\TSManager"
BASE_URL = "http://100.71.19.25:30101"
MODULE = "project"

# Cookie from 2026-08-05
COOKIE = "ud_token=eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ4aWFveWFuZyIsImlzcyI6InRzIiwiaWF0IjoxNzg1OTE5ODcwLCJhdWQiOiJ1c2VyIn0.zwLfTFFxfDzU-bWfjXa-WWSlVHgsLfh0C3sr_EUUMJQ3r7ion2C6ueVRjH76uMPlsMgigQ2VTJesg8esTqZ8Ag"

print("=" * 80)
print("Phase 6 验证 - 项目管理模块（新增项目）")
print(f"项目目录: {PROJECT_DIR}")
print(f"基础 URL: {BASE_URL}")
print(f"模块: {MODULE}")
print("=" * 80)

try:
    result = verify_project(
        project_dir=PROJECT_DIR,
        cookie=COOKIE,
        base_url=BASE_URL,
        module=MODULE,
        headed=True
    )

    print("\n" + "=" * 80)
    print("验证完成")
    print("=" * 80)

    if result:
        print(f"总步骤数: {result.get('total_steps', 0)}")
        print(f"已验证: {result.get('verified', 0)}")
        print(f"失败: {result.get('failed', 0)}")
        print(f"跳过: {result.get('skipped', 0)}")
        print(f"回写数量: {result.get('writeback_count', 0)}")

        # 检查降级写回
        verified_locators = result.get('verified_locators', {})
        degraded_count = 0
        for ref, info in verified_locators.items():
            marker = info.get('marker', '')
            if marker and 'DOWNGRADED' in marker:
                degraded_count += 1
                print(f"\n降级写回: {ref}")
                print(f"  marker: {marker}")
                print(f"  locator: {info.get('locator', '')[:100]}")

        if degraded_count > 0:
            print(f"\n总计 {degraded_count} 个 locator 被降级写回")
        else:
            print("\n无降级写回")

except Exception as e:
    print(f"\n验证失败: {e}")
    import traceback
    traceback.print_exc()
