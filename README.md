# Task Manager Python

React界面 + Electron桌面适配 + Python业务后端的Windows本地任务管理器。

待办树、日期与完成联动、SQLite、草稿确认、备份、Canvas、AI、IMAP/Microsoft邮箱、离线邮件、分析和持久化后台任务均由Python处理。Electron负责窗口、托盘、文件选择、系统通知、开机启动和旧凭据的一次性原生迁移。

## 日常使用

本仓库只保存源码，不上传已构建程序。执行 `npm run dist` 可在本机生成 `release-v2/Task Manager.zip`。解压后运行 `Task Manager.exe`，保留整个文件夹，不能只复制exe。生成的发布包自带Python，使用时不要求电脑另行安装Python或Node。

数据保存在应用旁边的 `data` 文件夹；移动和备份应用时一并保留。AI服务和邮箱需要自行配置真实服务、密钥或授权；本次迁移未复制旧项目的真实数据和凭据。

## 开发环境

开发时需要创建项目专属Python环境 `.venv`。`npm run dev` 和 `npm run test:python` 明确使用它，不依赖PATH中的全局Python。发布包另外携带独立Python3.14.10运行时。

克隆本仓库后，在项目目录中安装独立的Python和Node依赖：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm ci
npm run dev
```

如果本机pip索引/代理配置异常，可执行 `.venv\Scripts\python.exe scripts\install-python-deps.py`：从官方PyPI下载固定版本wheel、验证官方SHA256后装到项目环境。

## 验证与发布

```powershell
npm run check
npm run test:runtime
npm run dist
npm run test:package
```

- `check`：类型、Python后端、React/桌面与兼容测试、生产构建。
- `test:runtime`：隐藏真实Electron双窗口、Python/邮箱/worker调用链及合成旧凭据迁移。
- `dist`：生成自带运行时的Windows ZIP并验证发布内容。首次需要下载官方Python发布包；后续可用校验通过的缓存。
- `test:package`：直接验证app.asar中实际桥接、包内Python、数据库与后台worker。

`npm run dev:legacy`仅供开发时对照原TypeScript后端；正式包不包含旧TypeScript业务模块。两种模式不能同时写同一data。

详细产品规则和邮箱配置指引在docs目录。仓库排除运行数据、密钥、虚拟环境、日志、发布包、截图和本机交接记录。真实学校OAuth、真实邮件和云端AI仍需实际账号验收；自动化使用合成数据和受控响应。
