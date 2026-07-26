# SeaweedFS Browser (PySide6 + Nuitka)

用于浏览 SeaweedFS Filer 中的文件与目录。

当前版本：`1.0.10`

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
- 文本、图片和详细信息预览使用非模态窗口，可在预览最小化或保持打开时继续操作主窗口
- 同一服务上的同一文件只保留一个同类型预览窗口，再次打开时自动恢复并激活
- 文本、图片和模型预览在后台线程下载和准备，加载期间主窗口保持可用
- 每个预览加载任务提供非模态进度窗口和取消操作
- 跟踪 F3D 模型预览子进程，避免同一模型重复打开，并在主程序退出时统一清理
- 目录加载、文件保存、递归保存和预览任务使用统一的后台任务生命周期，支持安全取消和退出回收
- 单文件保存采用后台下载和临时文件原子替换，失败或取消不会覆盖已有文件
- 对远端文件路径进行 URL 编码，对递归保存目标进行路径越界保护
- 目录缓存：已进入过的目录优先使用缓存，点击“刷新当前目录”或按 `F5` 才重新加载

## 项目结构

- `main.py`：应用入口、主窗口和 F3D 子进程入口
- `seaweed_browser/core.py`：版本、配置、路径和格式化规则
- `seaweed_browser/client.py`：SeaweedFS HTTP 访问与原子下载
- `seaweed_browser/tasks.py`：统一任务管理器及后台 Worker
- `seaweed_browser/model_files.py`：GLB/GLTF 格式及外部资源解析
- `seaweed_browser/widgets.py`：文本、图片和详细信息预览控件
- `tests/`：不依赖图形环境的核心单元测试

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

GitHub Actions 在 PR 和 `master` push 时只执行检查与构建；仅推送与
`APP_VERSION` 一致的 `v*` tag 时才创建 GitHub Release。
