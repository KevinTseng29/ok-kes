# Windows 实验版打包

使用 Windows x64、Python 3.12 和项目本地虚拟环境。源码仍显示 `dev`，版本号仅写入打包暂存副本。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe scripts/build_portable.py --version v1.4.10-alpha.1
```

产物位于 `dist`：单文件便携 exe 和 `SHA256SUMS.txt`。用户直接双击 exe，无需安装 Python；程序会请求管理员权限，配置写入 exe 旁的 `configs` 目录。

打包脚本仅复制 `main.py`、`src`、`ok_tasks`、图标、翻译及必要图片到 `build` 下的独立暂存目录，不打包个人配置、日志、截图、研究样本或虚拟环境。PyInstaller 从当前虚拟环境收集运行库和 OCR 模型，不改动第三方库或源码版本字段。

OpenCC 运行库需要纯英文资源路径，因此单文件运行时会解压到 `C:\Temp\ok-kes` 下的独立临时目录。输出目录与中间文件均被 Git 忽略，exe 只作为 Release 附件发布。

## 冻结程序自检

自检不连接游戏、不发送点击，也不联网解码卡组。它检查本地动态库、OpenCC 字典、实验任务、预设编辑器、中文卡牌映射和 UI 资源，并实际执行一次 OCR 模型推理。

```powershell
$exe = (Get-ChildItem dist/ok-kes-experimental-win64-*.exe | Select-Object -First 1).FullName
$report = Join-Path (Get-Location) "build/portable-self-test.json"
$env:__COMPAT_LAYER = "RunAsInvoker"
$process = Start-Process -FilePath $exe -ArgumentList @("--self-test", "--self-test-report", "`"$report`"") -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "冻结程序自检失败，请检查 $report" }
Get-Content $report
```

`RunAsInvoker` 仅用于不操作游戏的构建自检；正常双击 exe 仍会请求管理员权限。

## GitHub 发布

推送 `v*-alpha.*` 注解标签后，`.github/workflows/build.yml` 会在 Windows 上运行测试、重新打包和冻结自检，全部成功后向当前仓库发布预发布 Release。仅使用当前仓库的 `GITHUB_TOKEN`，不依赖上游 CNB、Mirror酱或维护者的密钥。

也可手动触发工作流，填写已经存在的版本标签。实验功能和限制见 [实验版发布说明](docs/releases/experimental.md)。不要将 exe、`configs`、`.venv`、`build` 或 `dist` 提交到 Git。
