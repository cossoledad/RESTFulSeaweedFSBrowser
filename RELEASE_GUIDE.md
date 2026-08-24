# 发布流程

本仓库使用 GitHub Actions 工作流 [CI](.github/workflows/ci.yml) 完成测试、Windows 打包和 GitHub Release 发布。

## 触发规则

| 操作 | 触发的工作 | 结果 |
| --- | --- | --- |
| 推送到 `main` 或 `master` | `Syntax Check` → `Build Windows` | 运行测试并生成 Windows standalone Artifact，不创建 GitHub Release。 |
| 创建 Pull Request | `Syntax Check` → `Build Windows` | 运行测试并生成构建 Artifact，不创建 GitHub Release。 |
| 推送符合 `v*` 的标签 | `Syntax Check` → `Build Windows` → `Publish GitHub Release` | 验证版本、构建 ZIP、创建 GitHub Release 并上传附件。 |
| 在 Actions 页面手动运行 | 由输入的 ref 决定 | 仅运行构建检查；不会自动发布 Release。 |

默认发布分支应为仓库的默认分支；目前工作流同时支持 `main` 和 `master`。使用下列命令确认：

```powershell
git remote show origin
git branch --show-current
```

## 常规开发推送

完成功能和本地测试后，提交并推送到默认分支：

```powershell
git status
git diff --check
git add <需要提交的文件>
git commit -m "feat: 描述本次改动"
git push origin main
```

如果默认分支是 `master`，最后一行替换为：

```powershell
git push origin master
```

推送后在 GitHub Actions 中等待 `Syntax Check (Python 3.12)` 与 `Build Windows (Nuitka)` 成功。此阶段生成的 ZIP 只作为 Artifact 保存，不会显示在 Releases 页面。

## 正式发布

### 1. 准备版本内容

以版本 `X.Y.Z` 为例，发布前必须在同一个提交中完成：

- 将 `seaweed_browser/core.py` 中的 `APP_VERSION` 改为 `X.Y.Z`。
- 将 `README.md` 顶部的当前版本改为 `X.Y.Z`。
- 新建 `release-notes/vX.Y.Z.md`，写入用户可见的版本说明。
- 执行本地测试：

```powershell
.\.venv\Scripts\Activate.ps1
$files = @("main.py") + (Get-ChildItem seaweed_browser,tests -Filter *.py -File | ForEach-Object FullName)
python -m py_compile $files
python -m unittest discover -s tests -v
```

必要时运行 `./build.ps1` 并检查本地 standalone 程序。

### 2. 提交并推送发布提交

```powershell
git add README.md seaweed_browser/core.py release-notes/vX.Y.Z.md <本次功能文件>
git commit -m "release: vX.Y.Z"
git push origin main
```

等待该提交的分支 CI 成功；不要在未经验证的提交上打发布标签。

### 3. 创建并推送标签

标签格式必须严格为小写 `v` 加版本号，且标签指向已通过 CI 的发布提交：

```powershell
git log -1 --oneline
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

例如发布 `1.1.1`：

```powershell
git tag -a v1.1.1 -m "Release v1.1.1"
git push origin v1.1.1
```

标签推送会再次运行完整 CI。构建阶段从 `APP_VERSION` 生成期望标签 `vX.Y.Z`；发布阶段会校验实际标签相同。标签与 `APP_VERSION` 不一致时，`Publish GitHub Release` 会失败。

### 4. 发布后核验

当 `Publish GitHub Release` 成功后，在 GitHub Releases 页面确认：

- Release 名称为 `Release vX.Y.Z`。
- 发布说明来自 `release-notes/vX.Y.Z.md`。
- 附件为 `SeaweedFSBrowser-vX.Y.Z-windows-x64-standalone.zip`。
- 下载、解压并运行 `SeaweedFSBrowser.exe`，确认不需要目标机器安装 Python。

## 修复已发布版本的问题

不要移动、删除后重推或复用已发布的标签。修复后递增补丁版本，重新走“准备版本内容 → 推送发布提交 → 推送新标签”的完整流程，例如从 `v1.1.1` 发布 `v1.1.2`。
