#!/usr/bin/env python3
"""run_phase4.py — Phase 4 全自动探测编排器

自动串联三步流程：
  1. read_excel.py --extract-urls → module_urls.json
  2. discover_page.py --module-urls → discovery_{slug}.json (per module)
  3. _pages_writer.generate_pages_yaml_from_discovery() → pages YAML (per module, v2 direct import)

用法:
    python tools/run_phase3.py \
        --excel "examples/webuic测试用例-天枢1-修正版.xlsx" \
        --config "examples/TSManager2/config.yaml" \
        --project "examples/TSManager2" \
        --cookie "ud_token=..." \
        [--module "question_manage"] \
        [--local-storage "{...}"] \
        [--skip-discover] \
        [--skip-generate]
"""

import argparse
import glob
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))  # Add tools/ for _pages_writer

# v2 direct imports (replacing subprocess calls — G17)
from generation.pages_writer import generate_pages_yaml_from_discovery as _generate_pages_yaml


def run_cmd(cmd, label):
    """Run a subprocess command, return True on success."""
    print(f"\n{'='*60}")
    print(f"[Phase 4] {label}")
    print(f"{'='*60}")
    print(f"  CMD: {' '.join(cmd)}")
    try:
        # Force UTF-8 for all subprocesses (fixes Playwright GBK issue on Windows)
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'  # 禁用子进程输出缓冲，确保 print() 立即刷新
        result = subprocess.run(
            cmd, capture_output=False, text=True,
            encoding='utf-8', errors='replace',
            env=env,
        )
        if result.returncode != 0:
            print(f"[ERROR] {label} 失败 (exit {result.returncode})", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[ERROR] {label} 异常: {e}", file=sys.stderr)
        return False


def load_config(config_path):
    """Load config.yaml, return dict."""
    try:
        import yaml
        with open(config_path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        print("[WARN] yaml not installed, cannot read config", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[WARN] Cannot read config: {e}", file=sys.stderr)
        return {}


def _merge_discovery_files(probe_dir, slug):
    """M2: Glob 合并 — 查找 discovery_{slug}*.json 系列并合并。

    如果只有一个文件，返回该文件路径。
    如果有多个文件（_2, _3, ...），合并 pages[] 数组后写入新文件。
    如果没有文件，返回 None。
    """
    pattern = os.path.join(probe_dir, f'discovery_{slug}*.json')
    files = sorted(glob.glob(pattern))

    if not files:
        return None
    if len(files) == 1:
        return files[0]

    # 多个文件：合并 pages[] 数组
    merged = {'pages': [], 'module': slug, '_merged_from': []}
    for fpath in files:
        try:
            with open(fpath, encoding='utf-8') as f:
                data = json.load(f)
            if 'pages' in data:
                merged['pages'].extend(data['pages'])
            else:
                # 旧格式（单 URL）：包装为 pages[] 条目
                merged['pages'].append({
                    'url': data.get('url', ''),
                    'framework': data.get('framework'),  # L1: 保留页面级框架
                    'containers': data.get('containers', []),
                    'list_page': data.get('list_page', {}),
                })
            # 从第一个文件继承 cn_name（如果存在）
            if 'cn_name' not in merged and 'cn_name' in data:
                merged['cn_name'] = data['cn_name']
            merged['_merged_from'].append(os.path.basename(fpath))
        except Exception as e:
            print(f"[WARN] 无法读取 {fpath}: {e}", file=sys.stderr)

    if not merged['pages']:
        return files[0]  # 回退到第一个文件

    merged_path = os.path.join(probe_dir, f'discovery_{slug}_merged.json')
    with open(merged_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    n_pages = len(merged['pages'])
    print(f"[M2] 合并 {len(files)} 个 discovery 文件 → {n_pages} pages")
    return merged_path


def main():
    parser = argparse.ArgumentParser(
        description='Phase 4 全自动探测编排器 — 串联 URL 提取 + 探测 + pages 生成'
    )
    parser.add_argument('--excel', required=True,
                        help='Excel 测试用例文件路径')
    parser.add_argument('--config', required=True,
                        help='config.yaml 路径')
    parser.add_argument('--project', required=True,
                        help='项目根目录路径')
    parser.add_argument('--cookie', default=None,
                        help='Cookie 字符串（默认从 config.yaml 读取）')
    parser.add_argument('--module', default=None,
                        help='限定单个模块（默认全部）')
    parser.add_argument('--local-storage', default=None,
                        help='额外 localStorage 注入（JSON 对象字符串）')
    parser.add_argument('--skip-discover', action='store_true',
                        help='跳过探测步骤（使用已有 discovery JSON）')
    parser.add_argument('--skip-generate', action='store_true',
                        help='跳过 pages 生成步骤')
    parser.add_argument('--module-map', default='',
                        help='手动覆盖模块映射，格式: 中文名1=slug1,中文名2=slug2')

    args = parser.parse_args()

    # Windows 终端编码兼容
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8')

    # ── 管线自愈：Phase 2/3 缺失时自动补全，其余记日志不阻断 ──
    from infra.pipeline_guard import check_pipeline_state
    check_pipeline_state(args.project, ["phase_0", "phase_2"], "run_phase4.py",
                          {"excel_path": args.excel, "cookie": args.cookie})

    # ── Step 0: 准备 ──
    probe_dir = os.path.join(args.project, '_probe')
    os.makedirs(probe_dir, exist_ok=True)
    pages_dir = os.path.join(args.project, 'pages')

    # Cookie: CLI > config.yaml
    cookie = args.cookie
    if not cookie:
        cfg = load_config(args.config)
        cookie = cfg.get('cookie', '')
        if not cookie:
            print("[ERROR] 没有可用的 cookie（CLI 或 config.yaml）", file=sys.stderr)
            sys.exit(1)

    # localStorage: CLI > config.yaml
    local_storage = args.local_storage
    if not local_storage:
        cfg = load_config(args.config)
        ls = cfg.get('local_storage', {})
        if ls:
            local_storage = json.dumps(ls, ensure_ascii=False)

    # ── Step 1: 提取 URL ──
    module_urls_path = os.path.join(probe_dir, 'module_urls.json')
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, '..', 'excel', 'read_excel.py'),
           args.excel, '--extract-urls',
           '--pages-dir', pages_dir,
           '--config', args.config,
           '--output', module_urls_path]
    success = run_cmd(cmd, 'Step 1: 从 Excel 提取模块 URL')
    if not success:
        print("[FATAL] Step 1 失败，无法继续", file=sys.stderr)
        sys.exit(1)

    with open(module_urls_path, encoding='utf-8') as f:
        module_urls = json.load(f)

    # ── Step 1.5: 构建 cn_name → slug 映射（调用 build_module_map.py）──
    # module_urls.json 格式: {cn_name: {"urls": [...]}} — key 是中文名
    # build_module_map.py 从 Excel + pages/ + YAML 注释 + discovery JSON 构建映射
    print(f"\n{'='*60}")
    print(f"[Phase 4] Step 1.5: 构建模块名映射 (cn_name → slug)")
    print(f"{'='*60}")

    module_map_path = os.path.join(probe_dir, 'module_map.json')

    # 如果 module_map.json 已存在且有效，直接复用（避免覆盖手动映射）
    # BUG-4 fix: 当 --module-map 从 CLI 传入时，删除旧缓存并重新生成
    if args.module_map and os.path.isfile(module_map_path):
        os.remove(module_map_path)
        print(f"[INFO] 收到 --module-map，删除旧缓存重新生成")

    if os.path.isfile(module_map_path):
        try:
            with open(module_map_path, encoding='utf-8') as f:
                existing_map = json.load(f)
            if isinstance(existing_map, dict) and len(existing_map) > 0:
                # 检查缓存覆盖率：是否覆盖当前 module_urls 的所有模块
                missing_modules = set(module_urls.keys()) - set(existing_map.keys())
                if missing_modules:
                    print(f"[WARN] module_map.json 缺少 {len(missing_modules)} 个模块: {list(missing_modules)[:3]}{'...' if len(missing_modules) > 3 else ''}")
                    print("[INFO] 删除旧缓存，重新生成")
                    os.remove(module_map_path)
                else:
                    print(f"[INFO] 复用已有的 module_map.json ({len(existing_map)} 个映射)")
                    # 跳过 build_module_map.py
                    with open(module_map_path, encoding='utf-8') as f:
                        cn_to_slug = json.load(f)
            else:
                raise ValueError("Empty or invalid")
        except (json.JSONDecodeError, ValueError):
            print("[WARN] module_map.json 无效，重新生成")
            os.remove(module_map_path)
    else:
        existing_map = None

    if not os.path.isfile(module_map_path):
        pages_dir = os.path.join(args.project, 'pages')
        bmm_cmd = [sys.executable, os.path.join(SCRIPT_DIR, '..', 'excel', 'build_module_map.py'),
                   args.excel,
                   '--pages', pages_dir,
                   '--discovery-dir', probe_dir,
                   '--output', module_map_path,
                   '--module-urls', module_urls_path]
        if args.module_map:
            bmm_cmd.extend(['--module-map', args.module_map])

        bmm_ok = run_cmd(bmm_cmd, 'Step 1.5: build_module_map.py')
        if not (bmm_ok and os.path.isfile(module_map_path)):
            print("[ERROR] build_module_map.py 失败，无法生成模块映射",
                  file=sys.stderr)
            print("[INFO] 请确保 Excel 文件和 pages/ 目录结构正确", file=sys.stderr)
            sys.exit(1)

    with open(module_map_path, encoding='utf-8') as f:
        cn_to_slug = json.load(f)

    if args.module:
        # --module 可以是 slug 或中文名，支持逗号分隔多个模块
        module_names = [m.strip() for m in args.module.split(',')]
        matched = {}
        for module_name in module_names:
            module_matched = {k: v for k, v in module_urls.items()
                             if cn_to_slug.get(k) == module_name or k == module_name}
            if not module_matched:
                print(f"[ERROR] 模块 {module_name} 不在 module_urls.json 中", file=sys.stderr)
                print(f"  可用模块: {', '.join(module_urls.keys())}", file=sys.stderr)
                sys.exit(1)
            matched.update(module_matched)
        module_urls = matched

    print(f"\n[Phase 4] 共 {len(module_urls)} 个模块待探测:")
    for cn_name, data in module_urls.items():
        slug = cn_to_slug.get(cn_name, cn_name)
        print(f"  {slug} ({cn_name}): {len(data['urls'])} URLs")

    # ── Step 2: 逐模块探测 ──
    results = {}
    if not args.skip_discover:
        for cn_name, data in module_urls.items():
            slug = cn_to_slug.get(cn_name, cn_name)
            output_path = os.path.join(probe_dir, f'discovery_{slug}.json')
            cmd = [sys.executable, os.path.join(SCRIPT_DIR, 'discover_page.py'),
                   '--module', slug,
                   '--module-urls', module_urls_path,
                   '--module-map-file', module_map_path,
                   '--cookie', cookie,
                   '--output', output_path]
            if local_storage:
                cmd.extend(['--local-storage', local_storage])
            ok = run_cmd(cmd, f'Step 2: 探测 {slug} ({cn_name})')

            # 认证失败检测：auth_error 阻断 pages 生成，防止空数据覆盖现有 elements.yaml
            if ok and os.path.isfile(output_path):
                try:
                    with open(output_path, encoding='utf-8') as f:
                        _disc = json.load(f)
                    if _disc.get('auth_error'):
                        print(f"[ERROR] {slug}: Cookie 认证失败（被重定向到登录页）",
                              file=sys.stderr)
                        print(f"[ERROR] ⚠️ 请检查以下项目:", file=sys.stderr)
                        print(f"[ERROR]   1. Cookie 是否已过期（浏览器 F12 → Network → 任意请求 → Cookie）", file=sys.stderr)
                        print(f"[ERROR]   2. config.yaml 中的 cookie 值是否与浏览器一致", file=sys.stderr)
                        print(f"[ERROR]   3. cookie_domain 是否正确（应为域名，不含端口和路径）", file=sys.stderr)
                        print(f"[ERROR]   4. 目标系统是否使用 CAS/SSO（重定向链可能未完成）", file=sys.stderr)
                        ok = False
                except Exception:
                    pass

            # 探测成功后立即回写 cn_name（不等 Step 2.5）
            if ok and os.path.isfile(output_path) and cn_name and cn_name != slug:
                try:
                    with open(output_path, encoding='utf-8') as f:
                        disc = json.load(f)
                    if disc.get('cn_name') != cn_name:
                        disc['cn_name'] = cn_name
                        with open(output_path, 'w', encoding='utf-8') as f:
                            json.dump(disc, f, ensure_ascii=False, indent=2)
                        print(f"[INFO] {slug}: cn_name 已回写 → {cn_name}")
                except Exception as e:
                    print(f"[WARN] {slug}: cn_name 立即回写失败 — {e}", file=sys.stderr)

            results[slug] = {
                'success': ok,
                'output': output_path,
                'cn_name': cn_name,
                'urls_count': len(data['urls']),
            }
    else:
        # --skip-discover: 从已有 discovery JSON 加载
        print("\n[Phase 4] --skip-discover: 使用已有 discovery JSON")
        for cn_name, data in module_urls.items():
            slug = cn_to_slug.get(cn_name, cn_name)
            output_path = os.path.join(probe_dir, f'discovery_{slug}.json')
            # M2: glob 合并 — 查找所有匹配的 discovery 文件
            merged_path = _merge_discovery_files(probe_dir, slug)
            if merged_path:
                output_path = merged_path
            if os.path.isfile(output_path):
                results[slug] = {
                    'success': True,
                    'output': output_path,
                    'cn_name': cn_name,
                    'urls_count': len(data['urls']),
                }
            else:
                print(f"[WARN] {output_path} 不存在，跳过 {slug}", file=sys.stderr)

    # ── Step 2.5: 回写 cn_name 到 discovery JSON（持久化唯一来源）──
    # discover_page.py 不写入 cn_name，需要从 module_urls.json 的 key 补充
    for slug, res in results.items():
        if not res.get('success'):
            continue
        cn_name = res.get('cn_name', '')
        if not cn_name or cn_name == slug:
            continue  # 无需回写（cn_name 为空或已等于 slug）

        disc_path = res['output']
        if not os.path.isfile(disc_path):
            continue

        try:
            with open(disc_path, encoding='utf-8') as f:
                disc = json.load(f)
            if disc.get('cn_name') != cn_name:  # 避免无谓写入
                disc['cn_name'] = cn_name
                with open(disc_path, 'w', encoding='utf-8') as f:
                    json.dump(disc, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] {slug}: cn_name 回写失败 — {e}", file=sys.stderr)

    # ── Step 2.6: 生成统一 discovery.json（多模块聚合）──
    # 将所有模块的 per-module discovery 文件合并为一个统一的 discovery.json
    # 解决问题 B: 多模块项目中 discovery.json 只保留最后一个模块的数据
    if results:
        print(f"\n{'='*60}")
        print("Step 2.6: 生成统一 discovery.json（多模块聚合）")
        print(f"{'='*60}")
        all_discovery = []
        for slug, res in results.items():
            if not res.get('success'):
                continue
            disc_path = res.get('output', '')
            if not os.path.isfile(disc_path):
                # 尝试 merged 版本
                merged = _merge_discovery_files(probe_dir, slug)
                if merged:
                    disc_path = merged
            if os.path.isfile(disc_path):
                with open(disc_path, encoding='utf-8') as f:
                    data = json.load(f)
                all_discovery.append(data)

        unified_path = os.path.join(probe_dir, 'discovery.json')
        if len(all_discovery) == 1:
            # 单模块: 直接复制（与现有行为一致）
            import shutil
            src_path = results[list(results.keys())[0]].get('output', '')
            if os.path.isfile(src_path):
                shutil.copy2(src_path, unified_path)
            print(f"  [OK] 单模块 → {os.path.basename(unified_path)}")
        elif len(all_discovery) > 1:
            # 多模块: 聚合为 modules[] 格式，同时展平 list_page/containers 保持向后兼容
            _sections = ('buttons', 'row_buttons', 'inputs', 'tabs',
                         'detail_links', 'checkboxes', 'menu_items')
            flat_lp = {}
            flat_containers = []
            for disc in all_discovery:
                lp = disc.get('list_page', {})
                for sec in _sections:
                    if sec in lp:
                        flat_lp.setdefault(sec, []).extend(lp[sec])
                for c in disc.get('containers', []):
                    c_copy = dict(c)
                    c_copy['_source_module'] = disc.get('module', '')
                    flat_containers.append(c_copy)
            unified = {
                'modules': all_discovery,
                'module_count': len(all_discovery),
                'list_page': flat_lp,
                'containers': flat_containers,
            }
            with open(unified_path, 'w', encoding='utf-8') as f:
                json.dump(unified, f, ensure_ascii=False, indent=2)
            total_elems = sum(len(v) for v in flat_lp.values()) + sum(
                len(c.get('elements', [])) for c in flat_containers)
            print(f"  [OK] {len(all_discovery)} 模块聚合 → {os.path.basename(unified_path)} "
                  f"({total_elems} 元素, {len(flat_containers)} 容器)")

    # ── Step 3: 生成 pages YAML（v2: direct import — G17）──
    if not args.skip_generate:
        for slug, res in results.items():
            if not res.get('success'):
                print(f"[SKIP] {slug}: 探测失败，跳过 pages 生成")
                continue
            # M2: glob 合并 — 查找所有匹配的 discovery 文件
            merged_path = _merge_discovery_files(probe_dir, slug)
            discovery_input = merged_path if merged_path else res['output']

            out_pages_dir = os.path.join(args.project, 'pages', slug)
            os.makedirs(out_pages_dir, exist_ok=True)
            out_yaml = os.path.join(out_pages_dir, 'elements.yaml')

            print(f"\n{'='*60}")
            print(f"[Phase 4] Step 3: 生成 pages for {slug}")
            print(f"{'='*60}")
            try:
                _generate_pages_yaml(
                    discovery_path=discovery_input,
                    output_path=out_yaml,
                    module_name=res['cn_name'],
                    module_slug=slug,
                )
                print(f"[OK] {slug}: {out_yaml}")
            except Exception as e:
                print(f"[ERROR] {slug}: pages 生成失败 — {e}", file=sys.stderr)
    else:
        print("\n[Phase 4] --skip-generate: 跳过 pages YAML 生成")

    # ── Step 4: 汇总报告 ──
    print(f"\n{'='*60}")
    print(f"[Phase 4] 汇总报告")
    print(f"{'='*60}")

    total_ok = 0
    total_fail = 0
    total_elements = 0
    total_verified = 0

    for slug, res in results.items():
        status = '✅' if res.get('success') else '❌'
        if res.get('success'):
            total_ok += 1
        else:
            total_fail += 1

        # 从 discovery JSON 读取统计
        elem_count = 0
        ver_count = 0
        if res.get('success') and os.path.isfile(res.get('output', '')):
            try:
                with open(res['output'], encoding='utf-8') as f:
                    disc = json.load(f)
                # Aggregate across pages[] or top-level
                all_containers = []
                all_list_pages = []
                if 'pages' in disc:
                    for p in disc['pages']:
                        all_containers.extend(p.get('containers', []))
                        all_list_pages.append(p.get('list_page', {}))
                else:
                    all_containers = disc.get('containers', [])
                    all_list_pages = [disc.get('list_page', {})]

                for c in all_containers:
                    for e in c.get('elements', []):
                        elem_count += 1
                        if e.get('verified'):
                            ver_count += 1
                for lp in all_list_pages:
                    for cat in ['buttons', 'row_buttons', 'inputs', 'tabs',
                                'detail_links', 'checkboxes', 'menu_items']:
                        for e in lp.get(cat, []):
                            elem_count += 1
                            if e.get('verified'):
                                ver_count += 1
            except Exception:
                pass

        total_elements += elem_count
        total_verified += ver_count

        rate = round(100 * ver_count / max(elem_count, 1), 1) if elem_count else 0
        pages_count = res.get('urls_count', '?')
        print(f"  {status} {slug} ({res['cn_name']}): "
              f"{pages_count} URLs, {elem_count} elements, "
              f"{ver_count} verified ({rate}%)")

    overall_rate = round(100 * total_verified / max(total_elements, 1), 1)
    print(f"\n  总计: {total_ok} 成功 / {total_fail} 失败")
    print(f"  元素: {total_elements} total, {total_verified} verified ({overall_rate}%)")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
