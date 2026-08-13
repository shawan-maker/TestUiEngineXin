# PyPI 上传超时解决方案

## 问题原因
`upload.pypi.org` 在中国大陆被墙或限速，直接连接超时。

## 解决方案

### 方案 1：使用代理（推荐）

如果你有代理（VPN/SSR/Clash 等），设置环境变量后上传：

**Windows PowerShell:**
```powershell
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
twine upload dist/*
```

**Linux/Mac:**
```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
twine upload dist/*
```

**常见代理端口：**
- Clash: 7890
- V2rayN: 10809
- SSR: 1080
- Shadowsocks: 8388

### 方案 2：增加超时时间

```bash
twine upload --timeout 120 dist/*
```

但这通常不够，因为问题是连接被阻断，不是慢。

### 方案 3：使用海外服务器上传

如果你有海外 VPS：
1. 将 `dist/` 目录传到 VPS
2. 在 VPS 上执行 `twine upload dist/*`

### 方案 4：GitHub Actions 自动发布

在 GitHub 仓库创建 `.github/workflows/publish.yml`：

```yaml
name: Upload Python Package

on:
  release:
    types: [published]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v3
      with:
        python-version: '3.x'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install build twine
    - name: Build package
      run: python -m build
    - name: Publish package
      uses: pypa/gh-action-pypi-publish@27b31702a0e7fc50959f5ad993c78deac1bdfc29
      with:
        user: __token__
        password: ${{ secrets.PYPI_API_TOKEN }}
```

然后在 GitHub Settings → Secrets 中添加 `PYPI_API_TOKEN`。

## 验证代理是否生效

```bash
# 测试能否连接 PyPI
curl -I https://upload.pypi.org
```

如果返回 `HTTP/1.1 200 OK` 或 `HTTP/2 200`，说明代理生效。

## 推荐流程

1. 启动你的代理软件（Clash/V2rayN 等）
2. 找到代理端口（通常在软件设置中）
3. 设置环境变量
4. 执行 `twine upload dist/*`
