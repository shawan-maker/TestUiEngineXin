# Phase 2: 页面结构探测规则

## R2.1 页面可达性检查

目标页面必须可访问（HTTP 200），否则停止生成并告知用户。

## R2.2 UI 框架识别

必须识别页面使用的 UI 框架（Element UI / Ant Design / 等），用于后续 probe 加载对应模式库。

## R2.3 页面结构检测

必须检测以下页面结构特征：

| 检测项 | 输出字段 | 用途 |
|--------|---------|------|
| Loading 遮罩 | `has_loading_mask` | 生成等待步骤 |
| 表格结构 | `table_structure` | 决定表格按钮探测路径 |
| 容器类型 | `container_type` | 决定元素作用域前缀（drawer/dialog） |
| 导出按钮 | `export_buttons` | 生成下载文件步骤 |

## R2.4 下拉选项采集

对页面上的 el-select 组件，采集其选项列表，用于验证用户选择的选项是否存在。

## R2.5 等待策略生成

根据检测结果自动生成等待策略：

| 检测条件 | 生成的等待步骤 |
|---------|--------------|
| has_loading_mask=true | `wait_for_element_hidden(xpath=//div[contains(@class,'el-loading-mask')], 15000)` |
| 有表格 | `wait_for_element_hidden(xpath=//div[contains(@class,'el-loading-mask')], 15000)` after click |
| 有 el-select | `wait_for_time(500)` after select option |

## R2.6 Harvest 输出精简

Harvest 输出**只保留有价值字段**，禁止输出完整 elements 列表：

```json
{
  "url": "...",
  "title": "...",
  "ui_framework": ["Element UI"],
  "detected_patterns": {
    "has_loading_mask": true,
    "table_structure": {"has_table": true, "has_fixed_right": true, "column_count": 14},
    "container_type": "drawer",
    "export_buttons": [...]
  },
  "select_options": [...],
  "wait_strategy": {...}
}
```

**禁止输出**：
- `elements` 列表（60+ 个元素，价值低）
- 每个元素的 tag/text/class（probe 按需探测即可）
