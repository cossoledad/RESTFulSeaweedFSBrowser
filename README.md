# SeaweedFS Browser (PySide6 + Nuitka)

用于浏览 SeaweedFS Filer 中的文件与目录。

当前版本：`1.0.5`

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

- 每次发布前新增对应版本文件，例如 `release-notes/v1.0.5.md`
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
