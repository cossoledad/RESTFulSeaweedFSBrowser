# SeaweedFS Browser (PySide6 + Nuitka)

用于浏览 SeaweedFS Filer 中的文件与目录。

## 功能

- `Base URL` 输入框，默认值从本地配置加载（如 `http://10.1.23.81:38888`）
- `根目录` 输入框，默认值从本地配置加载（如 `/buckets/cax-dev/PARTING/`）
- 当前页搜索（按名称过滤当前目录已加载条目）
- 文件夹浏览（双击进入）
- 文件预览（双击文件，按文本预览）

## 配置文件位置

Windows 下默认保存在：

`%APPDATA%/SeaweedFSBrowser/config.json`

## 运行

```powershell
python main.py
```

## Nuitka 构建

standalone（默认）：

```powershell
.\build.ps1
```

onefile：

```powershell
.\build.ps1 -Mode onefile
```

可发布目录默认在 `release/SeaweedFSBrowser/`。

## GitHub CI

仓库已内置 GitHub Actions 工作流：

- 文件路径：`.github/workflows/ci.yml`
- 触发条件：
  - push 到 `main`/`master`
  - Pull Request
  - 手动触发（`workflow_dispatch`）

CI 包含两步：

1. `syntax-check`：在 Ubuntu 上执行 Python 语法检查  
2. `build-windows`：在 Windows 上执行 Nuitka 打包，并上传 `release/SeaweedFSBrowser` 作为 artifact

你可以在 GitHub 的 `Actions` 页面进入对应运行，下载 `SeaweedFSBrowser-windows-<run_number>` 产物进行验证。
