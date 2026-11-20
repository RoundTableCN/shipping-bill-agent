# GitHub 交付说明

本目录是清理后的 GitHub 上传版本，不包含本机运行产物、OCR 原始响应、日志、虚拟环境和 API Key。

## 已排除

- `out/`：OCR 原始响应、签名 URL、临时解析结果
- `dist/`：本机生成的 zip/解压目录
- `资料/`：原始面试材料和真实业务样本
- `_analysis/`：本地调试脚本和截图
- `data/samples/`：真实业务账单样例
- `data/fixtures/sample_prealert.eml`：真实邮件及附件样例
- `data/golden/expected/.run/`：golden 生成过程残留的邮件附件
- `.env`、`.venv/`、`__pycache__/`、`.pytest_cache/`

## 上传前检查

```text
确认仓库中没有 .env
确认仓库中没有 API Key / token / OSS 签名 URL
确认 data/samples、sample_prealert.eml、.run 已删除
```

当前公开版本已删除真实样例；依赖这些样例的测试会自动 skip。清理后测试结果：

```text
129 passed, 131 skipped
```

完整本地工作区（包含原始样例）仍然是：

```text
260 passed
```

## 方式一：GitHub Desktop（推荐）

1. 打开 GitHub Desktop，登录 GitHub。
2. `File -> Add local repository`，选择本目录。
3. 如果提示不是 Git 仓库，选择 `create a repository`。
4. 填写仓库名，例如 `shipping-bill-agent`，提交信息：
   `Interview submission: shipping bill agent`
5. 点击 `Publish repository`。
6. 私有仓库请取消 `Keep this code private` 的勾选前先确认样本数据可公开；
   建议先保持 Private。

## 方式二：Git 命令行上传

先检查 Git 是否可用：

```powershell
git --version
```

如果当前终端找不到 `git`，但本机确实已安装 Git，可以：

- 使用 Git Bash；
- 使用 Git 的完整路径，例如 `"C:\Program Files\Git\cmd\git.exe"`；
- 或改用 GitHub Desktop。

GitHub CLI `gh` 当前未安装；只使用 `git` 也可以上传：

```bash
git init
git add .
git commit -m "Interview submission: shipping bill agent"
git branch -M main
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

如果想使用 `gh repo create`，再安装 GitHub CLI：

```powershell
winget install --id GitHub.cli -e --source winget
```

然后：

```bash
gh auth login
gh repo create shipping-bill-agent --private --source=. --remote=origin --push
```

如果已经有仓库，则使用：

```bash
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

## 方式三：GitHub 网页上传

1. 新建仓库。
2. 在仓库页面选择 `Add file -> Upload files`。
3. 把本目录中的文件和文件夹拖进去。
4. 提交。

## 发布面试压缩包

本目录同级已经有：

```text
dist/shipping-bill-agent-github.zip
```

可以在 GitHub 仓库的 `Releases -> Draft a new release` 中作为附件上传，不要把它直接提交到源码目录。

## 许可证

本目录附带 `LICENSE`：

- 仅用于面试评估和代码审阅；
- 未经作者书面许可，不得用于商业复用或再分发。

如果希望开源复用，请把 `LICENSE` 替换为 MIT、Apache-2.0 等正式许可证。

## 运行

```text
python -m pytest -q
python scripts/launch_streamlit.py
```

Windows 可双击 `start_app.bat`。

首次运行会询问 AI API；也可以选择“不使用大模型（规则抽取）”。
