# SeaweedFS Browser (PySide6 + Nuitka)

用于浏览 SeaweedFS Filer 中的文件与目录。

当前版本：`1.0.13`

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
- 在当前远程目录新建文件夹，名称经过路径边界校验
- 选择一个或多个本地文件上传到当前目录，同名文件默认覆盖
- 上传采用固定并发流式传输，不会将大文件整体读入内存
- 上传任务可取消；部分失败时可只重试失败项
- 文本文件预览（双击文件，按文本预览）
- 图片预览（支持 `png/jpg/jpeg/bmp/gif/webp`）
- 模型预览（支持 `glb/gltf`，通过 `f3d` 打开）
- 文本、图片和详细信息预览使用非模态窗口，可在预览最小化或保持打开时继续操作主窗口
- 同一服务上的同一文件只保留一个同类型预览窗口，再次打开时自动恢复并激活
- 文本、图片和模型预览在后台线程下载和准备，加载期间主窗口保持可用
- 上传、下载、目录加载和预览准备统一进入任务中心，可查看状态、进度和错误并取消任务
- 状态栏自动汇总后台任务，多个任务并行时展示总数和最高优先级任务
- 已结束任务保留最近 50 条历史，业务结果不进入任务状态快照，避免任务中心持有大对象
- 跟踪 F3D 模型预览子进程，避免同一模型重复打开，并在主程序退出时统一清理
- 目录加载、文件保存、递归保存和预览任务使用统一的后台任务生命周期，支持安全取消和退出回收
- 单文件保存采用后台下载和临时文件原子替换，失败或取消不会覆盖已有文件
- 对远端文件路径进行 URL 编码，对递归保存目标进行路径越界保护
- 目录缓存：最多保留 32 个最近访问目录，点击“刷新当前目录”或按 `F5` 可重新加载
- 递归保存默认并发下载 4 个文件，提高大量小文件的保存吞吐
- 预览准备和单文件保存分别限制为最多 3 个并发任务，避免无界创建后台线程

## 项目结构

- `main.py`：应用入口、主窗口和 F3D 子进程入口
- `seaweed_browser/core.py`：版本、配置、路径和格式化规则
- `seaweed_browser/client.py`：SeaweedFS HTTP 访问、流式上传与原子下载
- `seaweed_browser/tasks.py`：上传、下载、目录加载和预览后台 Worker
- `seaweed_browser/task_models.py`：统一任务状态、进度和错误模型
- `seaweed_browser/task_runtime.py`：后台线程生命周期、并发限制、去重和取消
- `seaweed_browser/task_presenter.py`：状态栏任务摘要
- `seaweed_browser/task_widgets.py`：可停靠任务中心
- `seaweed_browser/cache.py`：有界 LRU 缓存
- `seaweed_browser/downloads.py`：固定并发批量下载调度
- `seaweed_browser/uploads.py`：上传计划、固定并发调度和部分失败汇总
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
  "page_limit": 1000,
  "directory_cache_max_entries": 32,
  "directory_download_workers": 4,
  "upload_workers": 3,
  "max_concurrent_preview_loads": 3,
  "max_concurrent_file_saves": 3
}
```

为避免配置错误耗尽资源，目录缓存最多允许 256 项，递归下载和上传线程最多 16 个，
预览准备和单文件保存任务上限最多 16 个。

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
