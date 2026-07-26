# SeaweedFS Browser (PySide6 + Nuitka)

用于浏览 SeaweedFS Filer 中的文件与目录。

当前版本：`1.0.7`

## Windows 下载

普通用户请从 [Releases](https://github.com/cossoledad/RESTFulSeaweedFSBrowser/releases)
下载名称类似下面的独立运行包：

`SeaweedFSBrowser-v<版本>-windows-x64-standalone.zip`

仓库首页的 `Code -> Download ZIP` 和 Release 中自动生成的 `Source code`
仅包含源代码，不包含 Python、PySide6 或 F3D 运行环境。

## 功能

- `Base URL` 输入框，默认值从本地配置加载（如 `http://10.1.23.81:38888`）
- `根目录` 输入框，默认值从本地配置加载（如 `/buckets/cax-dev/PARTING/`）
- `PAGE_LIMIT` 支持写入本地配置文件，通过 `config.json` 中的 `page_limit` 调整单次分页大小
- 当前页搜索（按名称过滤当前目录已加载条目）
- 文件列表支持点击任意列表头排序，大小、时间、分块数按原始值排序
- 文件夹浏览（双击进入）
- 文本文件预览（双击文件，按文本预览）
- 图片预览（支持 `png/jpg/jpeg/bmp/gif/webp`）
- 模型预览（支持 `glb/gltf`，通过 `f3d` 打开）
- 目录缓存：已进入过的目录优先使用缓存，点击“刷新当前目录”或按 `F5` 才重新加载

## 发布说明

- 每次发布前新增对应版本文件，例如 `release-notes/v1.0.6.md`
- 推送 tag（如 `v1.0.5`）后，GitHub Actions 会自动读取该文件作为 Release 说明

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

构建脚本会强制检查 F3D Python 扩展、DLL 和资源目录，并在生成发布包后运行：

```powershell
SeaweedFSBrowser.exe --check-f3d-runtime
```

只有 F3D 导入和打包程序预览启动参数均通过自检时，构建才会成功。
