/**
 * _ai_validate_result.js — 深度扫描/AI 结果验证门控（浏览器端）
 *
 * 三道防线：
 * 1. 文本匹配校验（按钮文本、输入框 placeholder/相邻 label）
 * 2. 容器上下文校验（dialog/drawer 内的元素必须在容器内）
 * 3. 元素类型校验（tag 符合 elem_type 预期）
 *
 * Phase 6 定位验证链路优化方案 §4.3
 */

function validateDeepScanResult(xpath, label, elemType, containerContext) {
  try {
    const element = document.evaluate(
      xpath, document, null,
      XPathResult.FIRST_ORDERED_NODE_TYPE, null
    ).singleNodeValue;

    if (!element) {
      return { valid: false, reason: 'element not found' };
    }

    const tag = element.tagName.toLowerCase();
    const text = (element.textContent || '').trim();
    const placeholder = element.getAttribute('placeholder') || '';
    const classes = element.className || '';

    // ═══ 防线 1: 文本匹配校验 ═══
    // 按钮类：元素文本必须包含 label
    if (['button', 'submit-btn', 'tab', 'table-action-button',
         'search-button', 'download-button'].includes(elemType)) {
      if (!text.includes(label)) {
        return {
          valid: false,
          reason: `button text='${text}' 不包含 label='${label}'`
        };
      }
    }

    // 输入类：检查 placeholder 或相邻 label
    if (['input-generic', 'textarea-generic'].includes(elemType)) {
      // 增强：检查是否在 el-select 内部
      if (element.closest('.el-select, .ant-select')) {
        return {
          valid: false,
          reason: 'input 在 el-select 内部，可能是误匹配'
        };
      }

      if (!text.includes(label) && !placeholder.includes(label)) {
        // 检查相邻 label 元素
        const formItem = element.closest('.el-form-item, .ant-form-item');
        if (formItem) {
          const labelEl = formItem.querySelector('label');
          const parentLabel = labelEl ? labelEl.textContent.trim() : '';
          if (!parentLabel.includes(label)) {
            return {
              valid: false,
              reason: `input 无文本关联: text='${text}', placeholder='${placeholder}', parent_label='${parentLabel}'`
            };
          }
        } else {
          return {
            valid: false,
            reason: 'input 无法验证文本关联'
          };
        }
      }
    }

    // select/cascader：检查相邻 label
    if (['el-select', 'el-cascader'].includes(elemType)) {
      const formItem = element.closest('.el-form-item, .ant-form-item');
      if (formItem) {
        const labelEl = formItem.querySelector('label');
        const parentLabel = labelEl ? labelEl.textContent.trim() : '';
        if (!parentLabel.includes(label)) {
          return {
            valid: false,
            reason: `select 无文本关联: parent_label='${parentLabel}'`
          };
        }
      } else {
        return {
          valid: false,
          reason: 'select 无法验证文本关联'
        };
      }
    }

    // ═══ 防线 2: 容器上下文校验 ═══
    if (['dialog', 'drawer', 'message-box', 'ant-modal', 'ant-drawer'].includes(containerContext)) {
      const containerSelectors = {
        'dialog': '.el-dialog, .ant-modal',
        'drawer': '.el-drawer, .ant-drawer',
        'message-box': '.el-message-box, .ant-modal-confirm',
        'ant-modal': '.ant-modal',
        'ant-drawer': '.ant-drawer'
      };
      const selector = containerSelectors[containerContext] || '';
      if (selector && !element.closest(selector)) {
        return {
          valid: false,
          reason: `元素不在期望容器 ${containerContext} 内`
        };
      }
    }

    // ═══ 防线 3: 元素类型校验 ═══
    const expectedTags = {
      'button': ['button', 'a', 'span'],
      'submit-btn': ['button'],
      'input-generic': ['input', 'textarea'],
      'textarea-generic': ['textarea'],
      'el-select': ['input', 'div'],
      'el-cascader': ['input', 'div'],
      'tab': ['div', 'li', 'a'],
      'table-action-button': ['button', 'a', 'span'],
    };
    if (expectedTags[elemType] && !expectedTags[elemType].includes(tag)) {
      return {
        valid: false,
        reason: `tag='${tag}' 不符合 elem_type=${elemType}`
      };
    }

    // 所有防线通过
    return {
      valid: true,
      reason: `tag=${tag}, text='${text.substring(0, 30)}'`
    };

  } catch (e) {
    return {
      valid: false,
      reason: `validation error: ${e.message}`
    };
  }
}

return validateDeepScanResult(xpath, label, elemType, containerContext);
