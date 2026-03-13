# SeaweedFS Browser (PySide6 + Nuitka)

用于浏览 SeaweedFS Filer 中的文件与目录。

当前版本：`1.0.3`

## 功能

- `Base URL` 输入框，默认值从本地配置加载（如 `http://10.1.23.81:38888`）
- `根目录` 输入框，默认值从本地配置加载（如 `/buckets/cax-dev/PARTING/`）
- `PAGE_LIMIT` 支持写入本地配置文件，通过 `config.json` 中的 `page_limit` 调整单次分页大小
- 当前页搜索（按名称过滤当前目录已加载条目）
- 文件列表支持点击任意列表头排序，大小、时间、分块数按原始值排序
- 程序启动时会先弹出“关于”窗口，显示当前版本信息
- 文件夹浏览（双击进入）
- 文件预览（双击文件，按文本预览）

## 配置文件位置

Windows 下默认保存在：

`%APPDATA%/SeaweedFSBrowser/config.json`

配置示例：

```json
{
  "base_url": "http://10.1.23.81:38888",
  "root_dir": "/buckets/cax-dev/files/",
  "page_limit": 1000
}
```

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

构建产物目录和文件名会自动带版本号，例如：

- `release/SeaweedFSBrowser-v1.0.3-windows-x64-standalone/`
- `release/SeaweedFSBrowser-v1.0.3-windows-x64-onefile/SeaweedFSBrowser-v1.0.3-windows-x64-onefile.exe`

## CI / Release

仓库内置 GitHub Actions 工作流：

- `syntax-check`：执行 `python -m py_compile main.py`
- `build-windows`：执行 Nuitka Windows 构建
- `push` 到 `main` 或 `master` 且构建成功后，自动发布 GitHub Release

Release 资产会自动带版本号，例如：

- `SeaweedFSBrowser-v1.0.3-windows-x64-standalone.zip`
