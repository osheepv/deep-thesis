# Windows 可安装测试版

目标是 Windows 10/11 x64 用户下载安装后直接打开工作台，无需安装 Python 或执行命令。`0.1.0-beta.1` 安装器已经构建，并在临时全新目录完成安装、启动和退出验收：安装器大小约595MiB，内置 Python 3.13、CPU PyTorch 与本地检索依赖；安装后的程序没有从源码目录导入模块，API 和界面能正常启动，关闭启动窗口后两个服务都已回收。该版本仍是预发布测试版，尚未签名。

## 使用方式

1. 运行 `DeepThesis-0.1.0-beta.1-windows-x64-setup.exe`，按当前用户安装。
2. 从开始菜单或桌面打开 Deep Thesis。启动窗口会等待本地 API 和界面就绪，再打开默认浏览器中的论文工作台。
3. 在工作台配置自己的 DeepSeek 接口。安装包不包含作者密钥，不提供公共付费接口。
4. 关闭浏览器不停止后台服务，可从启动窗口重新打开。写作完成后点击“退出程序”。强制退出可能中断在途模型请求，下次需按任务恢复摘要继续。

程序默认安装在 `%LOCALAPPDATA%\Programs\Deep Thesis`。论文保存到 `%LOCALAPPDATA%\Deep Thesis\data`，日志位于其同级 `launcher` 目录；卸载程序不会删除论文和日志。启动窗口提供打开数据和日志目录的按钮。首版使用本机端口18787/18788，冲突时启动失败并保留日志；不自动开放防火墙。窗口只允许同一登录会话运行一份。

当前使用浏览器作为工作台，桌面窗口负责启动和停止；并非嵌入式网页桌面壳。首版尚未实现自动升级、安装签名、全新 Windows 系统验收和云端账号计费。当前安装包的 SHA-256 记录在发布附件 `SHA256SUMS.txt` 中；升级前须退出程序并备份论文数据，不能把构建通过等同于历史数据升级兼容性通过。

## 开发者构建

构建机需要 Windows x64、Python3.13、.NET Framework C#编译器及 Inno Setup 6。依赖由构建机通过官方 PyPI / PyTorch CPU源安装到私有运行时，最终用户不运行pip。Python使用官方3.13嵌入式x64包，完整附带许可证；构建命令必须提供下载包的SHA-256并事先验证来源。

```powershell
python scripts/build_windows.py --output-dir C:\Builds\DeepThesis-beta1 --python-zip C:\BuildTools\python-3.13.14-embed-amd64.zip --python-sha256 VERIFIED_SHA256 --iscc 'C:\BuildTools\Inno\ISCC.exe'
```

输出目录必须不存在。构建器仅使用Git已提交源码，包含前后端、提示词、内置模板和许可证，不读取工作区未跟踪数据库、外部报告或本地密钥。构建机目录中的未提交变更不会进入安装包。

输出包含安装EXE、SHA256SUMS、逐文件摘要清单、源提交号、依赖安装报告和独立运行时自检结果。构建器先用随包Python进行依赖、模板、跨进程任务/草稿恢复和下载自检，自检失败则不编译安装包。摘要用于完整性校验，不等于发布者签名。

## 待完成的发布检查

- 全新 Windows 用户/系统的安装、启动、退出、端口占用和卸载。
- 重复启动与异常关闭后的服务回收；旧版本升级后数据保留及备份恢复。
- 模型配置引导、密钥存储与日志脱敏；首次文献检索模型下载的网络提示。
- 真实联网完整十环浏览器验收、待审长稿和规范引用/交叉引用交付。
- 签名与第三方许可证复核、用户说明、GitHub预发布安装附件与反馈入口。

构建方案参考：[Python官方嵌入式发行说明](https://docs.python.org/3.13/using/windows.html#the-embeddable-package)、[Inno Setup当前用户安装](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)。
