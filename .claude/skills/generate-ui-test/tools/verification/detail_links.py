"""
detail_links.py - Detail link 处理

从 verify_locators.py 提取的 detail link 处理函数：
- _write_verify_result: 写入验证结果 JSON
- _consume_pending_detail_links: 消费待处理的 detail link
- _try_kb_resolve_detail_links: 尝试用知识库解析 detail link
"""

import os
import re
import sys
import json

try:
    import yaml
except ImportError:
    print("[FATAL] pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ─── Shared imports ───
from core.yaml_utils import escape_yaml_scalar as _escape_yaml_scalar


def _write_verify_result(project_dir, result):
    """P3f-3: 写入 _probe/verify_result.json 供 _phase_registry.py 检查"""
    import hashlib, datetime

    probe_dir = os.path.join(project_dir, '_probe')
    os.makedirs(probe_dir, exist_ok=True)

    # 防伪造签名
    fingerprint = hashlib.sha256(
        f"{project_dir}:{result.get('total_steps', 0)}:"
        f"{result.get('verified', 0)}:{result.get('writeback_count', 0)}".encode()
    ).hexdigest()[:16]

    output = {
        'total_steps': result.get('total_steps', 0),
        'verified': result.get('verified', 0),
        'failed': result.get('failed', 0),
        'skipped': result.get('skipped', 0),
        'writeback_count': result.get('writeback_count', 0),
        'fingerprint': fingerprint,
        'run_timestamp': datetime.datetime.now().isoformat(),
        'modules_verified': result.get('modules_verified', []),
    }

    path = os.path.join(probe_dir, 'verify_result.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] verify_result.json written: {path}")


def _consume_pending_detail_links(project_dir, cookie, url, local_storage=None):
    """M20: 自动消费 pending_detail_links.json

    如果 _probe/pending_detail_links.json 存在且非空，
    用 KB 模板在浏览器中直接探测 locator，解决后清理文件。
    不再调用 probe_from_pages.py subprocess。
    """
    pending_file = os.path.join(project_dir, '_probe', 'pending_detail_links.json')
    if not os.path.isfile(pending_file):
        return

    try:
        with open(pending_file, encoding='utf-8') as f:
            pending = json.load(f)
    except Exception:
        return

    if not pending:
        return

    print(f"[M20] 发现 {len(pending)} 个 pending detail-link")

    # ── KB 模板浏览器直连探测 ──
    resolved = _try_kb_resolve_detail_links(
        project_dir, pending, cookie, url, local_storage)
    if resolved:
        # 移除已解决的条目
        resolved_keys = {(r['group'], r['field']) for r in resolved}
        remaining = [p for p in pending
                     if (p.get('group'), p.get('field')) not in resolved_keys]
        if not remaining:
            os.remove(pending_file)
            print(f"[M20] 所有 detail-link 已通过 KB 模板解决 ({len(resolved)} 个)")
            return
        # 更新 pending 文件
        with open(pending_file, 'w', encoding='utf-8') as f:
            json.dump(remaining, f, ensure_ascii=False, indent=2)
        print(f"[M20] KB 解决 {len(resolved)} 个，剩余 {len(remaining)} 个待 Phase 6 预执行处理")
    else:
        print(f"[M20] KB 模板未匹配，{len(pending)} 个 detail-link 将在 Phase 6 预执行中处理")


# KB detail-link 模式（文本无关的 class-based 优先，文本依赖的兜底）
_KB_DETAIL_LINK_PATTERNS = [
    # 纯 class-based（不依赖文本，通用性最强）
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"common-href")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"link-style")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"click-list")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"resource-id")]',
    '//td[not(contains(@class,"is-hidden"))]//*[@class="edit-name"]/preceding-sibling::div[contains(@class,"link-style")]',
    # 文本依赖（需要 label 替换）
    '//td[not(contains(@class,"is-hidden"))]//*[contains(text(),"{label}")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"link-style") or contains(@class,"click-list") or contains(@class,"resource-id") or contains(@class,"name")][contains(.,"{label}")]',
]


def _try_kb_resolve_detail_links(project_dir, pending, cookie, url,
                                   local_storage_override=None):
    """用 KB detail-link 模板在浏览器中直接探测 locator。

    返回已解决的条目列表 [{group, field, locator}, ...]，空列表表示全部失败。
    """
    if not pending:
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[M20-KB] playwright 未安装，跳过 KB 探测")
        return []

    resolved = []
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
        domain = urlparse(url).hostname
        cookies = parse_cookie(cookie, domain)
        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)

        # Inject localStorage (same logic as main verify)
        local_storage = {}
        config_path = os.path.join(project_dir, 'config.yaml')
        if os.path.isfile(config_path):
            try:
                with open(config_path, encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                if isinstance(cfg.get('local_storage'), dict):
                    for k, v in cfg['local_storage'].items():
                        local_storage[str(k)] = str(v)
            except Exception:
                pass
        if local_storage_override:
            try:
                override = json.loads(local_storage_override) if isinstance(
                    local_storage_override, str) else local_storage_override
                if isinstance(override, dict):
                    for k, v in override.items():
                        local_storage[str(k)] = str(v)
            except Exception:
                pass
        for c in cookies:
            if c['name'] in TOKEN_KEYS:
                local_storage[c['name']] = c['value']

        page = context.new_page()

        # Pre-inject localStorage via init_script (runs BEFORE any page script)
        # Prevents SPA router guards from redirecting to /login on first navigation.
        if local_storage:
            ls_items = ', '.join(
                f'localStorage.setItem({json.dumps(k)}, {json.dumps(v)})'
                for k, v in local_storage.items()
            )
            page.add_init_script(f'() => {{ {ls_items} }}')

        # Navigate — init_script already injected localStorage, SPA guard can read token
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_dom_stable(page, timeout_ms=5000)

        # Belt-and-suspenders: ensure localStorage is set
        for k, v in local_storage.items():
            page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])

        # Check auth validity
        if '/login' in page.url:
            print("[M20-KB] Cookie 无效，跳过 KB 探测")
            return []

        # Try to get first row text for label substitution
        first_row_text = None
        try:
            first_row_text = page.evaluate("""() => {
                const row = document.querySelector('table tbody tr');
                if (!row) return null;
                const cells = row.querySelectorAll('td');
                for (const cell of cells) {
                    const t = (cell.textContent || '').trim();
                    if (t && t.length > 2 && t.length < 50) return t;
                }
                return null;
            }""")
        except Exception:
            pass

        # Try each pending entry
        for entry in pending:
            group = entry.get('group', '')
            field = entry.get('field', '')
            label = entry.get('label', '')

            for pattern in _KB_DETAIL_LINK_PATTERNS:
                # Substitute {label} if present
                xpath = pattern
                if '{label}' in xpath:
                    if not first_row_text and not label:
                        continue
                    xpath = xpath.replace('{label}', first_row_text or label)

                try:
                    count = page.locator(f'xpath={xpath}').count()
                    if count == 1:
                        locator = f'xpath={xpath}'
                        resolved.append({
                            'group': group,
                            'field': field,
                            'locator': locator,
                        })
                        print(f"[M20-KB] ✅ {group}.{field} → {locator[:60]}...")
                        break
                except Exception:
                    continue

        # Write back resolved locators to pages YAML
        if resolved:
            verified_locators = {}
            for r in resolved:
                ref = f"{r['group']}.{r['field']}"
                verified_locators[ref] = {
                    'locator': r['locator'],
                    'marker': '[KB-DETAIL-LINK]',
                    'container_type': None,
                    'is_new_field': False,
                }
            update_pages_yaml(project_dir, verified_locators)

    except Exception as e:
        print(f"[M20-KB] KB 探测异常: {e}")
    finally:
        try:
            pw.stop()
        except Exception:
            pass

    return resolved


# ============================================================================
# Phase 2: Gap Scan + Auto-Supplement
# ============================================================================
