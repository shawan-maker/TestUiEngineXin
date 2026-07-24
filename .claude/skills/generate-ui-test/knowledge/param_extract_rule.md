# 参数化提取规则

## 识别条件

当多个用例同时满足以下条件时，判定为"结构相似"，应提取为参数化数据：

1. **步骤数量相同**
2. **每步的 keyword 相同**（如都是 fill_value → click → assert）
3. **每步的 locator 相同**（操作同一组元素）
4. **仅 params 中的值不同**（输入的文本、期望的结果不同）

## 提取流程

### 输入：3 个结构相似的用例

```
用例1: 用户名=admin, 密码=123456 → 期望：登录成功
用例2: 用户名=admin, 密码=wrong  → 期望：密码错误
用例3: 用户名="",    密码=123456 → 期望：用户名不能为空
```

### 分析

3 个用例步骤结构完全相同（输入用户名 → 输入密码 → 点击登录 → 验证），仅数据不同。

### 输出

**data 文件**（变化部分）：
```yaml
dataset_1:
  name: "正确密码登录"
  username: "admin"
  password: "123456"
  expected_welcome: "欢迎, admin"
  expected_error: ""

dataset_2:
  name: "错误密码登录"
  username: "admin"
  password: "wrong"
  expected_welcome: ""
  expected_error: "密码错误"

dataset_3:
  name: "用户名为空"
  username: ""
  password: "123456"
  expected_welcome: ""
  expected_error: "用户名不能为空"
```

**case 文件**（不变部分 + 数据引用，文件名含序号如 `01_login_valid.yaml`）：
```yaml
id: "login-valid"
name: "正确密码登录"
steps:
  - desc: "输入用户名"
    keyword: "fill_value"
    params:
      locator: "${login_page.username_input}"
      value: "${dataset_1.username}"
```

## 命名规则

| 对象 | 命名格式 | 示例 |
|------|---------|------|
| 数据集 | `dataset_N` | `dataset_1`, `dataset_2` |
| 数据集 name 字段 | 描述用例目的 | `"正确密码登录"` |
| data 文件 | `{模块}_{功能}_data.yaml` | `login_data.yaml` |
| case 文件 | `{序号:02d}_{功能}_{场景}.yaml` | `01_valid_login.yaml` |

## 不满足参数化条件时

如果用例之间步骤结构差异较大（步骤数不同、keyword 不同、操作元素不同）：
- **不做参数化**，每个用例独立编写
- data 文件中只提取公共数据（如 URL、通用账号）
